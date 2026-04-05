from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import StudySession
from tasks.models import Task
from sleep.models import SleepStudyPreference
from datetime import date, timedelta, time
from core.schedule_engine import generate_study_sessions, calculate_progress

# Day name helpers
DAY_MAP = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
DAY_FULL = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday'}
COLORS = ['orange', 'blue', 'red', 'purple', 'green']
DIFF_DISPLAY = {1: 'easy', 2: 'medium', 3: 'hard'}


def get_week_dates(week_offset=0):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    monday = monday + timedelta(weeks=week_offset)
    return [monday + timedelta(days=i) for i in range(5)]


def build_time_slots(start_time, max_hours):
    """Build list of hourly time slots starting from study start time"""
    slots = []
    current_hour = start_time.hour
    current_minute = start_time.minute
    for _ in range(int(max_hours)):
        slots.append(f'{str(current_hour).zfill(2)}:{str(current_minute).zfill(2)}')
        current_hour += 1
        if current_hour >= 24:
            break
    return slots


def get_user_preference(user):
    """Get user preference or return defaults"""
    try:
        preference = SleepStudyPreference.objects.get(user=user)
        return {
            'max_focus': preference.max_focus_hours,
            'max_cls': preference.max_focus_hours * 1.5,
            'study_start': preference.active_study_start,
            'preference': preference,
        }
    except SleepStudyPreference.DoesNotExist:
        return {
            'max_focus': 6.0,
            'max_cls': 9.0,
            'study_start': time(9, 0),
            'preference': None,
        }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def schedule_view(request):
    user = request.user
    week_offset = int(request.GET.get('week_offset', 0))
    week_dates = get_week_dates(week_offset)

    # Get user preference once
    pref_data = get_user_preference(user)
    max_cls = pref_data['max_cls']
    max_focus = pref_data['max_focus']
    study_start = pref_data['study_start']

    # Build time slots from user's study start time
    available_times = build_time_slots(study_start, max_focus)

    # Get all sessions for this week
    sessions = StudySession.objects.filter(
        user=user,
        scheduled_date__range=[week_dates[0], week_dates[4]]
    ).select_related('task')

    # Build color map per task
    tasks = Task.objects.filter(user=user)
    task_colors = {}
    for i, task in enumerate(tasks):
        task_colors[task.task_id] = COLORS[i % len(COLORS)]

    slots = []
    daily_load = {}

    for day_date in week_dates:
        day_key = DAY_MAP[day_date.weekday()]
        day_sessions = sessions.filter(scheduled_date=day_date)

        # Calculate daily CLS percentage
        total_cls = sum(s.cls_contribution for s in day_sessions)
        cls_pct = min(round((total_cls / max_cls) * 100), 100) if max_cls > 0 else 0
        daily_load[day_key] = cls_pct

        # Sort sessions by hours descending
        sorted_sessions = sorted(day_sessions, key=lambda s: s.scheduled_hours, reverse=True)

        for i, session in enumerate(sorted_sessions):
            if i >= len(available_times):
                break
            slots.append({
                'day': day_key,
                'time': available_times[i],
                'subject': session.task.title,
                'code': session.task.course_code,
                'duration': max(1, (session.scheduled_hours)),
                'color': task_colors.get(session.task.task_id, 'blue'),
                'session_id': session.session_id,
                'task_id': session.task.task_id,
                'difficulty': DIFF_DISPLAY.get(session.task.difficulty, 'easy'),
                'is_completed': session.is_completed,
            })

    # Build recommendation if any day exceeds 80%
    recommendation = None
    overloaded_days = {k: v for k, v in daily_load.items() if v >= 80}
    if overloaded_days:
        worst_day = max(overloaded_days, key=overloaded_days.get)
        day_names = {
            'mon': 'Monday', 'tue': 'Tuesday', 'wed': 'Wednesday',
            'thu': 'Thursday', 'fri': 'Friday'
        }
        recommendation = {
            'alert': f'{day_names.get(worst_day, worst_day)} exceeds safe cognitive load at {overloaded_days[worst_day]}%.',
            'suggestion': f'Consider moving a task from {day_names.get(worst_day, worst_day)} to a less loaded day.',
            'reduction': round(overloaded_days[worst_day] - 70)
        }

    return Response({
        'slots': slots,
        'daily_load': daily_load,
        'recommendation': recommendation,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_view(request):
    user = request.user
    today = date.today()
    week_dates = get_week_dates()

    # Get user preference once
    pref_data = get_user_preference(user)
    max_focus = pref_data['max_focus']
    max_cls = pref_data['max_cls']

    # Total incomplete tasks
    tasks = Task.objects.filter(user=user, is_completed=False)
    total_tasks = tasks.count()

    # Next deadline
    next_task = tasks.order_by('deadline').first()
    next_deadline = None
    if next_task:
        days_left = (next_task.deadline - today).days
        next_deadline = {
            'course': next_task.course_code,
            'title': next_task.title,
            'days_left': days_left
        }

    # Build color map per task
    all_tasks = Task.objects.filter(user=user)
    task_colors = {}
    for i, task in enumerate(all_tasks):
        task_colors[task.task_id] = COLORS[i % len(COLORS)]

    # Today's sessions
    today_sessions = StudySession.objects.filter(
        user=user,
        scheduled_date=today,
        is_completed=False
    ).select_related('task')

    times = ['09:00 AM', '10:00 AM', '11:00 AM', '12:00 PM', '01:00 PM', '02:00 PM']
    today_tasks = []
    for i, session in enumerate(today_sessions):
        if i >= len(times):
            break
        today_tasks.append({
            'id': session.session_id,
            'title': session.task.title,
            'time': times[i],
            'color': task_colors.get(session.task.task_id, 'blue'),
            'done': session.is_completed,
        })

    used_hours = sum(s.scheduled_hours for s in today_sessions)

    # Stress history for this week
    stress_history = {}
    day_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    for i, day_date in enumerate(week_dates):
        day_sessions = StudySession.objects.filter(
            user=user,
            scheduled_date=day_date
        )
        total_cls = sum(s.cls_contribution for s in day_sessions)
        cls_pct = min(round((total_cls / max_cls) * 100), 100) if max_cls > 0 else 0
        stress_history[day_labels[i]] = cls_pct

    # Current cognitive load
    today_cls = stress_history.get(
        day_labels[today.weekday()] if today.weekday() < 5 else 'Mon', 0
    )
    if today_cls >= 80:
        cog_level = 'high'
    elif today_cls >= 50:
        cog_level = 'moderate'
    else:
        cog_level = 'low'

    # Schedule for dashboard timetable
    sessions_this_week = StudySession.objects.filter(
        user=user,
        scheduled_date__range=[week_dates[0], week_dates[4]]
    ).select_related('task')

    schedule = {}
    for day_date in week_dates:
        day_name = DAY_FULL.get(day_date.weekday())
        if not day_name:
            continue
        day_sessions = sessions_this_week.filter(scheduled_date=day_date)
        available_times = ['09:00', '10:00', '11:00', '12:00', '13:00']
        schedule[day_name] = []
        for i, session in enumerate(day_sessions):
            if i >= len(available_times):
                break
            schedule[day_name].append({
                'time': available_times[i],
                'title': session.task.title,
                'color': task_colors.get(session.task.task_id, 'blue'),
                'difficulty': DIFF_DISPLAY.get(session.task.difficulty, 'easy'),
            })

    # Recommendation
    overloaded = {k: v for k, v in stress_history.items() if v >= 80}
    recommendation = None
    if overloaded:
        worst = max(overloaded, key=overloaded.get)
        recommendation = {
            'alert': f'{worst} exceeds safe cognitive load at {overloaded[worst]}%.',
            'suggestion': f'Consider moving a task from {worst} to a lighter day.',
            'reduction': round(overloaded[worst] - 70)
        }

    return Response({
        'total_tasks': total_tasks,
        'cognitive_load': {
            'value': today_cls,
            'level': cog_level,
        },
        'focus': {
            'used': round(used_hours, 1),
            'max': max_focus,
        },
        'next_deadline': next_deadline,
        'schedule': schedule,
        'stress_history': stress_history,
        'recommendation': recommendation,
        'today_tasks': today_tasks,
    }, status=status.HTTP_200_OK)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def complete_session(request, session_id):
    try:
        session = StudySession.objects.get(session_id=session_id, user=request.user)
    except StudySession.DoesNotExist:
        return Response(
            {'error': 'Session not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    completed = request.data.get('completed', True)
    session.is_completed = completed
    session.save()

    # Check if all sessions for this task are completed
    task = session.task
    all_sessions = StudySession.objects.filter(task=task)
    if all_sessions.filter(is_completed=False).count() == 0:
        task.is_completed = True
        task.save()

    return Response({
        'message': 'Session updated successfully!',
        'is_completed': session.is_completed,
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def regenerate_schedule(request):
    user = request.user

    # Delete all incomplete sessions
    StudySession.objects.filter(user=user, is_completed=False).delete()

    try:
        preference = SleepStudyPreference.objects.get(user=user)
    except SleepStudyPreference.DoesNotExist:
        return Response(
            {'error': 'Please set your sleep preferences first'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Regenerate sorted by deadline then hours
    tasks = Task.objects.filter(
        user=user,
        is_completed=False
    ).order_by('deadline', '-hours')

    total_scheduled = {}
    for task in tasks:
        sessions = generate_study_sessions(task, preference)
        hours_saved = 0
        for session in sessions:
            StudySession.objects.create(
                task=task,
                user=user,
                scheduled_date=session['scheduled_date'],
                scheduled_hours=session['scheduled_hours'],
                cls_contribution=session['cls_contribution'],
            )
            hours_saved += session['scheduled_hours']
        total_scheduled[task.task_id] = round(hours_saved, 2)

    # Auto apply redistribution if overload detected
    from core.schedule_engine import check_and_redistribute, apply_recommendation

    max_attempts = 5
    attempts = 0
    recommendation = check_and_redistribute(user, preference)

    while recommendation and attempts < max_attempts:
        apply_recommendation(
            recommendation['session'],
            recommendation['suggested_date']
        )
        attempts += 1
        recommendation = check_and_redistribute(user, preference)

    final_recommendation = check_and_redistribute(user, preference)

    # Check if schedule is still overloaded after redistribution
    still_overloaded = False
    from datetime import date as date_today
    from datetime import timedelta
    today = date_today.today()
    days_to_check = [
        today + timedelta(days=i)
        for i in range(14)
        if (today + timedelta(days=i)).weekday() < 5
    ]

    from core.schedule_engine import get_daily_cls_percentage
    for day in days_to_check:
        pct = get_daily_cls_percentage(user, day, preference.max_focus_hours)
        if pct >= 80:
            still_overloaded = True
            break

    response_data = {
        'message': 'Schedule regenerated and optimized successfully!',
        'redistributions_applied': attempts,
        'still_overloaded': still_overloaded,
        'warning': 'Your workload is too heavy for the available days. Consider extending deadlines or reducing task hours.' if still_overloaded else None,
    }

    if final_recommendation:
        response_data['recommendation'] = {
            'alert': final_recommendation['alert'],
            'suggestion': final_recommendation['suggestion'],
            'reduction': final_recommendation['reduction'],
            'session_id': final_recommendation['session'].session_id,
            'suggested_date': str(final_recommendation['suggested_date']),
        }

    return Response(response_data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def accept_recommendation(request, session_id):
    user = request.user

    try:
        session = StudySession.objects.get(session_id=session_id, user=user)
    except StudySession.DoesNotExist:
        return Response(
            {'error': 'Session not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    suggested_date = request.data.get('suggested_date')
    if not suggested_date:
        return Response(
            {'error': 'suggested_date is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        new_date = date.fromisoformat(suggested_date)
    except ValueError:
        return Response(
            {'error': 'Invalid date format'},
            status=status.HTTP_400_BAD_REQUEST
        )

    from core.schedule_engine import apply_recommendation, check_and_redistribute
    apply_recommendation(session, new_date)

    pref_data = get_user_preference(user)
    new_recommendation = None
    if pref_data['preference']:
        new_recommendation = check_and_redistribute(user, pref_data['preference'])

    response_data = {
        'message': 'Session rescheduled successfully!',
        'session_id': session_id,
        'new_date': str(new_date),
    }

    if new_recommendation:
        response_data['recommendation'] = {
            'alert': new_recommendation['alert'],
            'suggestion': new_recommendation['suggestion'],
            'reduction': new_recommendation['reduction'],
            'session_id': new_recommendation['session'].session_id,
            'suggested_date': str(new_recommendation['suggested_date']),
        }

    return Response(response_data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def check_missed(request):
    user = request.user

    pref_data = get_user_preference(user)
    if not pref_data['preference']:
        return Response(
            {'error': 'Preferences not set'},
            status=status.HTTP_400_BAD_REQUEST
        )

    from core.schedule_engine import handle_missed_sessions, check_and_redistribute
    rescheduled = handle_missed_sessions(user, pref_data['preference'])
    recommendation = check_and_redistribute(user, pref_data['preference'])

    response_data = {
        'message': f'{rescheduled} missed session(s) rescheduled.',
        'rescheduled_count': rescheduled,
    }

    if recommendation:
        response_data['recommendation'] = {
            'alert': recommendation['alert'],
            'suggestion': recommendation['suggestion'],
            'reduction': recommendation['reduction'],
            'session_id': recommendation['session'].session_id,
            'suggested_date': str(recommendation['suggested_date']),
        }

    return Response(response_data, status=status.HTTP_200_OK)
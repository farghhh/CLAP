from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone

from .models import StudySession
from tasks.models import Task
from sleep.models import SleepStudyPreference

from datetime import timedelta, time

from core.schedule_engine import (
    generate_study_sessions,
    calculate_progress,
    check_and_redistribute,
    apply_recommendation,
    get_available_days,
    get_daily_cls_percentage,
)

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────
DAY_MAP  = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
DAY_FULL = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday'}
COLORS   = ['orange', 'blue', 'red', 'purple', 'green']
DIFF_DISPLAY = {1: 'easy', 2: 'medium', 3: 'hard'}


# ─────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────

def get_week_dates(week_offset=0):
    """Returns list of 5 weekday dates for a given week offset"""
    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    monday = monday + timedelta(weeks=week_offset)
    return [monday + timedelta(days=i) for i in range(5)]


def build_time_slots(start_time, max_hours):
    """Build list of hourly time slots starting from study start time"""
    slots = []
    current_hour = start_time.hour
    current_minute = start_time.minute

    for _ in range(int(max_hours)):
        slots.append(
            f'{str(current_hour).zfill(2)}:{str(current_minute).zfill(2)}'
        )
        current_hour += 1
        if current_hour >= 24:
            break

    return slots


def chain_session_times(sessions, start_time):
    """
    Assign start/end times to sessions by chaining them consecutively.
    Each session starts where the previous one ended, based on scheduled_hours.
    """
    result = []
    cur_mins = start_time.hour * 60 + start_time.minute

    for session in sessions:
        dur_mins = round(float(session.scheduled_hours) * 60)
        end_mins = cur_mins + dur_mins

        start_h, start_m = divmod(cur_mins, 60)
        end_h,   end_m   = divmod(end_mins, 60)

        start_str = f'{str(start_h).zfill(2)}:{str(start_m).zfill(2)}'
        end_str   = f'{str(end_h).zfill(2)}:{str(end_m).zfill(2)}'

        result.append((session, start_str, end_str))
        cur_mins = end_mins

    return result


def get_user_preference(user):
    """Get user preference or return safe defaults"""
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


def build_recommendation_response(recommendation):
    """Helper to format recommendation dict for API response"""
    if not recommendation:
        return None
    return {
        'alert': recommendation['alert'],
        'suggestion': recommendation['suggestion'],
        'reduction': recommendation['reduction'],
        'session_id': recommendation['session'].session_id,
        'suggested_date': str(recommendation['suggested_date']),
    }


# ─────────────────────────────────────────────────────────────
# SCHEDULE VIEW
# ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def schedule_view(request):
    user = request.user
    week_offset = int(request.GET.get('week_offset', 0))
    week_dates = get_week_dates(week_offset)

    pref_data = get_user_preference(user)
    max_cls = pref_data['max_cls']
    max_focus = pref_data['max_focus']
    study_start = pref_data['study_start']

    sessions = StudySession.objects.filter(
        user=user,
        scheduled_date__range=[week_dates[0], week_dates[4]]
    ).select_related('task')

    all_tasks = Task.objects.filter(user=user)
    task_colors = {}
    for i, task in enumerate(all_tasks):
        task_colors[task.task_id] = COLORS[i % len(COLORS)]

    slots = []
    daily_load = {}

    for day_date in week_dates:
        day_key = DAY_MAP[day_date.weekday()]
        day_sessions = sessions.filter(scheduled_date=day_date)

        total_cls = sum(s.cls_contribution for s in day_sessions)
        cls_pct = min(round((total_cls / max_cls) * 100), 100) if max_cls > 0 else 0
        daily_load[day_key] = cls_pct

        sorted_sessions = sorted(
            day_sessions,
            key=lambda s: (s.task.deadline, s.task.task_id)
        )

        timed = chain_session_times(sorted_sessions, study_start)

        for session, start_str, end_str in timed:
            slots.append({
                'day':          day_key,
                'time':         start_str,
                'end':          end_str,
                'subject':      session.task.title,
                'code':         session.task.course_code,
                'duration':     session.scheduled_hours,
                'color':        task_colors.get(session.task.task_id, 'blue'),
                'session_id':   session.session_id,
                'task_id':      session.task.task_id,
                'difficulty':   DIFF_DISPLAY.get(session.task.difficulty, 'easy'),
                'is_completed': session.is_completed,
            })

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
            'reduction': round(overloaded_days[worst_day] - 70),
        }

    return Response({
        'slots': slots,
        'daily_load': daily_load,
        'recommendation': recommendation,
    }, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────
# DASHBOARD VIEW
# ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_view(request):
    user = request.user
    today = timezone.localdate()
    week_dates = get_week_dates()

    pref_data = get_user_preference(user)
    max_focus = pref_data['max_focus']
    max_cls = pref_data['max_cls']
    study_start = pref_data['study_start']

    tasks = Task.objects.filter(user=user, is_completed=False)
    total_tasks = tasks.count()

    next_task = tasks.order_by('deadline').first()
    next_deadline = None
    if next_task:
        client_date_str = request.GET.get('local_date')
        try:
            from datetime import date as _date
            client_today = _date.fromisoformat(client_date_str)
        except (TypeError, ValueError):
            client_today = today

        days_left = (next_task.deadline - client_today).days
        next_deadline = {
            'course': next_task.course_code,
            'title': next_task.title,
            'days_left': days_left,
        }

    all_tasks = Task.objects.filter(user=user)
    task_colors = {}
    for i, task in enumerate(all_tasks):
        task_colors[task.task_id] = COLORS[i % len(COLORS)]

    today_sessions = StudySession.objects.filter(
        user=user,
        scheduled_date=today,
    ).select_related('task')

    sorted_today = sorted(today_sessions, key=lambda s: (s.task.deadline, s.task.task_id))
    timed_today = chain_session_times(sorted_today, study_start)

    today_tasks = []
    for session, start_str, end_str in timed_today:
        today_tasks.append({
            'id':           session.session_id,
            'session_id':   session.session_id,
            'title':        session.task.title,
            'start':        start_str,
            'end':          end_str,
            'color':        task_colors.get(session.task.task_id, 'blue'),
            'difficulty':   DIFF_DISPLAY.get(session.task.difficulty, 'easy'),
            'done':         session.is_completed,
        })

    used_hours = round(
        sum(s.scheduled_hours for s in today_sessions if s.is_completed), 1
    )

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

    if today.weekday() < 5:
        today_cls = stress_history.get(day_labels[today.weekday()], 0)
    else:
        today_cls = 0

    if today_cls >= 80:
        cog_level = 'high'
    elif today_cls >= 50:
        cog_level = 'moderate'
    else:
        cog_level = 'low'

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

        sorted_day = sorted(day_sessions, key=lambda s: (s.task.deadline, s.task.task_id))
        timed_day = chain_session_times(sorted_day, study_start)

        schedule[day_name] = []
        for session, start_str, end_str in timed_day:
            schedule[day_name].append({
                'time':       start_str,
                'end':        end_str,
                'title':      session.task.title,
                'color':      task_colors.get(session.task.task_id, 'blue'),
                'difficulty': DIFF_DISPLAY.get(session.task.difficulty, 'easy'),
                'duration':   session.scheduled_hours,
                'session_id': session.session_id,
                'task_id':    session.task.task_id,
            })

    overloaded = {k: v for k, v in stress_history.items() if v >= 80}
    recommendation = None
    if overloaded:
        worst = max(overloaded, key=overloaded.get)
        recommendation = {
            'alert': f'{worst} exceeds safe cognitive load at {overloaded[worst]}%.',
            'suggestion': f'Consider moving a task from {worst} to a lighter day.',
            'reduction': round(overloaded[worst] - 70),
        }

    return Response({
        'total_tasks': total_tasks,
        'cognitive_load': {
            'value': today_cls,
            'level': cog_level,
        },
        'focus': {
            'used': used_hours,
            'max': max_focus,
        },
        'next_deadline': next_deadline,
        'schedule': schedule,
        'stress_history': stress_history,
        'recommendation': recommendation,
        'today_tasks': today_tasks,
    }, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────
# COMPLETE SESSION
# ─────────────────────────────────────────────────────────────

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def complete_session(request, session_id):
    try:
        session = StudySession.objects.get(
            session_id=session_id,
            user=request.user
        )
    except StudySession.DoesNotExist:
        return Response(
            {'error': 'Session not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    completed = request.data.get('completed', True)
    session.is_completed = completed
    session.save()

    task = session.task
    all_sessions = StudySession.objects.filter(task=task)
    all_done = all_sessions.filter(is_completed=False).count() == 0
    if task.is_completed != all_done:
        task.is_completed = all_done
        task.save()

    return Response({
        'message': 'Session updated successfully!',
        'is_completed': session.is_completed,
    }, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────
# REGENERATE SCHEDULE
# ─────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def regenerate_schedule(request):
    user = request.user
    today = timezone.localdate()

    StudySession.objects.filter(user=user, is_completed=False).delete()

    try:
        preference = SleepStudyPreference.objects.get(user=user)
    except SleepStudyPreference.DoesNotExist:
        return Response(
            {'error': 'Please set your sleep preferences first'},
            status=status.HTTP_400_BAD_REQUEST
        )

    tasks = Task.objects.filter(
        user=user,
        is_completed=False
    ).order_by('deadline', '-hours')

    for task in tasks:
        sessions = generate_study_sessions(task, preference)
        for session in sessions:
            StudySession.objects.create(
                task=task,
                user=user,
                scheduled_date=session['scheduled_date'],
                scheduled_hours=session['scheduled_hours'],
                cls_contribution=session['cls_contribution'],
            )

    attempts = 0
    max_attempts = 5
    recommendation = check_and_redistribute(user, preference)

    while recommendation and attempts < max_attempts:
        apply_recommendation(
            recommendation['session'],
            recommendation['suggested_date']
        )
        attempts += 1
        recommendation = check_and_redistribute(user, preference)

    still_overloaded = False
    days_to_check = [
        today + timedelta(days=i)
        for i in range(14)
        if (today + timedelta(days=i)).weekday() < 5
    ]

    for day in days_to_check:
        if get_daily_cls_percentage(user, day, preference.max_focus_hours) >= 80:
            still_overloaded = True
            break

    all_tasks = Task.objects.filter(user=user, is_completed=False)
    total_task_hours = round(sum(float(t.hours) for t in all_tasks), 1)
    nearest_task = all_tasks.order_by('deadline').first()

    if nearest_task:
        avail_days = get_available_days(today, nearest_task.deadline)
        max_possible_hours = round(len(avail_days) * preference.max_focus_hours, 1)
    else:
        max_possible_hours = 0

    hours_over = round(total_task_hours - max_possible_hours, 1)

    if still_overloaded:
        if hours_over > 0:
            warning_msg = (
                f'Your total workload ({total_task_hours}hrs) exceeds '
                f'available capacity ({max_possible_hours}hrs) by {hours_over}hrs. '
                f'Consider extending deadlines or increasing daily study hours in Settings.'
            )
        else:
            warning_msg = (
                'Some days are still overloaded. '
                'Consider extending task deadlines to spread work more evenly.'
            )
    else:
        warning_msg = None

    final_recommendation = check_and_redistribute(user, preference)

    response_data = {
        'message': 'Schedule regenerated and optimized successfully!',
        'redistributions_applied': attempts,
        'still_overloaded': still_overloaded,
        'warning': warning_msg,
    }

    if final_recommendation:
        response_data['recommendation'] = build_recommendation_response(
            final_recommendation
        )

    return Response(response_data, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────
# ACCEPT RECOMMENDATION
# ─────────────────────────────────────────────────────────────

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
        new_date = timezone.datetime.fromisoformat(suggested_date).date()
    except ValueError:
        return Response(
            {'error': 'Invalid date format'},
            status=status.HTTP_400_BAD_REQUEST
        )

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
        response_data['recommendation'] = build_recommendation_response(
            new_recommendation
        )

    return Response(response_data, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────
# CHECK MISSED SESSIONS
# ─────────────────────────────────────────────────────────────

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

    from core.schedule_engine import handle_missed_sessions

    preference = pref_data['preference']

    missed_result = handle_missed_sessions(user, preference)

    recommendation = check_and_redistribute(user, preference)

    # BUG FIX: response_data dict had a broken string literal key:
    #   'missed_count": missed_result.get(...)   ← mixed quote types = SyntaxError
    # This caused Django to fail to even load the view module, making every
    # request to this endpoint return a 500 (which Railway's proxy surfaced as
    # a timeout / no-response to the frontend).
    response_data = {
        'message': f"{missed_result['count']} missed session(s) rescheduled.",
        'rescheduled_count': missed_result['count'],
        'missed_count': missed_result.get('missed_count', missed_result['count']),
    }

    if missed_result['items']:
        response_data.update(missed_result['items'][0])

    response_data['missed_items'] = missed_result['items']

    if recommendation:
        response_data['recommendation'] = build_recommendation_response(
            recommendation
        )

    return Response(response_data, status=status.HTTP_200_OK)

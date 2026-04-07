from datetime import timedelta
from django.utils import timezone
from .cls_engine import calculate_cls, get_risk_level


# ─────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────

def get_available_days(start_date, deadline):
    """Returns list of available weekdays between start_date and deadline"""
    days = []
    current = start_date
    while current <= deadline:
        if current.weekday() < 5:  # Monday=0 to Friday=4 only
            days.append(current)
        current += timedelta(days=1)
    return days


def get_daily_cls_percentage(user, day, max_focus):
    """Returns CLS percentage for a specific day (0-100)"""
    from schedule.models import StudySession
    day_sessions = StudySession.objects.filter(
        user=user,
        scheduled_date=day,
        is_completed=False
    )
    total_cls = sum(s.cls_contribution for s in day_sessions)
    max_cls = max_focus * 1.5
    if max_cls <= 0:
        return 0
    return min(round((total_cls / max_cls) * 100), 100)


def get_other_tasks_hours(user, task, day):
    """
    Returns total hours scheduled on a day from OTHER tasks only.
    Excludes the current task and completed sessions.
    This is the key function that prevents double-counting.
    """
    from schedule.models import StudySession
    other_sessions = StudySession.objects.filter(
        user=user,
        scheduled_date=day,
        is_completed=False
    ).exclude(task=task)
    return round(sum(s.scheduled_hours for s in other_sessions), 2)


def get_daily_hours_used(user, day, max_focus):
    """Returns total hours already scheduled for a day (all tasks)"""
    from schedule.models import StudySession
    existing = StudySession.objects.filter(
        user=user,
        scheduled_date=day,
        is_completed=False
    )
    return round(sum(s.scheduled_hours for s in existing), 2)


# ─────────────────────────────────────────────────────────────
# CORE SESSION GENERATION
# ─────────────────────────────────────────────────────────────

def generate_study_sessions(task, preference):
    """
    Generates study sessions guaranteeing total_hours are always scheduled.
    """
    import math
    from schedule.models import StudySession

    today = timezone.localdate()
    deadline = task.deadline
    total_hours = round(float(task.hours), 2)
    max_focus = round(float(preference.max_focus_hours), 2)

    diff_map = {1: 'easy', 2: 'medium', 3: 'hard'}
    difficulty_str = diff_map.get(task.difficulty, 'medium')

    available_days = get_available_days(today, deadline)
    if not available_days:
        return []

    num_available = len(available_days)
    days_until_deadline = (deadline - today).days

    # ── Step 1: Calculate available hours per day for THIS task ──
    # Build a map of how many hours each day has available
    # for this specific task (max_focus minus other tasks)
    day_availability = {}
    for day in available_days:
        other_hours = get_other_tasks_hours(
            user=task.user, task=task, day=day
        )
        available = round(max_focus - other_hours, 2)
        if available > 0:
            day_availability[day] = available

    if not day_availability:
        return []

    # Total capacity across all days
    total_capacity = round(sum(day_availability.values()), 2)

    # ── Step 2: Minimum days needed ──────────────────────────
    min_days_needed = math.ceil(total_hours / max_focus)
    min_days_needed = max(1, min(min_days_needed, len(day_availability)))

    # ── Step 3: Target days based on urgency ─────────────────
    if days_until_deadline > 14:
        target_days = min(len(day_availability), min_days_needed * 3)
    elif days_until_deadline > 7:
        target_days = min(len(day_availability), min_days_needed * 2)
    else:
        target_days = min(len(day_availability), min_days_needed)

    target_days = max(1, target_days)

    # ── Step 4: Hours per session ─────────────────────────────
    raw_hours = total_hours / target_days
    hours_per_session = math.ceil(raw_hours * 2) / 2
    hours_per_session = min(hours_per_session, max_focus)
    hours_per_session = max(hours_per_session, 0.5)

    target_days = math.ceil(total_hours / hours_per_session)
    target_days = min(target_days, len(day_availability))

    # ── Step 5: Pick start day based on urgency ───────────────
    all_available = list(day_availability.keys())

    if days_until_deadline > 14:
        start_index = len(all_available) // 3
    elif days_until_deadline > 7:
        start_index = len(all_available) // 5
    else:
        start_index = 0

    usable_days = all_available[start_index:] or all_available

    # Space sessions evenly
    if target_days >= len(usable_days):
        selected_days = list(usable_days)
    else:
        step = len(usable_days) / target_days
        selected_days = [
            usable_days[min(math.floor(i * step), len(usable_days) - 1)]
            for i in range(target_days)
        ]

    # Remove duplicates
    seen = set()
    unique_days = []
    for d in selected_days:
        if d not in seen:
            seen.add(d)
            unique_days.append(d)
    selected_days = unique_days
    num_selected = len(selected_days)

    # ── Step 6: Assign hours ──────────────────────────────────
    sessions = []
    remaining_hours = total_hours

    for i, day in enumerate(selected_days):
        if remaining_hours <= 0:
            break

        available_hours = day_availability.get(day, 0)
        if available_hours < 0.5:
            continue

        if i == num_selected - 1:
            hours_today = min(remaining_hours, available_hours)
        else:
            hours_today = min(hours_per_session, available_hours, remaining_hours)

        hours_today = round(hours_today, 2)
        if hours_today < 0.5:
            continue

        cls_contribution = round(
            (hours_today / total_hours) * calculate_cls(
                difficulty_str, task.hours, task.deadline
            ), 2
        )

        sessions.append({
            'scheduled_date': day,
            'scheduled_hours': hours_today,
            'cls_contribution': cls_contribution,
        })

        # Reduce this day's availability
        day_availability[day] = round(day_availability[day] - hours_today, 2)
        remaining_hours = round(remaining_hours - hours_today, 2)

    # ── Step 7: Safety net ────────────────────────────────────
    # Try ALL days with any remaining capacity
    if remaining_hours >= 0.5:
        # Sort days by most available hours first
        sorted_days = sorted(
            all_available,
            key=lambda d: day_availability.get(d, 0),
            reverse=True
        )

        for day in sorted_days:
            if remaining_hours <= 0:
                break

            available_hours = day_availability.get(day, 0)
            if available_hours < 0.5:
                continue

            hours_today = round(min(remaining_hours, available_hours), 2)
            if hours_today < 0.5:
                continue

            existing = next(
                (s for s in sessions if s['scheduled_date'] == day), None
            )

            if existing:
                existing['scheduled_hours'] = round(
                    existing['scheduled_hours'] + hours_today, 2
                )
                existing['cls_contribution'] = round(
                    (existing['scheduled_hours'] / total_hours) * calculate_cls(
                        difficulty_str, task.hours, task.deadline
                    ), 2
                )
            else:
                sessions.append({
                    'scheduled_date': day,
                    'scheduled_hours': hours_today,
                    'cls_contribution': round(
                        (hours_today / total_hours) * calculate_cls(
                            difficulty_str, task.hours, task.deadline
                        ), 2
                    ),
                })

            day_availability[day] = round(day_availability[day] - hours_today, 2)
            remaining_hours = round(remaining_hours - hours_today, 2)

    # ── Step 8: Last resort ───────────────────────────────────
    # If still remaining hours, add to session with most hours
    # This guarantees total_hours is always fully scheduled
    if remaining_hours >= 0.5 and sessions:
        # Find session with most available capacity on its day
        best_session = max(sessions, key=lambda s: s['scheduled_hours'])
        best_session['scheduled_hours'] = round(
            best_session['scheduled_hours'] + remaining_hours, 2
        )
        best_session['cls_contribution'] = round(
            (best_session['scheduled_hours'] / total_hours) * calculate_cls(
                difficulty_str, task.hours, task.deadline
            ), 2
        )
        remaining_hours = 0

    return sessions


# ─────────────────────────────────────────────────────────────
# AUTO RESCHEDULING ENGINE
# ─────────────────────────────────────────────────────────────

def check_and_redistribute(user, preference):
    """
    Scans next 14 weekdays for overloaded days (CLS > 80%).
    Finds the most moveable session and suggests moving it
    to the lightest available day.
    Returns recommendation dict or None.
    """
    from schedule.models import StudySession

    max_focus = preference.max_focus_hours
    today = timezone.localdate()

    # Check next 14 weekdays
    days_to_check = [
        today + timedelta(days=i)
        for i in range(14)
        if (today + timedelta(days=i)).weekday() < 5
    ]

    # Find the most overloaded day
    overloaded_day = None
    overloaded_pct = 0

    for day in days_to_check:
        pct = get_daily_cls_percentage(user, day, max_focus)
        if pct >= 80 and pct > overloaded_pct:
            overloaded_day = day
            overloaded_pct = pct

    if not overloaded_day:
        return None

    # Find sessions on overloaded day sorted by lowest CLS first
    overloaded_sessions = StudySession.objects.filter(
        user=user,
        scheduled_date=overloaded_day,
        is_completed=False
    ).select_related('task').order_by('cls_contribution')

    if not overloaded_sessions.exists():
        return None

    # Find most moveable session
    # (lowest CLS contribution + has more than 1 day until deadline)
    moveable_session = None
    for session in overloaded_sessions:
        days_until_deadline = (session.task.deadline - today).days
        if days_until_deadline > 1:
            moveable_session = session
            break

    if not moveable_session:
        return None

    # Find the best day to move it to
    best_day = None
    best_pct = 100

    for day in days_to_check:
        if day == overloaded_day:
            continue
        if day >= moveable_session.task.deadline:
            continue

        pct = get_daily_cls_percentage(user, day, max_focus)
        hours_used = get_daily_hours_used(user, day, max_focus)
        available = max_focus - hours_used

        if pct < best_pct and available >= moveable_session.scheduled_hours:
            best_pct = pct
            best_day = day

    if not best_day:
        return None

    # Calculate stress reduction
    new_overloaded_pct = overloaded_pct - round(
        (moveable_session.cls_contribution / (max_focus * 1.5)) * 100
    )
    stress_reduction = max(0, overloaded_pct - new_overloaded_pct)

    return {
        'session': moveable_session,
        'overloaded_date': overloaded_day,
        'suggested_date': best_day,
        'stress_reduction': round(stress_reduction),
        'alert': f'{overloaded_day.strftime("%A")} is overloaded at {overloaded_pct}%!',
        'suggestion': f'Move "{moveable_session.task.title}" from {overloaded_day.strftime("%A")} to {best_day.strftime("%A")}.',
        'reduction': round(stress_reduction),
    }


def apply_recommendation(session, new_date):
    """
    Moves a session to a new date when user accepts recommendation.
    """
    session.scheduled_date = new_date
    session.save()


# ─────────────────────────────────────────────────────────────
# PROCRASTINATION DETECTION
# ─────────────────────────────────────────────────────────────

def handle_missed_sessions(user, preference):
    """
    Situation 3 — Procrastination Detection.
    Checks yesterday's incomplete sessions.
    Marks them missed and reschedules to next available day.

    Returns:
        {
            'count': int,
            'items': [
                {
                    'task_title': str,
                    'task_day': str,
                    'task_start': str,
                    'task_end': str,
                    'reschedule_day': str,
                    'reschedule_start': str,
                    'reschedule_end': str,
                },
                ...
            ]
        }
    """
    from schedule.models import StudySession

    yesterday = timezone.localdate() - timedelta(days=1)
    today = timezone.localdate()
    study_start = preference.active_study_start
    max_focus = preference.max_focus_hours

    missed_qs = StudySession.objects.filter(
        user=user,
        scheduled_date=yesterday,
        is_completed=False,
        is_missed=False
    ).select_related('task').order_by('task__deadline', 'task__task_id')

    if not missed_qs.exists():
        return {
            'count': 0,
            'items': []
        }

    missed_sessions = list(missed_qs)
    missed_timed = []
    cur_mins_yesterday = study_start.hour * 60 + study_start.minute

    # Build original yesterday times before moving anything
    for session in missed_sessions:
        dur_mins = round(float(session.scheduled_hours) * 60)
        end_mins = cur_mins_yesterday + dur_mins

        start_h, start_m = divmod(cur_mins_yesterday, 60)
        end_h, end_m = divmod(end_mins, 60)

        missed_timed.append({
            'session': session,
            'task_title': session.task.title,
            'task_day': yesterday.strftime('%A'),
            'task_start': f'{str(start_h).zfill(2)}:{str(start_m).zfill(2)}',
            'task_end': f'{str(end_h).zfill(2)}:{str(end_m).zfill(2)}',
        })

        cur_mins_yesterday = end_mins

    rescheduled_items = []

    for item in missed_timed:
        session = item['session']

        # Mark as missed first
        session.is_missed = True
        session.save()

        deadline = session.task.deadline
        next_day = today
        moved = False

        while next_day < deadline:
            # Skip weekends
            if next_day.weekday() >= 5:
                next_day += timedelta(days=1)
                continue

            hours_used = get_daily_hours_used(user, next_day, max_focus)
            available = max_focus - hours_used

            if available >= session.scheduled_hours:
                session.scheduled_date = next_day
                session.is_missed = False
                session.save()

                # Rebuild times for the rescheduled day after move
                day_sessions = StudySession.objects.filter(
                    user=user,
                    scheduled_date=next_day
                ).select_related('task').order_by('task__deadline', 'task__task_id')

                cur_mins_day = study_start.hour * 60 + study_start.minute
                new_start = ''
                new_end = ''

                for s in day_sessions:
                    dur_mins = round(float(s.scheduled_hours) * 60)
                    end_mins = cur_mins_day + dur_mins

                    start_h, start_m = divmod(cur_mins_day, 60)
                    end_h, end_m = divmod(end_mins, 60)

                    if s.session_id == session.session_id:
                        new_start = f'{str(start_h).zfill(2)}:{str(start_m).zfill(2)}'
                        new_end = f'{str(end_h).zfill(2)}:{str(end_m).zfill(2)}'
                        break

                    cur_mins_day = end_mins

                rescheduled_items.append({
                    'task_title': item['task_title'],
                    'task_day': item['task_day'],
                    'task_start': item['task_start'],
                    'task_end': item['task_end'],
                    'reschedule_day': next_day.strftime('%A'),
                    'reschedule_start': new_start,
                    'reschedule_end': new_end,
                })

                moved = True
                break

            next_day += timedelta(days=1)

        # If not moved, keep is_missed=True so it is still flagged in the system
        if not moved:
            session.save()

    return {
        'count': len(rescheduled_items),
        'items': rescheduled_items
    }

# ─────────────────────────────────────────────────────────────
# PROGRESS TRACKER
# ─────────────────────────────────────────────────────────────

def calculate_progress(task):
    """
    Returns progress percentage for a task
    based on completed study hours vs total scheduled hours.
    This is more accurate than counting sessions because
    sessions may have different durations.
    """
    from schedule.models import StudySession

    sessions = StudySession.objects.filter(task=task)
    if not sessions.exists():
        return 0

    total_hours = round(sum(s.scheduled_hours for s in sessions), 2)
    if total_hours <= 0:
        return 0

    completed_hours = round(
        sum(s.scheduled_hours for s in sessions if s.is_completed),
        2
    )

    return round((completed_hours / total_hours) * 100)

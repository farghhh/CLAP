from datetime import date, timedelta
from .cls_engine import calculate_cls, get_risk_level

# HELPER FUNCTIONS

def get_available_days(start_date, deadline):
    """Returns list of available weekdays between start_date and deadline"""
    days = []
    current = start_date
    while current < deadline:
        if current.weekday() < 5:  # Monday=0 to Friday=4 only
            days.append(current)
        current += timedelta(days=1)
    return days


def get_daily_cls_percentage(user, day, max_focus):
    """Returns CLS percentage for a specific day"""
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


def get_daily_hours_used(user, day, max_focus):
    """Returns total hours already scheduled for a day"""
    from schedule.models import StudySession
    existing = StudySession.objects.filter(
        user=user,
        scheduled_date=day
    )
    return sum(s.scheduled_hours for s in existing)


# CORE SESSION GENERATION
def generate_study_sessions(task, preference):
    import math
    from schedule.models import StudySession

    today = date.today()
    deadline = task.deadline
    total_hours = float(task.hours)
    max_focus = float(preference.max_focus_hours)

    diff_map = {1: 'easy', 2: 'medium', 3: 'hard'}
    difficulty_str = diff_map.get(task.difficulty, 'medium')

    available_days = get_available_days(today, deadline)
    if not available_days:
        return []

    num_available = len(available_days)
    days_until_deadline = (deadline - today).days

    # ── Step 1: Minimum days needed ───────────────────────────
    min_days_needed = math.ceil(total_hours / max_focus)

    # ── Step 2: Target days based on urgency ──────────────────
    if days_until_deadline > 14:
        target_days = min(num_available, min_days_needed * 3)
    elif days_until_deadline > 7:
        target_days = min(num_available, min_days_needed * 2)
    else:
        target_days = min(num_available, min_days_needed)

    target_days = max(1, target_days)

    # ── Step 3: Hours per session ─────────────────────────────
    hours_per_session = total_hours / target_days
    hours_per_session = math.ceil(hours_per_session * 2) / 2  # round up to 0.5
    hours_per_session = min(hours_per_session, max_focus)

    # Recalculate target_days after rounding
    target_days = math.ceil(total_hours / hours_per_session)
    target_days = min(target_days, num_available)

    # ── Step 4: Pick start day based on urgency ───────────────
    if days_until_deadline > 14:
        start_index = num_available // 3
    elif days_until_deadline > 7:
        start_index = num_available // 5
    else:
        start_index = 0

    usable_days = available_days[start_index:] or available_days

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

    # ── Step 5: Assign hours ──────────────────────────────────
    sessions = []
    remaining_hours = round(total_hours, 2)

    for i, day in enumerate(selected_days):
        if remaining_hours <= 0:
            break

        # Only count OTHER tasks' sessions (not this task)
        other_sessions = StudySession.objects.filter(
            user=task.user,
            scheduled_date=day
            is_completed=False
        ).exclude(task=task)
        other_hours = sum(s.scheduled_hours for s in other_sessions)
        available_hours = round(max_focus - other_hours, 2)

        if available_hours <= 0:
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

        remaining_hours = round(remaining_hours - hours_today, 2)

   # ── Step 6: Safety net ────────────────────────────────────
    if remaining_hours >= 0.5:
        # Try ALL available days including ones not in selected_days
        for day in available_days:
            if remaining_hours <= 0:
                break

            # Only count incomplete sessions from OTHER tasks
            other_sessions = StudySession.objects.filter(
                user=task.user,
                scheduled_date=day,
                is_completed=False
            ).exclude(task=task)
            other_hours = sum(s.scheduled_hours for s in other_sessions)

            # Also count what we already scheduled for this task today
            already_this_task = sum(
                s['scheduled_hours'] for s in sessions
                if s['scheduled_date'] == day
            )

            available_hours = round(max_focus - other_hours - already_this_task, 2)

            if available_hours < 0.5:
                continue

            hours_today = round(min(remaining_hours, available_hours), 2)

            if hours_today < 0.5:
                continue

            # Check if session already exists for this day
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

            remaining_hours = round(remaining_hours - hours_today, 2)

    return sessions


# AUTO RESCHEDULING ENGINE

def check_and_redistribute(user, preference):
    """
    Checks all days for overload (>80% CLS).
    If overloaded, finds the most moveable session
    and moves it to the lightest available day.
    Returns a recommendation dict if overload found, else None.
    """
    from schedule.models import StudySession
    from tasks.models import Task

    max_focus = preference.max_focus_hours
    today = date.today()

    # Check next 14 days for overload
    days_to_check = [today + timedelta(days=i) for i in range(14)
                     if (today + timedelta(days=i)).weekday() < 5]

    overloaded_day = None
    overloaded_pct = 0

    for day in days_to_check:
        pct = get_daily_cls_percentage(user, day, max_focus)
        if pct >= 80 and pct > overloaded_pct:
            overloaded_day = day
            overloaded_pct = pct

    if not overloaded_day:
        return None  # No overload found

    # Find sessions on overloaded day
    overloaded_sessions = StudySession.objects.filter(
        user=user,
        scheduled_date=overloaded_day,
        is_completed=False
    ).select_related('task').order_by('cls_contribution')

    if not overloaded_sessions.exists():
        return None

    # Find most moveable session (lowest CLS, furthest deadline)
    moveable_session = None
    for session in overloaded_sessions:
        days_until_deadline = (session.task.deadline - today).days
        if days_until_deadline > 1:  # Has time to move
            moveable_session = session
            break

    if not moveable_session:
        return None

    # Find the lightest available day to move to
    best_day = None
    best_pct = 100

    for day in days_to_check:
        if day == overloaded_day:
            continue
        if day >= moveable_session.task.deadline:
            continue  # Can't move past deadline

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
    stress_reduction = overloaded_pct - new_overloaded_pct

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
    Moves a session to a new date.
    Called when user accepts a recommendation.
    """
    session.scheduled_date = new_date
    session.save()


# PROCRASTINATION DETECTION

def handle_missed_sessions(user, preference):
    """
    Situation 3 — Procrastination Detection.
    Checks yesterday's sessions that were not completed.
    Marks them as missed and reschedules to next available day.
    Returns number of sessions rescheduled.
    """
    from schedule.models import StudySession

    yesterday = date.today() - timedelta(days=1)
    max_focus = preference.max_focus_hours

    # Find missed sessions from yesterday
    missed = StudySession.objects.filter(
        user=user,
        scheduled_date=yesterday,
        is_completed=False,
        is_missed=False
    )

    if not missed.exists():
        return 0

    rescheduled_count = 0

    for session in missed:
        # Mark as missed
        session.is_missed = True
        session.save()

        # Find next available day
        next_day = date.today()
        deadline = session.task.deadline

        while next_day < deadline:
            if next_day.weekday() >= 5:  # Skip weekends
                next_day += timedelta(days=1)
                continue

            hours_used = get_daily_hours_used(user, next_day, max_focus)
            available = max_focus - hours_used

            if available >= session.scheduled_hours:
                # Reschedule to this day
                session.scheduled_date = next_day
                session.is_missed = False
                session.save()
                rescheduled_count += 1
                break

            next_day += timedelta(days=1)

    return rescheduled_count


# PROGRESS TRACKER

def calculate_progress(task):
    """
    Returns progress percentage for a task
    based on completed study sessions
    """
    from schedule.models import StudySession

    total_sessions = StudySession.objects.filter(task=task)
    if not total_sessions.exists():
        return 0

    completed = total_sessions.filter(is_completed=True).count()
    total = total_sessions.count()

    return round((completed / total) * 100)
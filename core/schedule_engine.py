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

    # ── Step 1: How many hours per day do we NEED? ────────────
    required_per_day = total_hours / num_available

    # ── Step 2: Determine actual hours per session ─────────────
    if required_per_day >= max_focus:
        # Tight deadline — must use max focus every day
        hours_per_session = max_focus

    elif required_per_day < 1.0:
        # Far deadline — don't schedule tiny sessions
        # Use comfortable session size and fewer days
        if task.difficulty == 3:    # hard
            hours_per_session = 1.5
        else:                        # easy/medium
            hours_per_session = 2.0
        hours_per_session = min(hours_per_session, max_focus, total_hours)

    else:
        # Normal case — use required amount but round up to nearest 0.5
        hours_per_session = math.ceil(required_per_day * 2) / 2
        hours_per_session = min(hours_per_session, max_focus)

    # ── Step 3: How many sessions do we need? ─────────────────
    num_sessions = math.ceil(total_hours / hours_per_session)
    num_sessions = min(num_sessions, num_available)

    # After capping, recalculate to make sure hours_per_session
    # is enough to cover all hours
    hours_per_session = min(
        math.ceil((total_hours / num_sessions) * 2) / 2,
        max_focus
    )

    # ── Step 4: Pick which days based on urgency ──────────────
    if days_until_deadline > 14:
        start_index = num_available // 3
    elif days_until_deadline > 7:
        start_index = num_available // 5
    else:
        start_index = 0

    usable_days = available_days[start_index:]
    if not usable_days:
        usable_days = available_days

    # Space sessions evenly across usable days
    if num_sessions >= len(usable_days):
        selected_days = usable_days[:num_sessions]
    else:
        step = len(usable_days) / num_sessions
        selected_days = [
            usable_days[min(math.floor(i * step), len(usable_days) - 1)]
            for i in range(num_sessions)
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

    # ── Step 5: Assign hours ensuring total = task.hours ──────
    sessions = []
    remaining_hours = total_hours

    for i, day in enumerate(selected_days):
        if remaining_hours <= 0:
            break

        existing_hours = get_daily_hours_used(task.user, day, max_focus)
        available_hours = max_focus - existing_hours

        if available_hours <= 0:
            # This day is full — try to find next available day
            continue

        # Last session gets ALL remaining hours
        if i == num_selected - 1:
            hours_today = min(remaining_hours, available_hours)
        else:
            hours_today = min(hours_per_session, available_hours, remaining_hours)

        if hours_today < 0.5:
            continue

        cls_contribution = round(
            (hours_today / total_hours) * calculate_cls(
                difficulty_str,
                task.hours,
                task.deadline
            ), 2
        )

        sessions.append({
            'scheduled_date': day,
            'scheduled_hours': round(hours_today, 2),
            'cls_contribution': cls_contribution,
        })

        remaining_hours = round(remaining_hours - hours_today, 2)

    # ── Step 6: Safety net — if hours still remaining ─────────
    # This happens if some days were full due to other tasks
    # Find any day with space and add remaining hours
    if remaining_hours >= 0.5:
        for day in available_days:
            if remaining_hours <= 0:
                break

            existing_hours = get_daily_hours_used(task.user, day, max_focus)
            available_hours = max_focus - existing_hours

            if available_hours < 0.5:
                continue

            hours_today = min(remaining_hours, available_hours)

            # Check if session already exists for this day
            existing_session = next(
                (s for s in sessions if s['scheduled_date'] == day), None
            )

            if existing_session:
                # Add to existing session
                existing_session['scheduled_hours'] = round(
                    existing_session['scheduled_hours'] + hours_today, 2
                )
                existing_session['cls_contribution'] = round(
                    (existing_session['scheduled_hours'] / total_hours) * calculate_cls(
                        difficulty_str, task.hours, task.deadline
                    ), 2
                )
            else:
                cls_contribution = round(
                    (hours_today / total_hours) * calculate_cls(
                        difficulty_str, task.hours, task.deadline
                    ), 2
                )
                sessions.append({
                    'scheduled_date': day,
                    'scheduled_hours': round(hours_today, 2),
                    'cls_contribution': cls_contribution,
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
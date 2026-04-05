from datetime import date, timedelta
from .cls_engine import calculate_cls, get_risk_level


# ─────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────

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
    Generates study sessions for a task.

    Key principles:
    1. Total scheduled hours MUST equal task.hours
    2. Respects max_focus_hours per day
    3. Only counts OTHER tasks' hours when checking daily availability
    4. Urgency-based distribution (urgent = fewer days, more hours/day)
    5. Safety net ensures no hours are lost
    """
    import math
    from schedule.models import StudySession

    today = date.today()
    deadline = task.deadline
    total_hours = round(float(task.hours), 2)
    max_focus = round(float(preference.max_focus_hours), 2)

    # Convert difficulty integer to string
    diff_map = {1: 'easy', 2: 'medium', 3: 'hard'}
    difficulty_str = diff_map.get(task.difficulty, 'medium')

    # Get available weekdays before deadline
    available_days = get_available_days(today, deadline)
    if not available_days:
        return []

    num_available = len(available_days)
    days_until_deadline = (deadline - today).days

    # ── Step 1: Minimum days needed ───────────────────────────
    # How few days can we finish this in? (using max focus each day)
    min_days_needed = math.ceil(total_hours / max_focus)
    min_days_needed = max(1, min(min_days_needed, num_available))

    # ── Step 2: Target days based on urgency ──────────────────
    if days_until_deadline > 14:
        # Far deadline — spread across more days, lighter pace
        target_days = min(num_available, min_days_needed * 3)
    elif days_until_deadline > 7:
        # Medium urgency — moderate spread
        target_days = min(num_available, min_days_needed * 2)
    else:
        # Urgent — use minimum days, maximize hours per session
        target_days = min(num_available, min_days_needed)

    target_days = max(1, target_days)

    # ── Step 3: Hours per session ─────────────────────────────
    # Divide total hours evenly across target days
    raw_hours_per_session = total_hours / target_days

    # Round up to nearest 0.5 for cleaner schedule
    hours_per_session = math.ceil(raw_hours_per_session * 2) / 2

    # Never exceed max_focus per day
    hours_per_session = min(hours_per_session, max_focus)
    hours_per_session = max(hours_per_session, 0.5)

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

    usable_days = available_days[start_index:]
    if not usable_days:
        usable_days = available_days

    # ── Step 5: Space sessions evenly across usable days ──────
    if target_days >= len(usable_days):
        selected_days = list(usable_days)
    else:
        step = len(usable_days) / target_days
        selected_days = [
            usable_days[min(math.floor(i * step), len(usable_days) - 1)]
            for i in range(target_days)
        ]

    # Remove duplicates while preserving order
    seen = set()
    unique_days = []
    for d in selected_days:
        if d not in seen:
            seen.add(d)
            unique_days.append(d)
    selected_days = unique_days
    num_selected = len(selected_days)

    # ── Step 6: Assign hours to each session ──────────────────
    sessions = []
    remaining_hours = total_hours

    for i, day in enumerate(selected_days):
        if remaining_hours <= 0:
            break

        # Only count other tasks' hours — not this task's own sessions
        other_hours = get_other_tasks_hours(user=task.user, task=task, day=day)
        available_hours = round(max_focus - other_hours, 2)

        if available_hours < 0.5:
            continue

        # Last session absorbs all remaining hours
        if i == num_selected - 1:
            hours_today = min(remaining_hours, available_hours)
        else:
            hours_today = min(hours_per_session, available_hours, remaining_hours)

        hours_today = round(hours_today, 2)

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
            'scheduled_hours': hours_today,
            'cls_contribution': cls_contribution,
        })

        remaining_hours = round(remaining_hours - hours_today, 2)

    # ── Step 7: Safety net ────────────────────────────────────
    # If hours are still remaining (some days were full),
    # try ALL available days to absorb the remaining hours
    if remaining_hours >= 0.5:
        for day in available_days:
            if remaining_hours <= 0:
                break

            # Hours from other tasks on this day
            other_hours = get_other_tasks_hours(user=task.user, task=task, day=day)

            # Hours already assigned to this task on this day (in current run)
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

            # Add to existing session for this day if one exists
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
    today = date.today()

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
    Returns count of rescheduled sessions.
    """
    from schedule.models import StudySession

    yesterday = date.today() - timedelta(days=1)
    max_focus = preference.max_focus_hours

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

        # Find next available weekday with enough space
        next_day = date.today()
        deadline = session.task.deadline

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
                rescheduled_count += 1
                break

            next_day += timedelta(days=1)

    return rescheduled_count


# ─────────────────────────────────────────────────────────────
# PROGRESS TRACKER
# ─────────────────────────────────────────────────────────────

def calculate_progress(task):
    """
    Returns progress percentage for a task
    based on completed vs total study sessions.
    """
    from schedule.models import StudySession

    total_sessions = StudySession.objects.filter(task=task)
    if not total_sessions.exists():
        return 0

    completed = total_sessions.filter(is_completed=True).count()
    total = total_sessions.count()

    return round((completed / total) * 100)
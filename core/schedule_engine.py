from datetime import date, timedelta
from .cls_engine import calculate_cls, get_risk_level

def get_available_days(start_date, deadline):
    """
    Returns list of available days between today and deadline
    """
    days = []
    current = start_date
    while current < deadline:
        days.append(current)
        current += timedelta(days=1)
    return days


def generate_study_sessions(task, preference):
    """
    Generates study sessions for a task based on:
    - Task details (hours, deadline, difficulty)
    - User preferences (max focus hours, active study hours)

    Returns list of session dictionaries
    """
    from schedule.models import StudySession

    today = date.today()
    deadline = task.deadline
    total_hours = task.hours
    max_focus = preference.max_focus_hours

    # Get available days before deadline
    available_days = get_available_days(today, deadline)

    if not available_days:
        return []

    # Get existing daily load for each day
    sessions = []
    remaining_hours = total_hours

    for day in available_days:
        if remaining_hours <= 0:
            break

        # Check how many hours already scheduled for this day
        existing_sessions = StudySession.objects.filter(
            user=task.user,
            scheduled_date=day
        )
        existing_hours = sum(s.scheduled_hours for s in existing_sessions)

        # Available hours for this day
        available_hours = max_focus - existing_hours

        if available_hours <= 0:
            continue

        # Schedule as many hours as possible for this day
        hours_today = min(available_hours, remaining_hours)

        # Convert difficulty integer to string for cls_engine
        diff_map = {1: 'easy', 2: 'medium', 3: 'hard'}
        difficulty_str = diff_map.get(task.difficulty, 'medium')

        # Calculate CLS contribution for this session
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

        remaining_hours -= hours_today

    return sessions


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
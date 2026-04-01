from datetime import date

def calculate_urgency(deadline):
    """
    Returns urgency score 0.0 to 10.0
    Closer deadline = higher urgency
    """
    days_remaining = (deadline - date.today()).days

    if days_remaining <= 0:
        return 10.0
    elif days_remaining >= 14:
        return 1.0
    else:
        return round(10 - ((days_remaining - 1) * (9 / 13)), 2)


def calculate_cls(difficulty, hours, deadline):
    """
    Cognitive Load Score (CLS) — ranges from 0.0 to 10.0

    Formula:
    CLS = (difficulty_score × 0.4) + (duration_score × 0.3) + (urgency_score × 0.3)
    """
    # Difficulty score (0-10)
    difficulty_map = {
        'easy':   3.33,
        'medium': 6.67,
        'hard':   10.0
    }
    difficulty_score = difficulty_map.get(difficulty, 5.0)

    # Duration score (0-10), capped at 8 hours max
    duration_score = min((hours / 8) * 10, 10)

    # Urgency score (0-10)
    urgency_score = calculate_urgency(deadline)

    # Final CLS
    cls = (difficulty_score * 0.4) + (duration_score * 0.3) + (urgency_score * 0.3)
    return round(cls, 2)


def get_risk_level(cls_score):
    """
    Returns risk level based on CLS score
    """
    if cls_score >= 7.5:
        return 'High'
    elif cls_score >= 4.5:
        return 'Medium'
    else:
        return 'Low'
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from schedule.models import StudySession
from sleep.models import SleepStudyPreference
from datetime import date, timedelta

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stress_analytics(request):
    user = request.user
    days = int(request.GET.get('days', 30))
    today = date.today()

    # Get max focus hours for percentage calculation
    try:
        preference = SleepStudyPreference.objects.get(user=user)
        max_focus = preference.max_focus_hours
    except SleepStudyPreference.DoesNotExist:
        max_focus = 6.0

    max_cls = max_focus * 1.5

    # Build daily CLS data for the past N days
    labels = []
    values = []

    for i in range(days - 1, -1, -1):
        day_date = today - timedelta(days=i)
        day_sessions = StudySession.objects.filter(
            user=user,
            scheduled_date=day_date
        )
        total_cls = sum(s.cls_contribution for s in day_sessions)
        cls_pct = min(round((total_cls / max_cls) * 100), 100) if max_cls > 0 else 0

        # Format label
        label = day_date.strftime('%a %d %b')
        labels.append(label)
        values.append(cls_pct)

    # Calculate stats
    non_zero = [v for v in values if v > 0]
    avg_load = round(sum(non_zero) / len(non_zero)) if non_zero else 0
    peak_load = max(values) if values else 0
    overload_days = len([v for v in values if v >= 80])
    safe_days = len([v for v in values if v < 60])

    # Burnout risk — 3 or more consecutive high days
    burnout_risk = False
    burnout_msg = None
    consecutive = 0
    for v in values[-7:]:  # check last 7 days
        if v >= 70:
            consecutive += 1
            if consecutive >= 3:
                burnout_risk = True
                burnout_msg = f'You have had high cognitive load for {consecutive} consecutive days. Please take a break and redistribute your tasks.'
                break
        else:
            consecutive = 0

    # Recommendation
    recommendation = None
    if peak_load >= 80:
        recommendation = {
            'alert': f'Your peak cognitive load reached {peak_load}% this period.',
            'suggestion': 'Consider spreading your tasks more evenly across the week to reduce overload.',
            'reduction': round(peak_load - 70)
        }

    return Response({
        'labels': labels,
        'values': values,
        'stats': {
            'avg_load': avg_load,
            'peak_load': peak_load,
            'overload_days': overload_days,
            'safe_days': safe_days,
        },
        'burnout_risk': burnout_risk,
        'burnout_msg': burnout_msg,
        'recommendation': recommendation,
    }, status=status.HTTP_200_OK)
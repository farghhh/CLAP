from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from schedule.models import StudySession
from sleep.models import SleepStudyPreference
from tasks.models import Task
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

    # ── Build date range ──────────────────────────────────────
    # 7  -> past 3 + next 4
    # 14 -> past 7 + next 7
    # 30 -> past 7 + next 23

    if days == 7:
        past_days = 3
        future_days = 4
    elif days == 14:
        past_days = 7
        future_days = 7
    else:
        past_days = 7
        future_days = 23

    start_date = today - timedelta(days=past_days)
    end_date = today + timedelta(days=future_days)

    # Find furthest deadline to ensure we show all upcoming work
    furthest_task = Task.objects.filter(
        user=user,
        is_completed=False
    ).order_by('-deadline').first()

    if furthest_task and furthest_task.deadline > end_date:
        end_date = furthest_task.deadline

    # ── Build daily CLS data ──────────────────────────────────
    labels = []
    values = []
    current = start_date

    while current <= end_date:
        day_sessions = StudySession.objects.filter(
            user=user,
            scheduled_date=current
        )
        total_cls = sum(s.cls_contribution for s in day_sessions)
        cls_pct = min(round((total_cls / max_cls) * 100), 100) if max_cls > 0 else 0

        # Format label — mark today and weekends
        if current == today:
            label = f'TODAY ({current.strftime("%d %b")})'
        else:
            label = current.strftime('%a %d %b')

        labels.append(label)
        values.append(cls_pct)

        current += timedelta(days=1)

    # ── Calculate stats ───────────────────────────────────────
    non_zero = [v for v in values if v > 0]
    avg_load = round(sum(non_zero) / len(non_zero)) if non_zero else 0
    peak_load = max(values) if values else 0
    overload_days = len([v for v in values if v >= 80])
    safe_days = len([v for v in values if v < 60])

    # ── Burnout risk ──────────────────────────────────────────
    # Check for 3 or more consecutive high load days
    burnout_risk = False
    burnout_msg = None
    consecutive = 0

    for v in values:
        if v >= 70:
            consecutive += 1
            if consecutive >= 3:
                burnout_risk = True
                burnout_msg = (
                    f'You have {consecutive} consecutive high load days. '
                    f'Please redistribute your tasks to avoid burnout.'
                )
                break
        else:
            consecutive = 0

    # ── Recommendation ────────────────────────────────────────
    recommendation = None
    if peak_load >= 80:
        recommendation = {
            'alert': f'Your peak cognitive load is {peak_load}%.',
            'suggestion': 'Consider spreading your tasks more evenly to reduce overload.',
            'reduction': round(peak_load - 70)
        }
    elif avg_load >= 60:
        recommendation = {
            'alert': f'Your average cognitive load is {avg_load}%.',
            'suggestion': 'Your workload is moderate. Keep monitoring to avoid overload.',
            'reduction': round(avg_load - 50)
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

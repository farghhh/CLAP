from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import SleepStudyPreference

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_preferences(request):
    # Get data from frontend
    sleep_start = request.data.get('sleep_start')
    sleep_end = request.data.get('sleep_end')
    study_start = request.data.get('study_start')
    study_end = request.data.get('study_end')
    max_focus_hours = request.data.get('max_focus_hours')

    # Check all fields are provided
    if not all([sleep_start, sleep_end, study_start, study_end, max_focus_hours]):
        return Response(
            {'error': 'All fields are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Get user directly from request (JWT handles this automatically)
    user = request.user

    # Save or update preferences
    SleepStudyPreference.objects.update_or_create(
        user=user,
        defaults={
            'sleep_start': sleep_start,
            'sleep_end': sleep_end,
            'active_study_start': study_start,
            'active_study_end': study_end,
            'max_focus_hours': max_focus_hours,
        }
    )

    # Mark onboarding as complete
    user.profile.onboarding_complete = True
    user.profile.save()

    return Response({
        'message': 'Preferences saved successfully!'
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_preferences(request):
    user = request.user
    try:
        preference = SleepStudyPreference.objects.get(user=user)
    except SleepStudyPreference.DoesNotExist:
        return Response(
            {'error': 'Preferences not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    return Response({
        'sleep_start': str(preference.sleep_start),
        'sleep_end': str(preference.sleep_end),
        'study_start': str(preference.active_study_start),
        'study_end': str(preference.active_study_end),
        'max_focus_hours': preference.max_focus_hours,
    }, status=status.HTTP_200_OK)
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

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_preferences(request):
    user = request.user

    # Check preferences exist first
    try:
        preference = SleepStudyPreference.objects.get(user=user)
    except SleepStudyPreference.DoesNotExist:
        return Response(
            {'error': 'Preferences not found. Please complete onboarding first.'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Get data — use existing values as defaults if not provided
    sleep_start = request.data.get('sleep_start', str(preference.sleep_start))
    sleep_end = request.data.get('sleep_end', str(preference.sleep_end))
    study_start = request.data.get('study_start', str(preference.active_study_start))
    study_end = request.data.get('study_end', str(preference.active_study_end))
    max_focus_hours = request.data.get('max_focus_hours', preference.max_focus_hours)

    # Update
    preference.sleep_start = sleep_start
    preference.sleep_end = sleep_end
    preference.active_study_start = study_start
    preference.active_study_end = study_end
    preference.max_focus_hours = max_focus_hours
    preference.save()

    return Response({
        'message': 'Preferences updated successfully!',
        'sleep_start': str(preference.sleep_start),
        'sleep_end': str(preference.sleep_end),
        'study_start': str(preference.active_study_start),
        'study_end': str(preference.active_study_end),
        'max_focus_hours': preference.max_focus_hours,
    }, status=status.HTTP_200_OK)
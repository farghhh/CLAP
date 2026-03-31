from rest_framework import serializers
from .models import SleepStudyPreference

class SleepStudyPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SleepStudyPreference
        fields = [
            'sleep_start',
            'sleep_end',
            'active_study_start',
            'active_study_end',
            'max_focus_hours'
        ]
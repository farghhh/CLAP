from django.db import models
from django.contrib.auth.models import User

def generate_preference_id():
    last = SleepStudyPreference.objects.all().order_by('preference_id').last()
    if not last:
        return 'SP001'
    number = int(last.preference_id[2:])
    return f'SP{number + 1:03d}'

class SleepStudyPreference(models.Model):
    preference_id = models.CharField(max_length=10, primary_key=True, default=generate_preference_id, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    sleep_start = models.TimeField()
    sleep_end = models.TimeField()
    active_study_start = models.TimeField()
    active_study_end = models.TimeField()
    max_focus_hours = models.FloatField(default=6.0)

    def __str__(self):
        return f"{self.user.username}'s preference"
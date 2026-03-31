from django.db import models
from django.contrib.auth.models import User

def generate_log_id():
    last = DailyStressLog.objects.all().order_by('log_id').last()
    if not last:
        return 'L001'
    number = int(last.log_id[1:])
    return f'L{number + 1:03d}'

class DailyStressLog(models.Model):
    log_id = models.CharField(max_length=10, primary_key=True, default=generate_log_id, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField()
    total_cls = models.FloatField(default=0.0)
    cls_percentage = models.FloatField(default=0.0)
    stress_level = models.CharField(max_length=10, default='Low')
    has_recommendation = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.date}"

def generate_recommendation_id():
    last = Recommendation.objects.all().order_by('recommendation_id').last()
    if not last:
        return 'R001'
    number = int(last.recommendation_id[1:])
    return f'R{number + 1:03d}'

class Recommendation(models.Model):
    STATUS_CHOICES = [('Pending','Pending'), ('Accepted','Accepted'), ('Ignored','Ignored')]

    recommendation_id = models.CharField(max_length=10, primary_key=True, default=generate_recommendation_id, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    session = models.ForeignKey('schedule.StudySession', on_delete=models.CASCADE)
    overloaded_date = models.DateField()
    suggested_date = models.DateField()
    stress_reduction = models.FloatField(default=0.0)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Recommendation for {self.user.username} - {self.overloaded_date}"
from django.db import models
from django.contrib.auth.models import User
from tasks.models import Task

def generate_session_id():
    last = StudySession.objects.all().order_by('session_id').last()
    if not last:
        return 'S001'
    number = int(last.session_id[1:])
    return f'S{number + 1:03d}'

class StudySession(models.Model):
    session_id = models.CharField(max_length=10, primary_key=True, default=generate_session_id, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    scheduled_date = models.DateField()
    scheduled_hours = models.FloatField()
    cls_contribution = models.FloatField(default=0.0)
    is_completed = models.BooleanField(default=False)
    is_missed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.task.assignment_title} - {self.scheduled_date}"
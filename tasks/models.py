from django.db import models
from django.contrib.auth.models import User

def generate_task_id():
    last = Task.objects.all().order_by('task_id').last()
    if not last:
        return 'T001'
    number = int(last.task_id[1:])
    return f'T{number + 1:03d}'

class Task(models.Model):
    DIFFICULTY_CHOICES = [(1,'Easy'), (2,'Medium'), (3,'Hard')]

    task_id = models.CharField(max_length=10, primary_key=True, default=generate_task_id, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    course_code = models.CharField(max_length=20)
    title = models.CharField(max_length=200)
    difficulty = models.IntegerField(choices=DIFFICULTY_CHOICES)
    hours = models.FloatField()
    deadline = models.DateField()
    cls_score = models.FloatField(default=0.0)
    risk_level = models.CharField(max_length=10, default='Low')
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.assignment_title
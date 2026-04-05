from django.db import models
from django.contrib.auth.models import User

#django's built in user model (to be compatible with JWT)
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    onboarding_complete = models.BooleanField(default=False)
    profile_picture = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.user.username
from django.db import models

# Create your models here.
class RegisteredUser(models.Model): #table name
    username = models.CharField(max_length=100) #semua ni dari username sampai created_at is attribute utk table RegisteredUser
    email = models.CharField(max_length=100)
    password = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self): #untuk django display username
        return self.username
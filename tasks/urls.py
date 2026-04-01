from django.urls import path
from . import views

urlpatterns = [
    path('', views.assignments, name='assignments'),
    path('<str:task_id>/', views.assignment_detail, name='assignment_detail'),
]
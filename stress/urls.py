from django.urls import path
from . import views

urlpatterns = [
    path('', views.stress_analytics, name='stress_analytics'),
]
from django.urls import path
from . import views

urlpatterns = [
    path('', views.schedule_view, name='schedule'),
    path('sessions/<str:session_id>/complete/', views.complete_session, name='complete_session'),
    path('regenerate/', views.regenerate_schedule, name='regenerate_schedule'),
    path('sessions/<str:session_id>/accept/', views.accept_recommendation, name='accept_recommendation'),
    path('check-missed/', views.check_missed, name='check_missed'),
]
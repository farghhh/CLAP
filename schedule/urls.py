from django.urls import path
from . import views

urlpatterns = [
    path('', views.schedule_view, name='schedule'),
    path('sessions/<str:session_id>/complete/', views.complete_session, name='complete_session'),
]
from django.urls import path
from . import views

urlpatterns = [
    path('preferences/', views.save_preferences, name='save_preferences'),
    path('preferences/get/', views.get_preferences, name='get_preferences'),
    path('preferences/update/', views.update_preferences, name='update_preferences'),
]
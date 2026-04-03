from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', views.login, name='login'),
    path('password/reset/', views.forgot_password, name='forgot_password'),
    path('password/reset/confirm/', views.reset_password, name='reset_password'),
    path('profile/', views.profile, name='profile'),
    path('password/change/', views.change_password, name='change_password'),
]
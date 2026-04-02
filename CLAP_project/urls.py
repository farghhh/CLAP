"""
URL configuration for CLAP_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView
from schedule import views as schedule_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('users.urls')),
    path('api/users/', include('sleep.urls')),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'), #token refresh endpoints
    path('api/assignments/', include('tasks.urls')),
    path('api/schedule/', include('schedule.urls')),
    path('api/dashboard/', schedule_views.dashboard_view, name='dashboard'),
    path('api/stress-analytics/', include('stress.urls')),
]
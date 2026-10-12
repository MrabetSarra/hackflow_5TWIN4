from django.urls import path
from . import views

app_name = 'dashboard_admin'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('participants/', views.participants, name='participants'),
    path('teams/', views.teams, name='teams'),
    path('announcements/', views.announcements, name='announcements'),
    path('judging/', views.judging, name='judging'),
]

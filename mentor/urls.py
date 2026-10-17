from django.urls import path
from . import views

app_name = 'mentor'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('teams/', views.teams_list, name='teams_list'),
    path('requests/', views.help_requests, name='help_requests'),
    path('evaluations/', views.evaluations, name='evaluations'),
]

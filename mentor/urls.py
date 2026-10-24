from django.urls import path
from . import views

app_name = 'mentor'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('teams/', views.teams_list, name='teams_list'),
    path('teams/<int:team_id>/', views.team_detail, name='team_detail'),
    path('teams/<int:team_id>/follow/', views.team_follow, name='team_follow'),
    path('teams/<int:team_id>/unfollow/', views.team_unfollow, name='team_unfollow'),
    path('requests/', views.help_requests, name='help_requests'),
    path('requests/<int:request_id>/take/', views.request_take, name='request_take'),
    path('requests/<int:request_id>/resolve/', views.request_resolve, name='request_resolve'),
    path('requests/<int:request_id>/transfer/', views.request_transfer, name='request_transfer'),
    path('evaluations/', views.evaluations, name='evaluations'),
]

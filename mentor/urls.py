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
    path('requests/triage-status/', views.triage_status, name='triage_status'),
    path('requests/<int:request_id>/triage/correct/', views.triage_correct, name='triage_correct'),
    path('requests/<int:request_id>/triage/retry/', views.triage_retry, name='triage_retry'),
    # Étape 3 — sessions de mentorat
    path('sessions/', views.sessions_list, name='sessions_list'),
    path('sessions/new/', views.session_create, name='session_create'),
    path('sessions/<int:session_id>/edit/', views.session_update, name='session_update'),
    path('sessions/<int:session_id>/cancel/', views.session_cancel, name='session_cancel'),
    path('sessions/<int:session_id>/delete/', views.session_delete, name='session_delete'),
    # Étape 4 — feedback / évaluations multi-critères
    path('submissions/', views.submissions, name='submissions'),
    path('submissions/<int:submission_id>/evaluate/', views.evaluation_create, name='evaluation_create'),
    path('evaluations/', views.evaluations, name='evaluations'),
    path('evaluations/<int:evaluation_id>/', views.evaluation_detail, name='evaluation_detail'),
    path('evaluations/<int:evaluation_id>/edit/', views.evaluation_update, name='evaluation_update'),
    path('evaluations/<int:evaluation_id>/delete/', views.evaluation_delete, name='evaluation_delete'),
    path('evaluations/<int:evaluation_id>/share/', views.evaluation_share, name='evaluation_share'),
]

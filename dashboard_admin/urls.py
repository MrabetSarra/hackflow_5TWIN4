from django.urls import include, path
from . import project_evaluation_views, views

app_name = 'dashboard_admin'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('copilot/ask/', views.copilot_ask, name='copilot_ask'),
    path('announcements/generate/', views.generate_announcement, name='announcement_generate'),
    path('participants/', views.participants, name='participants'),
    path('participants/export.csv', views.participants_export, name='participants_export'),
    path('teams/formation/', views.team_formation, name='team_formation'),
    path('participants/<int:user_id>/team/', views.participant_set_team, name='participant_set_team'),
    path('participants/<int:user_id>/active/', views.participant_toggle_active, name='participant_toggle_active'),
    path('participants/<int:user_id>/', views.participant_detail, name='participant_detail'),
    path('events/', views.events_overview, name='events_overview'),
    path('events/<int:event_id>/edit/', views.event_edit, name='event_edit'),
    path('teams/', views.teams, name='teams'),
    path('announcements/', views.announcements, name='announcements'),
    path('announcements/<int:announcement_id>/edit/', views.announcement_edit, name='announcement_edit'),
    path('announcements/<int:announcement_id>/delete/', views.announcement_delete, name='announcement_delete'),
    path('judging/', project_evaluation_views.judging, name='judging'),
    path('judging/submissions/<int:submission_id>/evaluate/', project_evaluation_views.project_evaluate, name='project_evaluate'),
    path('careers/', include('career_opportunities.organizer_urls')),
]

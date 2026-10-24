from django.urls import path
from . import views

app_name = 'student'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('team/', views.team_detail, name='team_detail'),
    path('matching/', views.skills_matching, name='skills_matching'),
    path('tasks/', views.tasks_kanban, name='tasks_kanban'),
    path('tasks/ai/<int:job_id>/', views.ai_task_job_status, name='ai_task_job_status'),
    path('tasks/ai/<int:job_id>/accept/', views.ai_task_job_accept, name='ai_task_job_accept'),
    path('mentor-request/', views.mentor_request, name='mentor_request'),
    path('submission/', views.project_submission, name='project_submission'),
    path('jury/submissions/', views.jury_submissions, name='jury_submissions'),
    path('jury/submissions/<int:submission_id>/download/', views.download_submission, name='download_submission'),
    path('invitation/<str:token>/<str:decision>/', views.respond_invitation, name='respond_invitation'),
    path('messages/', views.message_inbox, name='messages'),
    path('messages/<int:user_id>/', views.conversation, name='conversation'),
]

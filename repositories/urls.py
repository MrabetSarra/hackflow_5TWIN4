from django.urls import path

from . import views
from . import collaboration

app_name = 'repositories'

urlpatterns = [
    path('mentor/', views.mentor_repository_list, name='mentor_list'),
    path('', views.repository_list, name='list'),
    path('new/', views.repository_create, name='create'),
    path('<slug:slug>/', views.repository_detail, name='detail'),
    path('<slug:slug>/push/', views.repository_push, name='push'),
    path('<slug:slug>/download/', views.repository_download, name='download'),
    path('<slug:slug>/history/', collaboration.history, name='history'),
    path('<slug:slug>/commits/<str:revision>/', collaboration.commit_view, name='commit'),
    path('<slug:slug>/commits/<str:revision>/restore/', collaboration.restore_commit, name='restore'),
    path('<slug:slug>/compare/', collaboration.compare, name='compare'),
    path('<slug:slug>/merge-requests/', collaboration.merge_request_list, name='merge_requests'),
    path('<slug:slug>/merge-requests/<int:request_id>/', collaboration.merge_request_detail, name='merge_request'),
    path('<slug:slug>/merge-requests/<int:request_id>/resolve/', collaboration.resolve_conflicts, name='resolve_conflicts'),
    path('<slug:slug>/ai/suggest/', views.ai_suggestion, name='ai_suggestion'),
    path('<slug:slug>/file-comment/', views.file_comment, name='file_comment'),
]

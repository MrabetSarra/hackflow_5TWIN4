from django.urls import path
from . import views

urlpatterns = [
    path('', views.organizer_dashboard, name='career_dashboard'),
    path('new/', views.organizer_create, name='career_create'),
    path('applications/', views.organizer_applications, name='career_applications'),
    path('applications/<int:pk>/status/', views.organizer_application_status, name='career_application_status'),
    path('applications/<int:pk>/cv/', views.organizer_application_cv, name='career_application_cv'),
    path('<int:pk>/edit/', views.organizer_edit, name='career_edit'),
]

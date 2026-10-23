from django.urls import path
from . import views

app_name = 'career_opportunities'
urlpatterns = [
    path('', views.opportunity_list, name='list'),
    path('applications/', views.my_applications, name='applications'),
    path('applications/<int:pk>/status/', views.application_status, name='application_status'),
    path('<int:pk>/', views.opportunity_detail, name='detail'),
    path('<int:pk>/save/', views.save_toggle, name='save'),
]

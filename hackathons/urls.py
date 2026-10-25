from django.urls import path

from . import public_views as p
from . import views as v

app_name = 'hackathons'

urlpatterns = [
    # Étudiants & mentors
    path('', p.catalog, name='catalog'),
    path('h/<slug:slug>/', p.hackathon_detail, name='hackathon_detail'),
    path('challenges/<int:pk>/', p.challenge_detail, name='challenge_detail'),
    path('challenges/<int:pk>/register/', p.challenge_register, name='challenge_register'),
    path('registrations/', p.my_registrations, name='my_registrations'),
    path('registrations/<int:pk>/cancel/', p.registration_cancel, name='registration_cancel'),
    path('favorites/', v.my_favorites, name='my_favorites'),
    path('favorites/<slug:kind>/<int:pk>/toggle/', v.favorite_toggle, name='favorite_toggle'),
    path('mentor-feedback/hackathon/<int:pk>/', v.mentor_feedback_hackathon, name='mentor_feedback_hackathon'),
    path('mentor-feedback/challenge/<int:pk>/', v.mentor_feedback_challenge, name='mentor_feedback_challenge'),
    path('mentor-feedback/<int:pk>/delete/', v.mentor_feedback_delete, name='mentor_feedback_delete'),

    # Organisateurs
    path('manage/hackathons/', v.hackathon_list, name='hackathon_list'),
    path('manage/hackathons/new/', v.hackathon_form, name='hackathon_create'),
    path('manage/hackathons/<int:pk>/', v.hackathon_manage, name='hackathon_manage'),
    path('manage/hackathons/<int:pk>/edit/', v.hackathon_form, name='hackathon_edit'),
    path('manage/hackathons/<int:pk>/status/', v.hackathon_status, name='hackathon_status'),
    path('manage/hackathons/<int:pk>/stage/', v.hackathon_stage, name='hackathon_stage'),
    path('manage/hackathons/<int:pk>/delete/', v.hackathon_delete, name='hackathon_delete'),
    path('manage/mentor-feedback/', v.mentor_feedback_list, name='mentor_feedback_list'),
    path('manage/hackathons/<int:hackathon_id>/challenges/new/', v.challenge_form, name='challenge_create'),
    path('manage/hackathons/<int:hackathon_id>/challenges/<int:pk>/', v.challenge_manage, name='challenge_manage'),
    path('manage/hackathons/<int:hackathon_id>/challenges/<int:pk>/edit/', v.challenge_form, name='challenge_edit'),
    path('manage/hackathons/<int:hackathon_id>/challenges/<int:pk>/status/', v.challenge_status, name='challenge_status'),
    path('manage/hackathons/<int:hackathon_id>/challenges/<int:pk>/delete/', v.challenge_delete, name='challenge_delete'),
    path('manage/challenges/<int:challenge_id>/<slug:kind>/new/', v.child_form, name='child_create'),
    path('manage/challenges/<int:challenge_id>/<slug:kind>/<int:pk>/edit/', v.child_form, name='child_edit'),
    path('manage/challenges/<int:challenge_id>/<slug:kind>/<int:pk>/delete/', v.child_delete, name='child_delete'),
]

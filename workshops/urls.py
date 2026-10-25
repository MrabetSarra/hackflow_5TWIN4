"""
workshops/urls.py
=================
Toutes les routes du module Ateliers.
Préfixe : /workshops/  (défini dans hackflow/urls.py)
"""

from django.urls import path

from . import api, views

app_name = 'workshops'

urlpatterns = [
    # ---------------------------------------------------------------
    # Catalogue
    # ---------------------------------------------------------------
    path('', views.workshop_list, name='list'),

    # ---------------------------------------------------------------
    # CRUD organisateur
    # ---------------------------------------------------------------
    path('create/', views.workshop_create, name='create'),
    path('<int:pk>/edit/', views.workshop_edit, name='edit'),
    path('<int:pk>/delete/', views.workshop_delete, name='delete'),
    path('<int:pk>/close/', views.workshop_close, name='close'),

    # ---------------------------------------------------------------
    # Mes réservations (étudiant)
    # ---------------------------------------------------------------
    path('my/', views.my_bookings, name='my_bookings'),

    # ---------------------------------------------------------------
    # Réservation / annulation / notation
    # ---------------------------------------------------------------
    path('<int:pk>/seats/', views.select_seat, name='seats'),
    path('<int:pk>/book/', views.book, name='book'),
    path('<int:pk>/cancel/', views.cancel, name='cancel'),
    path('<int:pk>/rate/', views.rate, name='rate'),
    path('<int:pk>/favorite/', views.toggle_favorite, name='favorite'),

    # ---------------------------------------------------------------
    # Check-in QR
    # ---------------------------------------------------------------
    path('<int:pk>/checkin/<str:token>/', views.checkin, name='checkin'),

    # ---------------------------------------------------------------
    # Replay (mode recorded)
    # ---------------------------------------------------------------
    path('<int:pk>/progress/', views.replay_progress, name='replay_progress'),
    path('<int:pk>/complete/', views.replay_complete, name='replay_complete'),

    # ---------------------------------------------------------------
    # Quiz de compréhension (replay)
    # ---------------------------------------------------------------
    path('<int:pk>/quiz/', views.workshop_quiz, name='quiz'),
    path('<int:pk>/quiz/submit/', views.workshop_quiz_submit, name='quiz_submit'),
    path('<int:pk>/quiz/manage/', views.workshop_quiz_manage, name='quiz_manage'),
    path('<int:pk>/quiz/question/add/', views.workshop_quiz_question_add, name='quiz_question_add'),
    path('<int:pk>/quiz/question/<int:qid>/edit/', views.workshop_quiz_question_edit, name='quiz_question_edit'),
    path('<int:pk>/quiz/question/<int:qid>/delete/', views.workshop_quiz_question_delete, name='quiz_question_delete'),

    # ---------------------------------------------------------------
    # Certificats
    # ---------------------------------------------------------------
    path('verify/<str:code>/', views.verify_certificate, name='verify'),
    path('certificate/<int:pk>/download/', views.download_certificate,
         name='download_certificate'),
    path('certificate/<int:pk>/revoke/', views.revoke_certificate,
         name='revoke_certificate'),

    # ---------------------------------------------------------------
    # Dashboard & export
    # ---------------------------------------------------------------
    path('dashboard/', views.organizer_dashboard, name='dashboard'),
    path('export.ics', views.export_ics, name='export_ics'),

    # ---------------------------------------------------------------
    # API JSON (AJAX)
    # ---------------------------------------------------------------
    path('api/recommend/', api.api_recommend, name='api_recommend'),
    path('api/<int:pk>/seats/', api.api_seats, name='api_seats'),
    path('api/generate-description/', api.api_generate_description, name='api_generate_description'),
    path('api/generate-titles/', api.api_generate_titles, name='api_generate_titles'),
    path('api/generate-objectives/', api.api_generate_objectives, name='api_generate_objectives'),
    path('api/generate-summary/', api.api_generate_summary, name='api_generate_summary'),
    path('api/explain-recommendation/', api.api_explain_recommendation, name='api_explain_recommendation'),
    path('api/<int:pk>/generate-quiz/', api.api_generate_quiz, name='api_generate_quiz'),

    # ---------------------------------------------------------------
    # Détail — EN DERNIER (slug peut matcher n'importe quoi)
    # ---------------------------------------------------------------
    path('<slug:slug>/', views.workshop_detail, name='detail'),
]

"""
URL configuration for hackflow project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from repositories.views import mentor_repository_list
from core.views import healthz
urlpatterns = [
    path('healthz/', healthz, name='healthz'),
    path('prometheus/', include('django_prometheus.urls')),
    # Espace Public / Landing
    path('', include('core.urls')),

    # Espace Authentification & Profil
    path('accounts/', include('accounts.urls')),

    # Espace Étudiant (Participant)
    path('student/', include('student.urls')),
    path('student/repositories/', include('repositories.urls')),
    path('mentor/repositories/', mentor_repository_list, name='mentor_repositories'),

    # Espace Mentor (Accompagnement)
    path('mentor/', include('mentor.urls')),

    # Espace Administrateur (Organisateur)
    path('cockpit/', include('dashboard_admin.urls')),
    path('careers/', include('career_opportunities.urls')),

    # Module Ateliers & Formations
    path('workshops/', include('workshops.urls')),
    # Tracks, Hackathons & Challenges
    path('hackathons/', include('hackathons.urls')),

    # Django Admin Technique (Standard)
    path('admin/', admin.site.urls),
]

handler403 = 'core.views.error_403'
handler404 = 'core.views.error_404'
handler500 = 'core.views.error_500'

# Servir les fichiers médias en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])


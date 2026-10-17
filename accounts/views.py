<<<<<<< HEAD
from django.shortcuts import render

def login_view(request):
    """
    Vue de connexion visuelle.
    Permet de tester l'authentification et offre des boutons de connexion démo directe vers les 3 rôles.
    """
    context = {
        'demo_accounts': [
            {
                'role': 'Étudiant',
                'name': 'Camille Laurent',
                'email': 'camille.laurent@etu.univ.fr',
                'url': 'student:dashboard',
                'badge_color': 'primary',
                'icon': 'bi-mortarboard-fill',
            },
            {
                'role': 'Mentor',
                'name': 'Dr. Marc Dubois',
                'email': 'marc.dubois@mentor.hackflow.fr',
                'url': 'mentor:dashboard',
                'badge_color': 'secondary',
                'icon': 'bi-lightbulb-fill',
            },
            {
                'role': 'Admin (Organisateur)',
                'name': 'Alexandre Moreau',
                'email': 'alexandre.moreau@hackflow.fr',
                'url': 'dashboard_admin:dashboard',
                'badge_color': 'danger',
                'icon': 'bi-shield-lock-fill',
            },
        ]
    }
    return render(request, 'accounts/login.html', context)


def register_view(request):
    """
    Vue d'inscription avec sélection de profil et tags de compétences.
    """
    context = {
        'available_skills': [
            'Python / Django', 'React / TypeScript', 'Vue.js', 'FastAPI',
            'UI/UX & Figma', 'IA & Machine Learning', 'DevOps & Docker',
            'Flutter / Mobile', 'PostgreSQL', 'Pitch & Business Model'
        ],
        'study_levels': [
            'Licence 1 ou 2', 'Licence 3 / BUT', 'Master 1', 'Master 2 / Cycle Ingénieur', 'Autre cursus'
        ]
    }
    return render(request, 'accounts/register.html', context)


def profile_view(request):
    """
    Vue de consultation et édition visuelle du profil utilisateur.
    """
    context = {
        'user': {
            'first_name': 'Camille',
            'last_name': 'Laurent',
            'role': 'Étudiant Participant',
            'school': 'Université Polytechnique - Faculté des Sciences',
            'level': 'Licence 3 Informatique',
            'email': 'camille.laurent@etu.univ.fr',
            'github': 'camille-laurent',
            'linkedin': 'camille-laurent-dev',
            'portfolio': 'https://camillelaurent.dev',
            'bio': 'Étudiante passionnée par le développement d\'applications web et les outils collaboratifs. Recherche des projets axés sur la transition écologique et l\'intelligence artificielle.',
            'avatar': 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=200&auto=format&fit=crop&q=80',
            'team_name': 'EcoTrack',
            'team_role': 'Team Leader & Fullstack Dev',
            'skills': ['Python', 'Django', 'React', 'TypeScript', 'Tailwind', 'PostgreSQL', 'Docker'],
            'badges': [
                {'name': 'Hackathon Vétéran', 'icon': 'bi-award-fill', 'color': 'warning'},
                {'name': 'Code Ninja', 'icon': 'bi-terminal-fill', 'color': 'primary'},
                {'name': 'Team Leader', 'icon': 'bi-star-fill', 'color': 'success'},
                {'name': 'Profil Vérifié', 'icon': 'bi-patch-check-fill', 'color': 'info'},
            ]
        }
    }
    return render(request, 'accounts/profile.html', context)
=======
import logging
import secrets
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import (
    EmailOrUsernameAuthenticationForm,
    PasswordResetRequestForm,
    PasswordResetVerifyForm,
    ProfileAssetsForm,
    ProfileDetailsForm,
)
from .models import PasswordResetCode


logger = logging.getLogger(__name__)


ROLE_DESTINATIONS = {
    'student': 'student:dashboard',
    'mentor': 'mentor:dashboard',
    'admin': 'dashboard_admin:dashboard',
}


def _default_destination(user):
    return reverse(ROLE_DESTINATIONS.get(user.role, 'core:landing'))


def login_view(request):
    """Authenticate users and send them to the workspace for their role."""
    next_url = request.POST.get('next') or request.GET.get('next')
    if request.user.is_authenticated:
        if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect(_default_destination(request.user))

    form = EmailOrUsernameAuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        auth_login(request, user)
        if not request.POST.get('remember_me'):
            request.session.set_expiry(0)
        if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect(_default_destination(user))

    return render(request, 'accounts/login.html', {'form': form, 'next': next_url})


@login_required
def logout_view(request):
    auth_logout(request)
    return redirect('accounts:login')


def password_reset_request_view(request):
    form = PasswordResetRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email'].strip()
        users = get_user_model().objects.filter(
            email__iexact=email,
            is_active=True,
        )
        if users.count() == 1:
            user = users.get()
            now = timezone.now()
            latest_request = PasswordResetCode.objects.filter(user=user).order_by('-created_at').first()
            if not latest_request or latest_request.created_at <= now - timedelta(minutes=1):
                PasswordResetCode.objects.filter(user=user, used_at__isnull=True).delete()
                code = f'{secrets.randbelow(1_000_000):06d}'
                reset_code = PasswordResetCode.objects.create(
                    user=user,
                    code_hash=make_password(code),
                    expires_at=now + timedelta(minutes=10),
                )
                try:
                    send_mail(
                        subject='Votre code de vérification HackFlow',
                        message=(
                            f'Bonjour {user.first_name or user.username},\n\n'
                            f'Votre code de réinitialisation HackFlow est : {code}\n\n'
                            'Ce code est valable pendant 10 minutes et ne peut être utilisé qu’une seule fois. '
                            'Si vous n’avez pas demandé cette réinitialisation, ignorez ce message.'
                        ),
                        from_email=None,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except Exception:
                    logger.exception('Password reset email delivery failed for user id %s', user.pk)
        return render(request, 'accounts/password_reset_request.html', {'form': form, 'submitted': True})

    return render(request, 'accounts/password_reset_request.html', {'form': form})


def password_reset_verify_view(request):
    form = PasswordResetVerifyForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email'].strip()
        users = get_user_model().objects.filter(
            email__iexact=email,
            is_active=True,
        )
        user = users.get() if users.count() == 1 else None
        reset_code = None
        if user:
            reset_code = PasswordResetCode.objects.filter(
                user=user,
                used_at__isnull=True,
                expires_at__gt=timezone.now(),
                attempts__lt=5,
            ).order_by('-created_at').first()

        if not user or not reset_code or not check_password(form.cleaned_data['code'], reset_code.code_hash):
            if reset_code:
                reset_code.attempts += 1
                reset_code.save(update_fields=['attempts'])
            form.add_error('code', 'Code invalide ou expiré. Demandez un nouveau code et réessayez.')
        else:
            try:
                validate_password(form.cleaned_data['new_password1'], user=user)
            except ValidationError as error:
                form.add_error('new_password1', error)
            else:
                user.set_password(form.cleaned_data['new_password1'])
                user.save(update_fields=['password'])
                reset_code.used_at = timezone.now()
                reset_code.save(update_fields=['used_at'])
                PasswordResetCode.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())
                return render(request, 'accounts/password_reset_verify.html', {'form': form, 'completed': True})

    return render(request, 'accounts/password_reset_verify.html', {'form': form})

def register_view(request):
    if request.user.is_authenticated:
        return redirect(_default_destination(request.user))
    return render(request, 'accounts/register.html')


def register_role_view(request, role):
    if role not in ('student', 'mentor'):
        from django.http import Http404
        raise Http404
    if request.user.is_authenticated:
        return redirect(_default_destination(request.user))

    from .forms import AccountRegistrationForm
    form = AccountRegistrationForm(request.POST or None, role=role)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        auth_login(request, user)
        return redirect(_default_destination(user))

    role_labels = {'student': 'Étudiant', 'mentor': 'Mentor'}
    return render(request, 'accounts/register_form.html', {
        'form': form,
        'role': role,
        'role_label': role_labels[role],
    })

@login_required
def profile_view(request):
    details_form = ProfileDetailsForm(
        request.POST if request.method == 'POST' and request.POST.get('form_type') == 'details' else None,
        instance=request.user,
    )
    form = ProfileAssetsForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == 'POST' and request.POST.get('form_type') == 'details':
        if details_form.is_valid():
            details_form.save()
            messages.success(request, 'Les informations de votre profil ont été mises à jour.')
            return redirect('accounts:profile')
        return render(request, 'accounts/profile.html', {
            'profile_user': request.user,
            'assets_form': form,
            'details_form': details_form,
            'editing_details': True,
        })
    if request.method == 'POST' and form.is_valid():
        old_photo = request.user.profile_photo
        old_cv = request.user.cv
        profile_user = form.save()
        if old_photo and old_photo.name != profile_user.profile_photo.name:
            old_photo.delete(save=False)
        if old_cv and old_cv.name != profile_user.cv.name:
            old_cv.delete(save=False)
        messages.success(request, 'Votre photo et votre CV ont été mis à jour.')
        return redirect('accounts:profile')

    return render(request, 'accounts/profile.html', {
        'profile_user': request.user,
        'assets_form': form,
        'details_form': details_form,
        'editing_details': request.GET.get('edit') == '1',
    })


@login_required
def download_cv_view(request):
    if not request.user.cv:
        raise Http404
    return FileResponse(
        request.user.cv.open('rb'),
        as_attachment=True,
        filename=Path(request.user.cv.name).name,
        content_type='application/pdf',
    )
>>>>>>> gestion_evenements

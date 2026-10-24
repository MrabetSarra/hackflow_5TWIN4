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
from django.db import transaction
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
from student.models import Hackathon, HackathonRegistration


def _sync_student_skills_from_cv(user, analysis):
    """Merge CV-detected skills into the profile's existing skill categories."""
    if analysis.get('status') != 'ready':
        return []
    extracted = {item.get('name', '').casefold() for item in analysis.get('data', {}).get('skills', [])}
    skill_groups = {
        'Python / Django': {'python', 'django'},
        'React / TypeScript': {'react', 'javascript', 'typescript'},
        'Vue.js': {'vue.js'}, 'FastAPI': {'fastapi'},
        'UI/UX & Figma': {'figma'},
        'IA & Machine Learning': {'machine learning', 'tensorflow', 'pytorch'},
        'DevOps & Docker': {'docker', 'kubernetes', 'aws', 'azure', 'linux'},
        'Flutter / Mobile': {'flutter'}, 'PostgreSQL': {'postgresql'},
    }
    detected = [label for label, names in skill_groups.items() if names & extracted]
    existing = user.skills or []
    additions = [skill for skill in detected if skill not in existing]
    if additions:
        user.skills = existing + additions
        user.save(update_fields=['skills'])
    return additions


logger = logging.getLogger(__name__)


ROLE_DESTINATIONS = {
    'student': 'student:dashboard',
    'mentor': 'mentor:dashboard',
    'admin': 'dashboard_admin:dashboard',
    'organization': 'dashboard_admin:dashboard',
}


def _default_destination(user):
    return reverse(ROLE_DESTINATIONS.get(user.role, 'core:landing'))


def login_view(request):
    """Show the login form and send successful logins to the user's workspace."""
    next_url = request.POST.get('next') or request.GET.get('next')

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
                        subject='Your HackFlow verification code',
                        message=(
                            f'Bonjour {user.first_name or user.username},\n\n'
                            f'Your HackFlow password reset code is: {code}\n\n'
                            'This code is valid for 10 minutes and can only be used once. '
                            'If you did not request this reset, you can ignore this message.'
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
            form.add_error('code', 'Invalid or expired code. Request a new code and try again.')
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
        with transaction.atomic():
            user = form.save()
            active_hackathon = Hackathon.objects.filter(
                is_active=True,
                ends_at__gte=timezone.now(),
            ).order_by('starts_at').first()
            if active_hackathon:
                HackathonRegistration.objects.get_or_create(hackathon=active_hackathon, user=user)
        auth_login(request, user)
        return redirect(_default_destination(user))

    role_labels = {'student': 'Student', 'mentor': 'Mentor'}
    return render(request, 'accounts/register_form.html', {
        'form': form,
        'role': role,
        'role_label': role_labels[role],
    })

@login_required
def profile_view(request):
    role = getattr(request.user, 'role', None)
    if role in ('admin', 'organization'):
        layout_template = 'layouts/base_admin.html'
    elif role == 'mentor':
        layout_template = 'layouts/base_mentor.html'
    else:
        layout_template = 'layouts/base_student.html'
    cv_skill_additions = []
    cv_detected_skills = []
    if request.user.role == 'student' and request.user.cv:
        from career_opportunities.services.cv_analysis import analyze_student_cv
        cv_analysis = analyze_student_cv(request.user)
        cv_detected_skills = cv_analysis.get('data', {}).get('skills', [])
        cv_skill_additions = _sync_student_skills_from_cv(request.user, cv_analysis)
    details_form = ProfileDetailsForm(
        request.POST if request.method == 'POST' and request.POST.get('form_type') == 'details' else None,
        instance=request.user,
    )
    form = ProfileAssetsForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == 'POST' and request.POST.get('form_type') == 'details':
        if details_form.is_valid():
            details_form.save()
            messages.success(request, 'Your profile information has been updated.' if request.user.role == 'student' else 'Les informations de votre profil ont été mises à jour.')
            return redirect('accounts:profile')
        return render(request, 'accounts/profile.html', {
            'layout_template': layout_template,
            'profile_user': request.user,
            'assets_form': form,
            'details_form': details_form,
            'editing_details': True,
            'cv_detected_skills': cv_detected_skills,
        })
    if request.method == 'POST' and form.is_valid():
        old_photo = request.user.profile_photo
        old_cv = request.user.cv
        profile_user = form.save()
        cv_changed = bool(profile_user.cv and (not old_cv or old_cv.name != profile_user.cv.name))
        if old_photo and old_photo.name != profile_user.profile_photo.name:
            old_photo.delete(save=False)
        if old_cv and old_cv.name != profile_user.cv.name:
            from career_opportunities.models import CareerApplication
            if not CareerApplication.objects.filter(cv=old_cv.name).exists():
                old_cv.delete(save=False)
        if cv_changed and profile_user.role == 'student':
            from career_opportunities.services.cv_analysis import analyze_student_cv
            analysis = analyze_student_cv(profile_user)
            if analysis['status'] != 'ready':
                messages.warning(request, 'The CV was saved privately, but no readable text could be extracted. Upload a text-based PDF to enable matching.')
            else:
                cv_skill_additions = _sync_student_skills_from_cv(profile_user, analysis)
                if cv_skill_additions:
                    messages.success(request, f"Skills added from your CV: {', '.join(cv_skill_additions)}.")
        messages.success(request, 'Your profile photo and CV have been updated.' if request.user.role == 'student' else 'Votre photo et votre CV ont été mis à jour.')
        return redirect('accounts:profile')

    return render(request, 'accounts/profile.html', {
        'layout_template': layout_template,
        'profile_user': request.user,
        'assets_form': form,
        'details_form': details_form,
        'editing_details': request.GET.get('edit') == '1',
        'cv_detected_skills': cv_detected_skills,
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

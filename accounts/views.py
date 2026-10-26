import base64
import io
import logging
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import qrcode
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
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
    TwoFactorDisableForm,
    TwoFactorRegenerateBackupCodesForm,
    TwoFactorSetupForm,
    TwoFactorVerifyForm,
)
from .models import PasswordResetCode
from .oauth import OAuthError, get_oauth_provider, get_or_create_oauth_user
from student.models import Hackathon, HackathonRegistration


def _sync_student_skills_from_cv(user, analysis):
    """Merge CV-detected skills into the profile's existing skill categories."""
    if analysis.get('status') != 'ready':
        return []
    extracted = {item.get('name', '').casefold() for item in analysis.get('data', {}).get('skills', [])}
    skill_groups = {
        'Python / Django': {'python', 'django'},
        'React / TypeScript': {'react', 'javascript', 'typescript', 'next.js', 'angular', 'vue.js'},
        'Vue.js': {'vue.js'},
        'FastAPI': {'fastapi', 'node.js', 'express', 'rest api'},
        'UI/UX & Figma': {'figma', 'ui/ux', 'tailwind css', 'html/css'},
        'IA & Machine Learning': {'machine learning', 'deep learning', 'tensorflow', 'pytorch', 'rag', 'chromadb', 'nlp', 'scikit-learn', 'langchain'},
        'DevOps & Docker': {'docker', 'kubernetes', 'aws', 'azure', 'gcp', 'linux', 'ci/cd', 'git'},
        'Flutter / Mobile': {'flutter'},
        'PostgreSQL': {'postgresql', 'postgres', 'sql', 'mysql', 'mongodb'},
    }
    detected = [label for label, names in skill_groups.items() if names & extracted]
    existing = list(user.skills or [])
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
        if user.two_factor_enabled:
            request.session['2fa_user_id'] = user.pk
            request.session['2fa_remember_me'] = bool(request.POST.get('remember_me'))
            if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
                request.session['2fa_next_url'] = next_url
            return redirect('accounts:two_factor_verify')

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

def _get_layout_template(user):
    role = getattr(user, 'role', None)
    if role in ('admin', 'organization'):
        return 'layouts/base_admin.html'
    elif role == 'mentor':
        return 'layouts/base_mentor.html'
    return 'layouts/base_student.html'


@login_required
def profile_view(request):
    layout_template = _get_layout_template(request.user)
    cv_skill_additions = []
    cv_detected_skills = []

    force_sync = request.GET.get('sync_cv') == '1' or (
        request.method == 'POST' and request.POST.get('action') == 'sync_cv_skills'
    )

    if request.user.cv:
        from career_opportunities.services.cv_analysis import analyze_student_cv
        cv_analysis = analyze_student_cv(request.user, force=force_sync)
        cv_detected_skills = cv_analysis.get('data', {}).get('skills', [])
        cv_skill_additions = _sync_student_skills_from_cv(request.user, cv_analysis)
        if force_sync:
            detected_names = [s.get('name') for s in cv_detected_skills if s.get('name')]
            if detected_names:
                messages.success(
                    request,
                    f"Compétences extraites avec succès de votre CV ({len(detected_names)}) : {', '.join(detected_names)}."
                )
            elif cv_analysis.get('status') == 'ready':
                messages.info(request, "L'analyse du CV est terminée mais aucune compétence connue n'a été détectée.")
            else:
                messages.warning(request, "Impossible de lire le texte de ce fichier PDF. Assurez-vous d'utiliser un PDF textuel.")
            return redirect('accounts:profile')
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
        photo_uploaded = bool(request.FILES.get('profile_photo'))
        cv_uploaded = bool(request.FILES.get('cv'))
        try:
            profile_user = form.save()
            if photo_uploaded:
                # Resolve the URL now so storage/configuration failures cannot look like a
                # successful upload followed by a broken image on the next page load.
                photo_url = profile_user.profile_photo.url
        except Exception as error:
            logger.error(
                'Profile asset upload failed (user_id=%s, error_type=%s)',
                request.user.pk, type(error).__name__,
            )
            return HttpResponse(
                'Your image or file could not be uploaded. Please try again.', status=503,
            )
        if photo_uploaded:
            storage = profile_user.profile_photo.storage
            logger.info(
                'Profile photo upload succeeded (user_id=%s, storage_backend=%s, url_host=%s)',
                profile_user.pk,
                f'{storage.__class__.__module__}.{storage.__class__.__name__}',
                urlsplit(photo_url).hostname or 'relative',
            )
        cv_changed = cv_uploaded or bool(profile_user.cv and (not old_cv or old_cv.name != profile_user.cv.name))
        if old_photo and old_photo.name != profile_user.profile_photo.name:
            try:
                old_photo.delete(save=False)
            except Exception as error:
                logger.warning('Old profile photo cleanup failed (user_id=%s, error_type=%s)', profile_user.pk, type(error).__name__)
        if old_cv and old_cv.name != profile_user.cv.name:
            from career_opportunities.models import CareerApplication
            if not CareerApplication.objects.filter(cv=old_cv.name).exists():
                try:
                    old_cv.delete(save=False)
                except Exception as error:
                    logger.warning('Old private CV cleanup failed (user_id=%s, error_type=%s)', profile_user.pk, type(error).__name__)
        if cv_changed and profile_user.cv:
            from career_opportunities.services.cv_analysis import analyze_student_cv
            analysis = analyze_student_cv(profile_user, force=True)
            if analysis.get('status') != 'ready':
                messages.warning(request, 'The CV was saved privately, but no readable text could be extracted. Upload a text-based PDF to enable matching.' if profile_user.role == 'student' else "Le CV a été enregistré, mais aucun texte lisible n'a pu être extrait. Téléversez un PDF textuel pour activer la détection des compétences.")
            else:
                cv_skill_additions = _sync_student_skills_from_cv(profile_user, analysis)
                detected = [s.get('name') for s in analysis.get('data', {}).get('skills', []) if s.get('name')]
                if detected:
                    messages.success(request, f"Compétences extraites avec succès de votre CV : {', '.join(detected)}.")
                elif cv_skill_additions:
                    messages.success(request, f"Skills added from your CV: {', '.join(cv_skill_additions)}." if profile_user.role == 'student' else f"Compétences ajoutées à votre profil : {', '.join(cv_skill_additions)}.")
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
    try:
        file_handle = request.user.cv.open('rb')
    except Exception as error:
        logger.error('Private CV download failed (user_id=%s, error_type=%s)', request.user.pk, type(error).__name__)
        return HttpResponse('File storage is temporarily unavailable.', status=503)
    response = FileResponse(file_handle, as_attachment=True,
                            filename=Path(request.user.cv.name).name,
                            content_type='application/pdf')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def two_factor_verify_view(request):
    """Verify 2FA TOTP or backup code before completing login."""
    if request.user.is_authenticated:
        return redirect(_default_destination(request.user))

    user_id = request.session.get('2fa_user_id')
    if not user_id:
        return redirect('accounts:login')

    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if not user or not user.two_factor_enabled:
        request.session.pop('2fa_user_id', None)
        request.session.pop('2fa_remember_me', None)
        request.session.pop('2fa_next_url', None)
        return redirect('accounts:login')

    if request.GET.get('cancel'):
        request.session.pop('2fa_user_id', None)
        request.session.pop('2fa_remember_me', None)
        request.session.pop('2fa_next_url', None)
        return redirect('accounts:login')

    form = TwoFactorVerifyForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        code = form.cleaned_data['code']
        is_totp_valid = user.verify_totp(code)
        is_backup_valid = False if is_totp_valid else user.verify_and_consume_backup_code(code)

        if is_totp_valid or is_backup_valid:
            remember_me = request.session.pop('2fa_remember_me', False)
            next_url = request.session.pop('2fa_next_url', None)
            request.session.pop('2fa_user_id', None)

            auth_login(request, user)
            if not remember_me:
                request.session.set_expiry(0)

            if is_backup_valid:
                messages.warning(
                    request,
                    'Vous vous êtes connecté avec un code de secours. Pensez à vérifier vos codes restants dans votre profil.'
                )

            if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect(_default_destination(user))
        else:
            form.add_error('code', 'Code de vérification ou code de secours invalide.')

    return render(request, 'accounts/two_factor_verify.html', {
        'form': form,
        'user_identifier': user.email or user.username,
    })


@login_required
def two_factor_setup_view(request):
    """Enable 2FA by scanning QR code and verifying the first TOTP code."""
    if request.user.two_factor_enabled:
        messages.info(request, "L'authentification à deux facteurs est déjà activée sur votre compte.")
        return redirect('accounts:profile')

    setup_secret = request.session.get('2fa_setup_secret')
    if not setup_secret:
        setup_secret = request.user.generate_two_factor_secret()
        request.session['2fa_setup_secret'] = setup_secret

    totp_uri = request.user.get_totp_uri(secret=setup_secret)

    # Generate QR Code image in base64
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(totp_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1e293b", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_b64 = base64.b64encode(buffer.getvalue()).decode()

    # Formatted secret for display (e.g. ABCD EFGH ...)
    secret_formatted = ' '.join([setup_secret[i:i+4] for i in range(0, len(setup_secret), 4)])

    form = TwoFactorSetupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        code = form.cleaned_data['code']
        if request.user.verify_totp(code, secret=setup_secret):
            request.user.two_factor_secret = setup_secret
            plain_backup_codes = request.user.generate_backup_codes()
            request.user.two_factor_enabled = True
            request.user.save(update_fields=['two_factor_secret', 'backup_codes', 'two_factor_enabled'])
            request.session.pop('2fa_setup_secret', None)
            request.session['2fa_new_backup_codes'] = plain_backup_codes
            messages.success(request, 'Authentification à deux facteurs activée avec succès !')
            return redirect('accounts:two_factor_backup_codes')
        else:
            form.add_error('code', "Code de vérification invalide. Vérifiez l'heure de votre appareil et réessayez.")

    return render(request, 'accounts/two_factor_setup.html', {
        'layout_template': _get_layout_template(request.user),
        'form': form,
        'qr_b64': qr_b64,
        'secret': setup_secret,
        'secret_formatted': secret_formatted,
    })


@login_required
def two_factor_backup_codes_view(request):
    """Display generated backup codes or allow regenerating them with password confirmation."""
    if not request.user.two_factor_enabled:
        messages.error(request, "L'authentification à deux facteurs n'est pas activée.")
        return redirect('accounts:profile')

    layout_template = _get_layout_template(request.user)
    new_codes = request.session.pop('2fa_new_backup_codes', None)
    if new_codes:
        return render(request, 'accounts/two_factor_backup_codes.html', {
            'layout_template': layout_template,
            'backup_codes': new_codes,
            'just_generated': True,
        })

    form = TwoFactorRegenerateBackupCodesForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        plain_backup_codes = request.user.generate_backup_codes()
        request.user.save(update_fields=['backup_codes'])
        messages.success(request, 'Un nouveau jeu de codes de secours a été généré.')
        return render(request, 'accounts/two_factor_backup_codes.html', {
            'layout_template': layout_template,
            'backup_codes': plain_backup_codes,
            'just_generated': True,
        })

    return render(request, 'accounts/two_factor_backup_codes.html', {
        'layout_template': layout_template,
        'form': form,
        'remaining_count': len(request.user.backup_codes or []),
        'just_generated': False,
    })


@login_required
def two_factor_disable_view(request):
    """Disable 2FA after password confirmation."""
    if not request.user.two_factor_enabled:
        return redirect('accounts:profile')

    form = TwoFactorDisableForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        request.user.two_factor_enabled = False
        request.user.two_factor_secret = ''
        request.user.backup_codes = []
        request.user.save(update_fields=['two_factor_enabled', 'two_factor_secret', 'backup_codes'])
        messages.success(request, "L'authentification à deux facteurs a été désactivée avec succès.")
        return redirect('accounts:profile')

    return render(request, 'accounts/two_factor_disable.html', {
        'layout_template': _get_layout_template(request.user),
        'form': form,
    })


def oauth_login_view(request, provider):
    """Initiate OAuth authorization redirect for Google or GitHub."""
    try:
        oauth_provider = get_oauth_provider(provider)
    except ValueError:
        raise Http404("Fournisseur OAuth inconnu.")

    role = request.GET.get('role')
    if role:
        if role not in ('student', 'mentor'):
            raise Http404("Rôle non autorisé. Seuls les comptes Étudiant et Mentor sont permis.")
        request.session['oauth_role'] = role
    else:
        request.session.pop('oauth_role', None)

    if not oauth_provider.is_configured():
        messages.warning(
            request,
            f"L'authentification via {provider.capitalize()} n'est pas encore configurée dans les variables d'environnement "
            f"({provider.upper()}_CLIENT_ID et {provider.upper()}_CLIENT_SECRET)."
        )
        return redirect('accounts:login')

    state = secrets.token_urlsafe(32)
    request.session['oauth_state'] = state
    request.session['oauth_provider'] = provider

    next_url = request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
        request.session['oauth_next'] = next_url

    redirect_uri = request.build_absolute_uri(reverse('accounts:oauth_callback', args=[provider]))
    auth_url = oauth_provider.get_authorization_url(redirect_uri=redirect_uri, state=state)
    return redirect(auth_url)


def oauth_callback_view(request, provider):
    """Handle OAuth authorization callback, exchange code, and log user in."""
    try:
        oauth_provider = get_oauth_provider(provider)
    except ValueError:
        raise Http404("Fournisseur OAuth inconnu.")

    if request.GET.get('error'):
        error_msg = request.GET.get('error_description') or request.GET.get('error')
        logger.warning("OAuth error returned by %s: %s", provider, error_msg)
        messages.warning(request, f"Connexion {provider.capitalize()} annulée.")
        return redirect('accounts:login')

    expected_state = request.session.pop('oauth_state', None)
    state = request.GET.get('state')
    if not state or not expected_state or state != expected_state:
        messages.error(request, "Échec de validation de sécurité OAuth (state invalide). Veuillez réessayer.")
        return redirect('accounts:login')

    code = request.GET.get('code')
    if not code:
        messages.error(request, "Code d'autorisation manquant.")
        return redirect('accounts:login')

    redirect_uri = request.build_absolute_uri(reverse('accounts:oauth_callback', args=[provider]))

    try:
        user_info = oauth_provider.get_user_info(code=code, redirect_uri=redirect_uri)
    except OAuthError as err:
        logger.error("OAuth authentication failed for %s: %s", provider, err)
        messages.error(request, f"Erreur lors de l'authentification avec {provider.capitalize()} : {err}")
        return redirect('accounts:login')
    except Exception:
        logger.exception("Unexpected error during OAuth login with %s", provider)
        messages.error(request, f"Une erreur inattendue est survenue lors de la connexion avec {provider.capitalize()}.")
        return redirect('accounts:login')

    email = user_info['email'].strip().lower()
    existing_user = get_user_model().objects.filter(email__iexact=email).first()

    if existing_user:
        user, created = get_or_create_oauth_user(user_info, provider)
    else:
        requested_role = request.session.pop('oauth_role', None)
        if requested_role in ('student', 'mentor'):
            user, created = get_or_create_oauth_user(user_info, provider, role=requested_role)
        else:
            # Let the new user select their role (Student or Mentor only)
            request.session['oauth_pending_user_info'] = user_info
            request.session['oauth_pending_provider'] = provider
            return redirect('accounts:oauth_select_role')

    next_url = request.session.pop('oauth_next', None)

    # If user has 2FA enabled, enforce second factor verification!
    if user.two_factor_enabled:
        request.session['2fa_user_id'] = user.pk
        request.session['2fa_remember_me'] = True
        if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
            request.session['2fa_next_url'] = next_url
        messages.info(request, "Veuillez saisir votre code d'authentification 2FA pour terminer la connexion.")
        return redirect('accounts:two_factor_verify')

    auth_login(request, user)

    if created:
        messages.success(request, f"Bienvenue sur HackFlow ! Votre compte a été créé avec succès via {provider.capitalize()}.")
    else:
        messages.success(request, f"Ravi de vous revoir ! Connexion réussie via {provider.capitalize()}.")

    if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect(_default_destination(user))


def oauth_select_role_view(request):
    """Allow newly registered OAuth users to select their role (strictly Student or Mentor only)."""
    user_info = request.session.get('oauth_pending_user_info')
    provider = request.session.get('oauth_pending_provider', 'github')

    if not user_info:
        return redirect('accounts:login')

    if request.method == 'POST':
        chosen_role = request.POST.get('role')
        if chosen_role not in ('student', 'mentor'):
            messages.error(request, "Choix non autorisé. Seuls les comptes Étudiant et Mentor peuvent être créés.")
            return render(request, 'accounts/oauth_select_role.html', {
                'user_info': user_info,
                'provider': provider,
            })

        user, created = get_or_create_oauth_user(user_info, provider, role=chosen_role)
        request.session.pop('oauth_pending_user_info', None)
        request.session.pop('oauth_pending_provider', None)
        next_url = request.session.pop('oauth_next', None)

        auth_login(request, user)
        messages.success(request, f"Bienvenue sur HackFlow ! Votre compte a été créé avec succès.")

        if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect(_default_destination(user))

    return render(request, 'accounts/oauth_select_role.html', {
        'user_info': user_info,
        'provider': provider,
    })

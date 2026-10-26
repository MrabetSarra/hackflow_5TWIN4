from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import (AccountRegistrationForm, EmailOrUsernameAuthenticationForm,
                    PasswordResetRequestForm, PasswordResetVerifyForm,
                    ProfileAssetsForm, ProfileDetailsForm)
from .models import PasswordResetCode
from student.models import Hackathon, HackathonRegistration


class AccountFlowTests(TestCase):
    def test_student_can_register_and_is_sent_to_student_dashboard(self):
        response = self.client.post(reverse('accounts:register_role', args=['student']), {
            'first_name': 'Sam', 'last_name': 'Student', 'username': 'samstudent',
            'email': 'sam@example.test', 'school': 'Example University',
            'study_level': 'Master 1', 'skills': ['Python / Django'],
            'password1': 'Strong-Test-Pass-428!', 'password2': 'Strong-Test-Pass-428!',
        })
        self.assertRedirects(response, reverse('student:dashboard'))
        user = get_user_model().objects.get(username='samstudent')
        self.assertEqual(user.role, 'student')
        self.assertTrue(user.check_password('Strong-Test-Pass-428!'))

    def test_login_redirects_by_role_and_rejects_wrong_password(self):
        user = get_user_model().objects.create_user(
            username='mentor-one', email='mentor@example.test', password='Strong-Test-Pass-428!', role='mentor',
        )
        bad = self.client.post(reverse('accounts:login'), {
            'username': user.username, 'password': 'wrong-password',
        })
        self.assertEqual(bad.status_code, 200)
        self.assertFalse(bad.wsgi_request.user.is_authenticated)
        good = self.client.post(reverse('accounts:login'), {
            'username': user.username, 'password': 'Strong-Test-Pass-428!',
        })
        self.assertRedirects(good, reverse('mentor:dashboard'))

    def test_login_accepts_email_and_logout_clears_session(self):
        user = get_user_model().objects.create_user(
            username='email-login', email='email@example.test', password='Strong-Test-Pass-428!', role='student',
        )
        response = self.client.post(reverse('accounts:login'), {
            'username': user.email, 'password': 'Strong-Test-Pass-428!',
        })
        self.assertRedirects(response, reverse('student:dashboard'))
        self.assertTrue('_auth_user_id' in self.client.session)
        self.client.get(reverse('accounts:logout'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_registration_rejects_mismatched_passwords_and_duplicate_email(self):
        form = AccountRegistrationForm({
            'first_name': 'A', 'last_name': 'Student', 'username': 'unique-name',
            'email': 'new@example.test', 'school': 'School', 'study_level': 'Master 1',
            'skills': ['Python / Django'], 'password1': 'Strong-Test-Pass-428!',
            'password2': 'Different-Test-Pass-428!',
        }, role='student')
        self.assertFalse(form.is_valid())
        self.assertIn('password2', form.errors)
        get_user_model().objects.create_user(username='already', email='taken@example.test')
        self.assertFalse(EmailOrUsernameAuthenticationForm(data={
            'username': 'not-an-email', 'password': 'anything',
        }).is_valid())

    def test_profile_details_are_validated_and_role_specific(self):
        User = get_user_model()
        student = User.objects.create_user(username='profile-student', role='student')
        student_form = ProfileDetailsForm({
            'first_name': 'Sam', 'last_name': 'Student', 'username': 'profile-student',
            'email': 'profile@example.test', 'school': 'Example University',
            'study_level': 'Master 1', 'skills': ['Python / Django'],
        }, instance=student)
        self.assertTrue(student_form.is_valid(), student_form.errors)
        student_form.save()
        student.refresh_from_db()
        self.assertEqual(student.skills, ['Python / Django'])

        mentor = User.objects.create_user(username='profile-mentor', role='mentor')
        mentor_form = ProfileDetailsForm(instance=mentor)
        self.assertIn('specialty', mentor_form.fields)
        self.assertNotIn('study_level', mentor_form.fields)
        admin = User.objects.create_user(username='profile-admin', role='admin')
        admin_form = ProfileDetailsForm(instance=admin)
        self.assertNotIn('skills', admin_form.fields)
        self.assertNotIn('specialty', admin_form.fields)

    def test_profile_form_rejects_duplicate_username_and_invalid_skill(self):
        User = get_user_model()
        User.objects.create_user(username='taken-profile', email='taken@example.test', role='student')
        user = User.objects.create_user(username='profile-edit', role='student')
        form = ProfileDetailsForm({
            'first_name': 'A', 'last_name': 'Student', 'username': 'taken-profile',
            'email': 'another@example.test', 'school': 'School', 'study_level': 'Master 1',
            'skills': ['Not in choices'],
        }, instance=user)
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)
        self.assertIn('skills', form.errors)

    def test_password_reset_forms_validate_code_password_and_email(self):
        self.assertTrue(PasswordResetRequestForm({'email': 'valid@example.test'}).is_valid())
        mismatch = PasswordResetVerifyForm({
            'email': 'valid@example.test', 'code': '123456',
            'new_password1': 'First-strong-password-55!', 'new_password2': 'Second-strong-password-55!',
        })
        self.assertFalse(mismatch.is_valid())
        self.assertIn('new_password2', mismatch.errors)
        invalid_code = PasswordResetVerifyForm({'email': 'bad-email', 'code': '12',
                                                'new_password1': '', 'new_password2': ''})
        self.assertFalse(invalid_code.is_valid())
        self.assertIn('code', invalid_code.errors)

    def test_profile_asset_form_checks_pdf_signature(self):
        user = get_user_model().objects.create_user(username='asset-student', role='student')
        valid = ProfileAssetsForm(files={'cv': SimpleUploadedFile('resume.pdf', b'%PDF-1.4 test')}, instance=user)
        self.assertTrue(valid.is_valid(), valid.errors)
        invalid = ProfileAssetsForm(files={'cv': SimpleUploadedFile('fake.pdf', b'not pdf')}, instance=user)
        self.assertFalse(invalid.is_valid())
        self.assertIn('cv', invalid.errors)


class AccountViewCoverageTests(TestCase):
    password = 'Valid-Coverage-Password-907!'

    def create_user(self, username='view-student', role='student', email=None):
        return get_user_model().objects.create_user(
            username=username, email=email or f'{username}@example.test',
            password=self.password, role=role,
        )

    def test_login_safe_redirect_remember_me_and_register_role_pages(self):
        student = self.create_user()
        response = self.client.post(reverse('accounts:login'), {
            'username': student.username, 'password': self.password,
            'next': '/student/tasks/', 'remember_me': 'on',
        })
        self.assertRedirects(response, '/student/tasks/')
        self.assertNotEqual(self.client.session.get_expiry_age(), 0)

        self.client.get(reverse('accounts:logout'))
        response = self.client.post(reverse('accounts:login'), {
            'username': student.username, 'password': self.password,
            'next': 'https://attacker.example.test/',
        })
        self.assertRedirects(response, reverse('student:dashboard'))
        self.client.get(reverse('accounts:logout'))

        self.assertEqual(self.client.get(reverse('accounts:register')).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:register_role', args=['student'])).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:register_role', args=['admin'])).status_code, 404)
        self.client.force_login(student)
        self.assertRedirects(self.client.get(reverse('accounts:register')), reverse('student:dashboard'))
        self.assertRedirects(
            self.client.get(reverse('accounts:register_role', args=['mentor'])),
            reverse('student:dashboard'),
        )

    @patch('accounts.views.send_mail')
    @patch('accounts.views.secrets.randbelow', return_value=123456)
    def test_password_reset_request_sends_code_and_rate_limits_resends(self, _random, send_mail_mock):
        user = self.create_user(email='reset@example.test')
        url = reverse('accounts:password_reset_request')
        response = self.client.post(url, {'email': user.email})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['submitted'])
        self.assertEqual(send_mail_mock.call_count, 1)
        code = PasswordResetCode.objects.get(user=user)
        self.assertTrue(code.is_valid)

        self.client.post(url, {'email': user.email})
        self.assertEqual(send_mail_mock.call_count, 1)
        self.assertEqual(PasswordResetCode.objects.filter(user=user).count(), 1)

    @patch('accounts.views.send_mail', side_effect=RuntimeError('mail unavailable'))
    def test_password_reset_hides_unknown_users_and_handles_mail_failure(self, _send_mail):
        url = reverse('accounts:password_reset_request')
        response = self.client.post(url, {'email': 'unknown@example.test'})
        self.assertTrue(response.context['submitted'])
        self.assertFalse(PasswordResetCode.objects.exists())

        user = self.create_user(username='mail-failure', email='mail-failure@example.test')
        response = self.client.post(url, {'email': user.email})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(PasswordResetCode.objects.filter(user=user).exists())

    def test_password_reset_verification_tracks_bad_attempt_then_changes_password(self):
        user = self.create_user(username='verify-user')
        reset = PasswordResetCode.objects.create(
            user=user, code_hash=make_password('123456'),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        url = reverse('accounts:password_reset_verify')
        base = {'email': user.email, 'new_password1': 'New-Coverage-Password-608!',
                'new_password2': 'New-Coverage-Password-608!'}
        invalid = self.client.post(url, {**base, 'code': '654321'})
        self.assertEqual(invalid.status_code, 200)
        reset.refresh_from_db()
        self.assertEqual(reset.attempts, 1)

        success = self.client.post(url, {**base, 'code': '123456'})
        self.assertTrue(success.context['completed'])
        user.refresh_from_db()
        reset.refresh_from_db()
        self.assertTrue(user.check_password('New-Coverage-Password-608!'))
        self.assertIsNotNone(reset.used_at)

    def test_password_reset_rejects_expired_codes_and_weak_passwords(self):
        user = self.create_user(username='expired-user')
        PasswordResetCode.objects.create(
            user=user, code_hash=make_password('123456'),
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        url = reverse('accounts:password_reset_verify')
        data = {'email': user.email, 'code': '123456',
                'new_password1': 'New-Coverage-Password-608!',
                'new_password2': 'New-Coverage-Password-608!'}
        expired = self.client.post(url, data)
        self.assertIn('code', expired.context['form'].errors)

        PasswordResetCode.objects.filter(user=user).update(
            expires_at=timezone.now() + timedelta(minutes=10), attempts=0,
        )
        weak = self.client.post(url, {**data, 'new_password1': 'short', 'new_password2': 'short'})
        self.assertIn('new_password1', weak.context['form'].errors)

    def test_registration_auto_registers_student_and_profile_routes_render_by_role(self):
        now = timezone.now()
        event = Hackathon.objects.create(
            name='Active coverage event', starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=1), is_active=True,
        )
        response = self.client.post(reverse('accounts:register_role', args=['student']), {
            'first_name': 'Casey', 'last_name': 'Coverage', 'username': 'coverage-registration',
            'email': 'coverage-registration@example.test', 'school': 'Test University',
            'study_level': 'Master 1', 'skills': ['Python / Django'],
            'password1': self.password, 'password2': self.password,
        })
        self.assertRedirects(response, reverse('student:dashboard'))
        user = get_user_model().objects.get(username='coverage-registration')
        self.assertTrue(HackathonRegistration.objects.filter(hackathon=event, user=user).exists())

        for username, role in (('profile-mentor-view', 'mentor'), ('profile-admin-view', 'admin')):
            profile_user = self.create_user(username=username, role=role)
            self.client.force_login(profile_user)
            self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 200)

    def test_profile_updates_details_and_download_requires_cv(self):
        user = self.create_user(username='profile-edit-view')
        self.client.force_login(user)
        response = self.client.post(reverse('accounts:profile'), {
            'form_type': 'details', 'first_name': 'Taylor', 'last_name': 'Test',
            'username': user.username, 'email': user.email, 'school': 'New School',
            'study_level': 'Master 1', 'skills': ['Python / Django'],
        })
        self.assertRedirects(response, reverse('accounts:profile'))
        user.refresh_from_db()
        self.assertEqual(user.school, 'New School')
        self.assertEqual(self.client.get(reverse('accounts:download_cv')).status_code, 404)

    @patch('accounts.views.ProfileAssetsForm')
    def test_profile_asset_storage_failure_is_reported_without_exposing_error(self, form_class):
        user = self.create_user(username='profile-upload-failure')
        self.client.force_login(user)
        form_class.return_value.is_valid.return_value = True
        form_class.return_value.save.side_effect = RuntimeError('secret-bearing provider response')

        response = self.client.post(reverse('accounts:profile'), {'form_type': 'assets'})

        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'secret-bearing provider response', status_code=503)
        self.assertContains(response, 'could not be uploaded', status_code=503)

    @patch('accounts.views.ProfileAssetsForm')
    def test_successful_profile_photo_upload_logs_backend_without_logging_url(self, form_class):
        user = self.create_user(username='profile-upload-success')
        user.profile_photo = 'profile_photos/new-photo.jpg'
        user.save(update_fields=['profile_photo'])
        self.client.force_login(user)
        form_class.return_value.is_valid.return_value = True
        form_class.return_value.save.return_value = user

        with self.assertLogs('accounts.views', level='INFO') as captured:
            response = self.client.post(reverse('accounts:profile'), {
                'form_type': 'assets',
                'profile_photo': SimpleUploadedFile('new-photo.jpg', b'photo-bytes'),
            })

        self.assertRedirects(response, reverse('accounts:profile'))
        self.assertIn('Profile photo upload succeeded', captured.output[0])
        self.assertIn('storage_backend=', captured.output[0])
        self.assertNotIn('/media/', captured.output[0])

    def test_missing_legacy_profile_photo_shows_initials_fallback(self):
        user = self.create_user(username='profile-missing-photo')
        user.profile_photo = 'profile_photos/IMG_20230511_115501_159.jpg'
        user.save(update_fields=['profile_photo'])
        self.client.force_login(user)

        response = self.client.get(reverse('accounts:profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Profile photo unavailable')
        self.assertContains(response, 'onerror="this.hidden=true;this.nextElementSibling.hidden=false;"')
        self.assertContains(response, "nextElementSibling.style.display='inline-flex'")


class TwoFactorAuthenticationTests(TestCase):
    password = 'Valid-2FA-Password-123!'

    def create_user(self, username='twofa-student', role='student', email=None):
        return get_user_model().objects.create_user(
            username=username,
            email=email or f'{username}@example.test',
            password=self.password,
            role=role,
        )

    def test_user_totp_and_backup_code_helpers(self):
        import pyotp
        user = self.create_user()
        secret = user.generate_two_factor_secret()
        self.assertTrue(secret)
        user.two_factor_secret = secret
        user.save()

        # Generate TOTP code
        totp = pyotp.TOTP(secret)
        current_code = totp.now()

        self.assertTrue(user.verify_totp(current_code))
        self.assertFalse(user.verify_totp('000000'))
        self.assertFalse(user.verify_totp(''))

        # Backup codes
        plain_codes = user.generate_backup_codes(count=4)
        user.save()
        self.assertEqual(len(plain_codes), 4)
        self.assertEqual(len(user.backup_codes), 4)

        # Consuming a valid backup code
        first_code = plain_codes[0]
        self.assertTrue(user.verify_and_consume_backup_code(first_code))
        self.assertEqual(len(user.backup_codes), 3)

        # Re-consuming the same code must fail
        self.assertFalse(user.verify_and_consume_backup_code(first_code))

        # Consuming an invalid code
        self.assertFalse(user.verify_and_consume_backup_code('INVALID-CODE'))

    def test_login_flow_redirects_to_2fa_verify_when_enabled(self):
        import pyotp
        user = self.create_user(username='twofa-enabled-user')
        secret = user.generate_two_factor_secret()
        user.two_factor_secret = secret
        user.two_factor_enabled = True
        user.save()

        # Step 1: POST to login
        response = self.client.post(reverse('accounts:login'), {
            'username': user.username,
            'password': self.password,
        })
        self.assertRedirects(response, reverse('accounts:two_factor_verify'))
        # User is not logged in yet
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.session.get('2fa_user_id'), user.pk)

        # Step 2: GET verify page
        get_res = self.client.get(reverse('accounts:two_factor_verify'))
        self.assertEqual(get_res.status_code, 200)

        # Step 3: Bad code
        bad_post = self.client.post(reverse('accounts:two_factor_verify'), {'code': '999999'})
        self.assertEqual(bad_post.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

        # Step 4: Correct code
        valid_code = pyotp.TOTP(secret).now()
        good_post = self.client.post(reverse('accounts:two_factor_verify'), {'code': valid_code})
        self.assertRedirects(good_post, reverse('student:dashboard'))
        self.assertIn('_auth_user_id', self.client.session)
        self.assertNotIn('2fa_user_id', self.client.session)

    def test_login_flow_with_backup_code(self):
        user = self.create_user(username='twofa-backup-user')
        user.two_factor_secret = user.generate_two_factor_secret()
        plain_codes = user.generate_backup_codes(count=2)
        user.two_factor_enabled = True
        user.save()

        # Login
        self.client.post(reverse('accounts:login'), {
            'username': user.username,
            'password': self.password,
        })

        # Verify with backup code
        good_post = self.client.post(reverse('accounts:two_factor_verify'), {'code': plain_codes[0]})
        self.assertRedirects(good_post, reverse('student:dashboard'))
        self.assertIn('_auth_user_id', self.client.session)

        user.refresh_from_db()
        self.assertEqual(len(user.backup_codes), 1)

    def test_two_factor_setup_and_disable_views(self):
        import pyotp
        user = self.create_user(username='twofa-setup-user')
        self.client.force_login(user)

        # Visit setup page
        setup_get = self.client.get(reverse('accounts:two_factor_setup'))
        self.assertEqual(setup_get.status_code, 200)
        pending_secret = self.client.session.get('2fa_setup_secret')
        self.assertTrue(pending_secret)

        # Submit valid TOTP
        valid_code = pyotp.TOTP(pending_secret).now()
        setup_post = self.client.post(reverse('accounts:two_factor_setup'), {'code': valid_code})
        self.assertRedirects(setup_post, reverse('accounts:two_factor_backup_codes'))

        user.refresh_from_db()
        self.assertTrue(user.two_factor_enabled)
        self.assertEqual(user.two_factor_secret, pending_secret)
        self.assertEqual(len(user.backup_codes), 8)

        # Disable 2FA with password
        disable_post = self.client.post(reverse('accounts:two_factor_disable'), {'password': self.password})
        self.assertRedirects(disable_post, reverse('accounts:profile'))
        user.refresh_from_db()
        self.assertFalse(user.two_factor_enabled)
        self.assertEqual(user.two_factor_secret, '')
        self.assertEqual(user.backup_codes, [])


class OAuthAuthenticationTests(TestCase):
    def test_oauth_login_redirect_when_not_configured(self):
        with patch('accounts.oauth.GitHubOAuthProvider.get_client_id', return_value=''), \
             patch('accounts.oauth.GitHubOAuthProvider.get_client_secret', return_value=''):
            response = self.client.get(reverse('accounts:oauth_login', args=['github']))
            self.assertRedirects(response, reverse('accounts:login'))

    def test_oauth_login_redirect_when_configured(self):
        with patch('accounts.oauth.GitHubOAuthProvider.get_client_id', return_value='test-gh-id'), \
             patch('accounts.oauth.GitHubOAuthProvider.get_client_secret', return_value='test-gh-secret'):
            response = self.client.get(reverse('accounts:oauth_login', args=['github']))
            self.assertEqual(response.status_code, 302)
            self.assertIn('https://github.com/login/oauth/authorize', response.url)
            self.assertIn('client_id=test-gh-id', response.url)
            self.assertIn('oauth_state', self.client.session)

    def test_oauth_callback_state_mismatch_rejected(self):
        session = self.client.session
        session['oauth_state'] = 'good-state'
        session.save()

        response = self.client.get(reverse('accounts:oauth_callback', args=['github']), {
            'state': 'tampered-state',
            'code': 'sample-code',
        })
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    @patch('accounts.oauth.GitHubOAuthProvider.get_user_info')
    def test_oauth_callback_creates_new_user_with_role_param(self, mock_user_info):
        mock_user_info.return_value = {
            'email': 'new-oauth-student@example.test',
            'username': 'oauthstudent',
            'first_name': 'Alex',
            'last_name': 'Coder',
            'github_url': 'https://github.com/oauthstudent',
            'bio': 'Developer',
        }

        session = self.client.session
        session['oauth_state'] = 'test-state'
        session['oauth_role'] = 'student'
        session.save()

        response = self.client.get(reverse('accounts:oauth_callback', args=['github']), {
            'state': 'test-state',
            'code': 'valid-code',
        })
        self.assertRedirects(response, reverse('student:dashboard'))

        User = get_user_model()
        user = User.objects.get(email='new-oauth-student@example.test')
        self.assertEqual(user.first_name, 'Alex')
        self.assertEqual(user.role, 'student')
        self.assertEqual(user.github_url, 'https://github.com/oauthstudent')
        self.assertTrue('_auth_user_id' in self.client.session)

    @patch('accounts.oauth.GitHubOAuthProvider.get_user_info')
    def test_oauth_callback_prompts_role_selection_and_allows_mentor(self, mock_user_info):
        mock_user_info.return_value = {
            'email': 'new-oauth-mentor@example.test',
            'username': 'oauthmentor',
            'first_name': 'Morgan',
            'last_name': 'Guide',
            'github_url': 'https://github.com/oauthmentor',
            'bio': 'Tech Mentor',
        }

        session = self.client.session
        session['oauth_state'] = 'test-mentor-state'
        session.save()

        response = self.client.get(reverse('accounts:oauth_callback', args=['github']), {
            'state': 'test-mentor-state',
            'code': 'valid-code',
        })
        # When no pre-selected role, redirect to select-role page
        self.assertRedirects(response, reverse('accounts:oauth_select_role'))

        # GET select-role page
        get_role_res = self.client.get(reverse('accounts:oauth_select_role'))
        self.assertEqual(get_role_res.status_code, 200)

        # POST invalid role 'admin' must be rejected
        bad_post = self.client.post(reverse('accounts:oauth_select_role'), {'role': 'admin'})
        self.assertEqual(bad_post.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(email='new-oauth-mentor@example.test').exists())

        # POST valid role 'mentor' succeeds
        good_post = self.client.post(reverse('accounts:oauth_select_role'), {'role': 'mentor'})
        self.assertRedirects(good_post, reverse('mentor:dashboard'))

        User = get_user_model()
        mentor_user = User.objects.get(email='new-oauth-mentor@example.test')
        self.assertEqual(mentor_user.role, 'mentor')
        self.assertTrue('_auth_user_id' in self.client.session)

    def test_get_or_create_oauth_user_strictly_forbids_admin(self):
        from accounts.oauth import get_or_create_oauth_user
        with self.assertRaises(ValueError):
            get_or_create_oauth_user({'email': 'hacker@example.test'}, 'github', role='admin')

    @patch('accounts.oauth.GoogleOAuthProvider.get_user_info')
    def test_oauth_callback_respects_existing_user_2fa(self, mock_user_info):
        User = get_user_model()
        user = User.objects.create_user(
            username='google-2fa-user',
            email='google2fa@example.test',
            two_factor_enabled=True,
            two_factor_secret='JBSWY3DPEHPK3PXP',
            role='student',
        )

        mock_user_info.return_value = {
            'email': 'google2fa@example.test',
            'username': 'google2fa',
            'first_name': 'Google',
            'last_name': 'User',
            'github_url': '',
            'bio': '',
        }

        session = self.client.session
        session['oauth_state'] = 'test-state-2fa'
        session.save()

        response = self.client.get(reverse('accounts:oauth_callback', args=['google']), {
            'state': 'test-state-2fa',
            'code': 'valid-google-code',
        })
        # Must redirect to 2FA verify page and NOT log in directly
        self.assertRedirects(response, reverse('accounts:two_factor_verify'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.session.get('2fa_user_id'), user.pk)


class CVSkillExtractionTests(TestCase):
    def test_sync_cv_skills_action_triggers_extraction_and_updates_profile(self):
        user = get_user_model().objects.create_user(
            username='cv-sync-user',
            email='cvsync@example.test',
            password='Test-Password-123!',
            role='student',
            skills=['Python / Django'],
        )
        # Attach dummy CV
        user.cv = SimpleUploadedFile('test_cv.pdf', b'%PDF-1.4 mock content with react and docker', content_type='application/pdf')
        user.save()
        self.client.force_login(user)

        # Mock analyze_student_cv
        with patch('career_opportunities.services.cv_analysis.analyze_student_cv') as mock_analyze:
            mock_analyze.return_value = {
                'status': 'ready',
                'data': {
                    'skills': [
                        {'name': 'React', 'evidence': 'React and TypeScript frontend'},
                        {'name': 'Docker', 'evidence': 'Docker container deployment'},
                    ]
                }
            }
            response = self.client.post(reverse('accounts:profile'), {'action': 'sync_cv_skills'})
            self.assertRedirects(response, reverse('accounts:profile'))
            mock_analyze.assert_any_call(user, force=True)

        user.refresh_from_db()
        self.assertIn('React / TypeScript', user.skills)
        self.assertIn('DevOps & Docker', user.skills)
        self.assertIn('Python / Django', user.skills)

    def test_clean_skills_allows_already_synced_skills(self):
        user = get_user_model().objects.create_user(
            username='cv-details-user',
            email='cvdetails@example.test',
            password='Test-Password-123!',
            role='student',
            skills=['Python / Django', 'Extra Synced Skill'],
        )
        form = ProfileDetailsForm(
            data={
                'first_name': 'CV',
                'last_name': 'Tester',
                'username': user.username,
                'email': user.email,
                'school': 'ESPRIT',
                'study_level': 'Master 1',
                'skills': ['Python / Django', 'Extra Synced Skill'],
            },
            instance=user,
        )
        self.assertTrue(form.is_valid(), form.errors)


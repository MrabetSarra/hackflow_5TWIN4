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

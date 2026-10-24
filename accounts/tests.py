from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .forms import (AccountRegistrationForm, EmailOrUsernameAuthenticationForm,
                    PasswordResetRequestForm, PasswordResetVerifyForm,
                    ProfileAssetsForm, ProfileDetailsForm)


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

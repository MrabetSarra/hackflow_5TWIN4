"""Tests de sécurité et de robustesse du module hackathons."""
from datetime import timedelta

from django.contrib.auth.hashers import check_password
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.views import error_500
from student.models import Hackathon

from .models import Challenge, Favorite, HackathonProfile, Track


class SecurityBase(TestCase):
    def setUp(self):
        self.org = User.objects.create_user('sec_org', password='Str0ng-pass-987', role='organization')
        self.student = User.objects.create_user('sec_stu', password='Str0ng-pass-987', role='student')
        self.track = Track.objects.create(name='Security')
        now = timezone.now()
        event = Hackathon.objects.create(
            name='Secure Jam', starts_at=now + timedelta(days=5), ends_at=now + timedelta(days=7), is_active=False,
        )
        self.h = HackathonProfile.objects.create(
            event=event, track=self.track, status=HackathonProfile.Status.PUBLISHED,
        )
        self.challenge = Challenge.objects.create(
            hackathon=self.h, title='Safe', status=Challenge.Status.PUBLISHED,
        )


class CsrfTests(SecurityBase):
    def setUp(self):
        super().setUp()
        self.client_csrf = Client(enforce_csrf_checks=True)
        self.client_csrf.force_login(self.student)

    def test_favorite_post_without_csrf_token_is_forbidden(self):
        response = self.client_csrf.post(reverse('hackathons:favorite_toggle', args=['hackathon', self.h.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Favorite.objects.filter(user=self.student).exists())

    def test_organizer_post_without_csrf_token_is_forbidden(self):
        self.client_csrf.force_login(self.org)
        response = self.client_csrf.post(
            reverse('hackathons:hackathon_status', args=[self.h.pk]), {'action': 'unpublish'},
        )
        self.assertEqual(response.status_code, 403)
        self.h.refresh_from_db()
        self.assertEqual(self.h.status, HackathonProfile.Status.PUBLISHED)


class AccessControlTests(SecurityBase):
    def test_anonymous_post_is_redirected_to_login(self):
        response = self.client.post(reverse('hackathons:hackathon_create'), {'name': 'x'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_student_cannot_create_hackathon(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse('hackathons:hackathon_create'), {'name': 'Hack'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(HackathonProfile.objects.filter(event__name='Hack').exists())

    def test_student_cannot_publish_hackathon(self):
        self.h.status = HackathonProfile.Status.DRAFT
        self.h.save()
        self.client.force_login(self.student)
        response = self.client.post(reverse('hackathons:hackathon_status', args=[self.h.pk]), {'action': 'publish'})
        self.assertEqual(response.status_code, 403)
        self.h.refresh_from_db()
        self.assertEqual(self.h.status, HackathonProfile.Status.DRAFT)


class ErrorHandlingTests(SecurityBase):
    def test_unknown_hackathon_returns_404(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('hackathons:hackathon_detail', args=['slug-qui-nexiste-pas']))
        self.assertEqual(response.status_code, 404)

    def test_unknown_challenge_on_manage_page_returns_404(self):
        self.client.force_login(self.org)
        response = self.client.get(reverse('hackathons:challenge_manage', args=[self.h.pk, 999999]))
        self.assertEqual(response.status_code, 404)

    def test_500_handler_returns_server_error_status(self):
        request = RequestFactory().get('/')
        response = error_500(request)
        self.assertEqual(response.status_code, 500)


class InjectionAndXssTests(SecurityBase):
    def test_sql_like_track_filter_is_treated_as_text(self):
        response = self.client.get(reverse('hackathons:catalog'), {'track': '1 OR 1=1', 'q': "' OR '1'='1"})
        self.assertEqual(response.status_code, 302)  # visiteur anonyme : redirigé vers la connexion
        self.client.force_login(self.student)
        response = self.client.get(reverse('hackathons:catalog'), {'track': '1 OR 1=1', 'q': "' OR '1'='1"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Secure Jam', response.content.decode())

    def test_script_in_challenge_title_is_escaped(self):
        payload = '<script>alert(1)</script>'
        Challenge.objects.create(hackathon=self.h, title=payload, status=Challenge.Status.PUBLISHED)
        self.client.force_login(self.student)
        response = self.client.get(reverse('hackathons:hackathon_detail', args=[self.h.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, payload)
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_hackathon_detail_has_no_unescaped_user_html(self):
        self.h.short_description = '<img src=x onerror=alert(1)>'
        self.h.save()
        self.client.force_login(self.student)
        response = self.client.get(reverse('hackathons:hackathon_detail', args=[self.h.slug]))
        self.assertNotContains(response, '<img src=x onerror=alert(1)>')


class PasswordStorageTests(TestCase):
    def test_passwords_are_hashed_not_stored_in_clear(self):
        user = User.objects.create_user('hash_user', password='Str0ng-pass-987', role='student')
        self.assertNotEqual(user.password, 'Str0ng-pass-987')
        self.assertTrue(user.password.startswith('pbkdf2_') or '$' in user.password)
        self.assertTrue(check_password('Str0ng-pass-987', user.password))

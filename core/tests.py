from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


class CustomErrorPageTests(TestCase):
    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
    def test_not_found_page_links_to_the_correct_dashboard_for_logged_in_role(self):
        for role, route in (
            ('student', 'student:dashboard'), ('mentor', 'mentor:dashboard'),
            ('admin', 'dashboard_admin:dashboard'),
        ):
            user = get_user_model().objects.create_user(username=f'error-{role}', role=role)
            self.client.force_login(user)
            response = self.client.get('/missing-page-for-test/')
            self.assertEqual(response.status_code, 404)
            self.assertTemplateUsed(response, '404.html')
            self.assertContains(response, reverse(route), status_code=404)

    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
    def test_forbidden_page_uses_custom_template_and_role_dashboard(self):
        student = get_user_model().objects.create_user(username='error-forbidden-student', role='student')
        self.client.force_login(student)
        response = self.client.get(reverse('mentor:dashboard'))
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')
        self.assertContains(response, reverse('student:dashboard'), status_code=403)

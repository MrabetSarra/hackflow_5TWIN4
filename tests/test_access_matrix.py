from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class RoleAccessMatrixTests(TestCase):
    routes = {
        'student': ('student:dashboard',),
        'mentor': ('mentor:dashboard',),
        'admin': ('dashboard_admin:dashboard',),
    }

    def setUp(self):
        User = get_user_model()
        self.users = {
            role: User.objects.create_user(
                username=f'{role}-matrix', password='Strong-Test-Pass-428!', role=role,
                is_staff=(role == 'admin'),
            )
            for role in self.routes
        }

    def test_anonymous_users_are_redirected_for_every_dashboard(self):
        for route_names in self.routes.values():
            for route in route_names:
                with self.subTest(route=route):
                    response = self.client.get(reverse(route))
                    self.assertEqual(response.status_code, 302)
                    self.assertIn(reverse('accounts:login'), response.url)

    def test_each_role_can_open_only_its_own_dashboard(self):
        for role, user in self.users.items():
            self.client.force_login(user)
            for target_role, route_names in self.routes.items():
                for route in route_names:
                    with self.subTest(role=role, route=route):
                        response = self.client.get(reverse(route))
                        self.assertEqual(response.status_code, 200 if role == target_role else 403)

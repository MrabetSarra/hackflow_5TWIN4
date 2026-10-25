from unittest.mock import patch

import requests
from cloudinary.exceptions import Error as CloudinaryError, NotFound
from django.core.files.base import ContentFile
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.storage import PrivateCVStorage
from .models import Hackathon, Milestone, Submission, Team, TeamMembership


@override_settings(
    CLOUDINARY_URL='cloudinary://test-key:test-secret@test-cloud',
    ROOT_URLCONF='student.test_submission_storage_urls',
)
class SubmissionCloudinaryStorageTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.student = User.objects.create_user(username='file-owner', password='pw', role='student')
        self.mentor = User.objects.create_user(username='file-mentor', password='pw', role='mentor')
        hackathon = Hackathon.objects.create(
            name='Storage test', starts_at=now, ends_at=now + timezone.timedelta(days=3),
        )
        self.team = Team.objects.create(hackathon=hackathon, name='Storage team', captain=self.student)
        TeamMembership.objects.create(team=self.team, user=self.student, role='Captain')
        self.milestone = Milestone.objects.create(
            hackathon=hackathon, title='Submission', due_at=now + timezone.timedelta(days=1),
        )
        self.submission = Submission.objects.create(
            team=self.team, milestone=self.milestone, file='submissions/net.zip',
        )
        self.storage = PrivateCVStorage()

    def test_existing_cloudinary_file_size_uses_private_raw_authenticated_lookup(self):
        with patch('cloudinary.api.resource', return_value={'bytes': 321}) as resource:
            self.assertEqual(self.storage.size('submissions/net.zip'), 321)
        resource.assert_called_once_with(
            'submissions/net.zip', resource_type='raw', type='authenticated',
        )

    def test_missing_cloudinary_file_does_not_crash_submission_page(self):
        self.client.force_login(self.student)
        with patch('cloudinary.api.resource', side_effect=NotFound('not found')), patch(
            'student.views.render', return_value=HttpResponse('ok'),
        ) as render, patch.object(PrivateCVStorage, '_local_storage') as local_storage:
            local_storage.return_value.exists.return_value = False
            response = self.client.get(reverse('student:project_submission'))

        self.assertEqual(response.status_code, 200)
        context = render.call_args.args[2]
        self.assertTrue(context['submission']['file_missing'])
        self.assertIsNone(context['submission']['file_size'])

    def test_existing_file_metadata_is_available_to_submission_page(self):
        self.client.force_login(self.student)
        with patch('cloudinary.api.resource', return_value={'bytes': 321}), patch(
            'student.views.render', return_value=HttpResponse('ok'),
        ) as render:
            response = self.client.get(reverse('student:project_submission'))

        self.assertEqual(response.status_code, 200)
        context = render.call_args.args[2]
        self.assertEqual(context['submission']['file_size'], 321)
        self.assertFalse(context['submission']['file_missing'])

    def test_temporary_cloudinary_network_failure_is_not_reported_as_missing(self):
        with patch('cloudinary.api.resource', side_effect=requests.Timeout('temporary timeout')):
            with self.assertRaises(requests.Timeout):
                self.storage.size('submissions/net.zip')
        with patch('cloudinary.api.resource', side_effect=CloudinaryError('API authentication failure')):
            with self.assertRaises(CloudinaryError):
                self.storage.size('submissions/net.zip')

    def test_private_submission_download_remains_role_protected(self):
        factory = RequestFactory()
        denied_request = factory.get(reverse('student:download_submission', args=[self.submission.pk]))
        denied_request.user = self.student
        from .views import download_submission
        with self.assertRaises(PermissionDenied):
            download_submission(denied_request, self.submission.pk)

        allowed_request = factory.get(reverse('student:download_submission', args=[self.submission.pk]))
        allowed_request.user = self.mentor
        with patch.object(PrivateCVStorage, 'open', return_value=ContentFile(b'private zip bytes')) as open_file:
            response = download_submission(allowed_request, self.submission.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        open_file.assert_called_once_with('submissions/net.zip', 'rb')


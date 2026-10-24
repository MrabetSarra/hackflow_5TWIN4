from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .forms import MentorRequestForm, TaskForm, TeamForm
from .models import Hackathon, Milestone, Submission, Task, Team, TeamMembership


class StudentModelTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.user = get_user_model().objects.create_user(username='model-student', password='pass')
        self.hackathon = Hackathon.objects.create(
            name='Model Test Hackathon', starts_at=now, ends_at=now + timedelta(days=2),
        )
        self.team = Team.objects.create(hackathon=self.hackathon, name='Model Team', captain=self.user, max_members=1)

    def test_places_left_never_goes_below_zero(self):
        self.assertEqual(self.team.places_left, 1)
        TeamMembership.objects.create(team=self.team, user=self.user)
        self.assertEqual(self.team.places_left, 0)
        self.team.max_members = 0
        self.assertEqual(self.team.places_left, 0)

    def test_membership_and_submission_unique_constraints(self):
        member = TeamMembership.objects.create(team=self.team, user=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamMembership.objects.create(team=self.team, user=self.user)
        milestone = Milestone.objects.create(
            hackathon=self.hackathon, title='Final', due_at=timezone.now() + timedelta(days=1),
        )
        Submission.objects.create(team=self.team, milestone=milestone, submitted_by=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Submission.objects.create(team=self.team, milestone=milestone, submitted_by=self.user)

    def test_task_status_choices_validate(self):
        task = Task(team=self.team, title='Test task', status=Task.Status.IN_PROGRESS)
        task.full_clean()
        task.status = 'unknown'
        with self.assertRaises(ValidationError):
            task.full_clean()


class StudentFormValidationTests(TestCase):
    def setUp(self):
        now = timezone.now()
        user = get_user_model().objects.create_user(username='form-student')
        hackathon = Hackathon.objects.create(
            name='Form Test Hackathon', starts_at=now, ends_at=now + timedelta(days=1),
        )
        self.team = Team.objects.create(hackathon=hackathon, name='Form Team', captain=user)

    def test_team_task_and_mentor_request_forms_reject_invalid_input(self):
        self.assertFalse(TeamForm({'name': '', 'category': 'x' * 121}).is_valid())
        task_form = TaskForm({'title': '', 'description': '', 'category': '', 'assignee': '',
                              'priority': 'urgent', 'deadline': ''}, team=self.team)
        self.assertFalse(task_form.is_valid())
        request_form = MentorRequestForm({'subject': '', 'category': 'invalid', 'urgency': 'urgent',
                                          'meeting_url': 'not a url', 'description': ''})
        self.assertFalse(request_form.is_valid())

from django.core.management import call_command
from django.test import TestCase

from student.models import Announcement, Hackathon, MentorRequest, Milestone, Notification, Sprint, Task, Team, TeamMembership


class SeedDemoCommandTests(TestCase):
    def test_rerun_does_not_duplicate_or_overwrite_demo_data(self):
        call_command('seed_demo')
        team = Team.objects.get(name='EcoTrack')
        student = team.captain
        team.description = 'A student edit that the next seed must preserve.'
        team.save(update_fields=['description'])
        original_counts = (
            Hackathon.objects.count(), Team.objects.count(), TeamMembership.objects.count(),
            Milestone.objects.count(), Announcement.objects.count(), Sprint.objects.count(),
            Task.objects.count(), MentorRequest.objects.count(), Notification.objects.count(),
        )

        call_command('seed_demo')

        self.assertEqual(team.description, 'A student edit that the next seed must preserve.')
        self.assertEqual(Team.objects.get(pk=team.pk).description, team.description)
        self.assertEqual(getattr(student, 'username'), 'camille.laurent')
        self.assertEqual(original_counts, (
            Hackathon.objects.count(), Team.objects.count(), TeamMembership.objects.count(),
            Milestone.objects.count(), Announcement.objects.count(), Sprint.objects.count(),
            Task.objects.count(), MentorRequest.objects.count(), Notification.objects.count(),
        ))

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.db import IntegrityError, transaction
from unittest.mock import patch

from accounts.models import User
from .models import Hackathon, MentorRequest, Milestone, Notification, Resource, Submission, Team, TeamInvitation, TeamLeaveRequest, TeamMembership, Task

# Create your tests here.


class TasksKanbanUnknownTaskTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(username='student-one', password='password', role='student')
        now = timezone.now()
        hackathon = Hackathon.objects.create(
            name='Test Hackathon', starts_at=now, ends_at=now + timezone.timedelta(days=2),
        )
        self.team = Team.objects.create(hackathon=hackathon, name='Team One', captain=self.student)
        TeamMembership.objects.create(team=self.team, user=self.student, role='Captain')
        self.client.force_login(self.student)

    def test_editing_unknown_task_redirects_instead_of_raising(self):
        response = self.client.post(reverse('student:tasks_kanban'), {
            'action': 'edit_task', 'task_id': '999999', 'title': 'Updated title',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('student:tasks_kanban'))


class TeamManagementTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.hackathon = Hackathon.objects.create(
            name='Team Management Hackathon', starts_at=now, ends_at=now + timezone.timedelta(days=2),
        )
        self.captain = User.objects.create_user(username='team-captain', password='password', role='student')
        self.member = User.objects.create_user(username='team-member', password='password', role='student')
        self.other = User.objects.create_user(username='other-captain', password='password', role='student')
        self.mentor = User.objects.create_user(username='team-mentor', password='password', role='mentor')
        self.team = Team.objects.create(hackathon=self.hackathon, name='Original Team', captain=self.captain)
        TeamMembership.objects.create(team=self.team, user=self.captain, role='Captain')
        TeamMembership.objects.create(team=self.team, user=self.member, role='Designer')
        self.other_team = Team.objects.create(hackathon=self.hackathon, name='Other Team', captain=self.other)
        TeamMembership.objects.create(team=self.other_team, user=self.other, role='Captain')

    def post_team(self, user, data):
        self.client.force_login(user)
        return self.client.post(reverse('student:team_detail'), data, follow=True)

    def test_anonymous_is_redirected_and_mentor_is_forbidden(self):
        response = self.client.get(reverse('student:team_detail'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

        self.client.force_login(self.mentor)
        self.assertEqual(self.client.get(reverse('student:team_detail')).status_code, 403)

    def test_team_document_download_requires_team_membership(self):
        resource = Resource.objects.create(
            team=self.team, title='Private planning document',
            document='team_resources/plan.pdf', created_by=self.captain,
        )
        self.client.force_login(self.other)
        response = self.client.get(reverse('student:download_team_resource', args=[resource.pk]))
        self.assertEqual(response.status_code, 404)

    def test_team_member_downloads_team_document_through_authorized_view(self):
        resource = Resource.objects.create(
            team=self.team, title='Team notes',
            document='team_resources/notes.pdf', created_by=self.captain,
        )
        self.client.force_login(self.member)
        with patch('accounts.storage.PrivateCVStorage.open') as open_file:
            from django.core.files.base import ContentFile
            open_file.return_value = ContentFile(b'private team file')
            response = self.client.get(reverse('student:download_team_resource', args=[resource.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        open_file.assert_called_once_with(resource.document.name, 'rb')

    def test_captain_can_edit_team(self):
        response = self.post_team(self.captain, {
            'action': 'edit_team', 'name': 'Updated Team', 'category': 'Climate',
            'description': 'Updated description', 'table_number': 'T-7',
            'room': 'Room 2', 'seeking_skill': 'Backend',
        })
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, 'Updated Team', response.context['team_edit_form'].errors if response.context and 'team_edit_form' in response.context else response.content[-2000:])
        self.assertEqual(self.team.category, 'Climate')
        self.assertEqual(self.team.description, 'Updated description')
        self.assertEqual(self.team.table_number, 'T-7')
        self.assertEqual(self.team.room, 'Room 2')
        self.assertEqual(self.team.seeking_skill, 'Backend')
        self.assertEqual(response.status_code, 200)

    def test_captain_can_remove_member_and_member_is_notified(self):
        self.post_team(self.captain, {'action': 'remove_member', 'member_id': self.member.pk})
        self.assertFalse(TeamMembership.objects.filter(team=self.team, user=self.member).exists())
        self.assertTrue(Notification.objects.filter(user=self.member, title='Removed from team').exists())

    def test_captain_can_transfer_captaincy(self):
        self.post_team(self.captain, {'action': 'transfer_captain', 'member_id': self.member.pk})
        self.team.refresh_from_db()
        self.assertEqual(self.team.captain_id, self.member.pk)

    def test_captain_can_cancel_pending_invitation(self):
        invitation = TeamInvitation.objects.create(
            team=self.team, email='invite@example.com', invited_by=self.captain, token='pending-team-invite',
        )
        self.post_team(self.captain, {'action': 'cancel_invitation', 'invitation_id': invitation.pk})
        self.assertFalse(TeamInvitation.objects.filter(pk=invitation.pk).exists())

    def test_non_captain_cannot_manage_team_and_other_team_ids_are_scoped(self):
        self.post_team(self.member, {'action': 'edit_team', 'name': 'Stolen name'})
        self.post_team(self.member, {'action': 'remove_member', 'member_id': self.other.pk})
        self.post_team(self.member, {'action': 'transfer_captain', 'member_id': self.other.pk})
        self.post_team(self.member, {'action': 'cancel_invitation', 'invitation_id': '999999'})
        self.post_team(self.member, {'action': 'invite', 'email': 'new-student@example.com'})
        self.client.force_login(self.member)
        self.client.post(reverse('student:skills_matching'), {'user_id': self.other.pk})
        self.team.refresh_from_db()
        self.other_team.refresh_from_db()
        self.assertEqual(self.team.name, 'Original Team')
        self.assertEqual(self.other_team.name, 'Other Team')
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=self.member).exists())
        self.assertFalse(TeamInvitation.objects.filter(team=self.team).exists())

    def test_member_leave_confirmation_target_is_rendered(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse('student:team_detail'))
        self.assertContains(response, 'id="teamConfirmationModal"')
        self.assertContains(response, 'data-bs-target="#teamConfirmationModal"')

    def test_student_cannot_edit_task_from_another_team(self):
        task = Task.objects.create(team=self.team, title='Keep this task')
        self.client.force_login(self.other)
        for action, extra in (('edit_task', {'title': 'Changed'}), ('delete', {}), ('status', {'status': Task.Status.DONE}), ('plan_task', {})):
            self.client.post(reverse('student:tasks_kanban'), {'action': action, 'task_id': task.pk, **extra})
        task.refresh_from_db()
        self.assertEqual(task.title, 'Keep this task')
        self.assertEqual(task.status, Task.Status.TODO)

    def test_any_team_member_can_manage_own_resources_but_not_other_team_resources(self):
        own_resource = Resource.objects.create(team=self.team, created_by=self.captain, title='Own resource', url='https://example.com/own')
        other_resource = Resource.objects.create(team=self.other_team, created_by=self.other, title='Other resource', url='https://example.com/other')
        self.client.force_login(self.member)
        response = self.client.post(reverse('student:team_detail'), {
            'action': 'resource_edit', 'resource_id': own_resource.pk,
            'title': 'Updated own resource', 'url': 'https://example.com/updated', 'kind': 'other',
        })
        self.assertEqual(response.status_code, 302)
        own_resource.refresh_from_db()
        self.assertEqual(own_resource.title, 'Updated own resource')
        response = self.client.post(reverse('student:team_detail'), {'action': 'delete_resource', 'resource_id': other_resource.pk})
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Resource.objects.filter(pk=other_resource.pk).exists())

    def test_captain_with_other_members_must_transfer_before_leaving(self):
        response = self.post_team(self.captain, {'action': 'leave_team'})
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=self.captain).exists())
        self.team.refresh_from_db()
        self.assertFalse(self.team.is_archived)
        self.assertTrue(any('Transfer captaincy to another member' in str(message) for message in list(response.context.get('messages', []))))

    def test_last_member_leaving_archives_team_without_deleting_it(self):
        TeamMembership.objects.filter(team=self.team, user=self.member).delete()
        self.post_team(self.captain, {'action': 'leave_team'})
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)
        self.assertFalse(TeamMembership.objects.filter(team=self.team).exists())

    def test_member_leave_notifies_captain_and_waits_for_approval(self):
        self.post_team(self.member, {'action': 'leave_team'})
        request = TeamLeaveRequest.objects.get(team=self.team, member=self.member)
        self.assertEqual(request.status, TeamLeaveRequest.Status.PENDING)
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=self.member).exists())
        self.assertTrue(Notification.objects.filter(user=self.captain, title='Team member wants to leave').exists())

    def test_captain_approves_leave_request_and_member_is_notified(self):
        leave_request = TeamLeaveRequest.objects.create(team=self.team, member=self.member)
        self.post_team(self.captain, {'action': 'approve_leave_request', 'leave_request_id': leave_request.pk})
        leave_request.refresh_from_db()
        self.assertEqual(leave_request.status, TeamLeaveRequest.Status.APPROVED)
        self.assertFalse(TeamMembership.objects.filter(team=self.team, user=self.member).exists())
        self.assertTrue(Notification.objects.filter(user=self.member, title='Team leave request approved').exists())

    def test_captain_declines_leave_request_and_member_stays(self):
        leave_request = TeamLeaveRequest.objects.create(team=self.team, member=self.member)
        self.post_team(self.captain, {'action': 'decline_leave_request', 'leave_request_id': leave_request.pk})
        leave_request.refresh_from_db()
        self.assertEqual(leave_request.status, TeamLeaveRequest.Status.DECLINED)
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=self.member).exists())
        self.assertTrue(Notification.objects.filter(user=self.member, title='Team leave request declined').exists())

    def test_non_captain_cannot_decide_leave_request(self):
        leave_request = TeamLeaveRequest.objects.create(team=self.team, member=self.member)
        self.post_team(self.member, {'action': 'approve_leave_request', 'leave_request_id': leave_request.pk})
        leave_request.refresh_from_db()
        self.assertEqual(leave_request.status, TeamLeaveRequest.Status.PENDING)
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=self.member).exists())


class ProjectSubmissionMilestoneTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.student = User.objects.create_user(username='submitter', password='password', role='student')
        hackathon = Hackathon.objects.create(name='Submission Hackathon', starts_at=now, ends_at=now + timezone.timedelta(days=5))
        self.team = Team.objects.create(hackathon=hackathon, name='Submission Team', captain=self.student)
        TeamMembership.objects.create(team=self.team, user=self.student, role='Captain')
        self.next_milestone = Milestone.objects.create(hackathon=hackathon, title='Next milestone', due_at=now + timezone.timedelta(days=1), order=1)
        self.later_milestone = Milestone.objects.create(hackathon=hackathon, title='Later milestone', due_at=now + timezone.timedelta(days=2), order=2)
        self.past_milestone = Milestone.objects.create(hackathon=hackathon, title='Past milestone', due_at=now - timezone.timedelta(days=1), order=0)
        self.client.force_login(self.student)

    def test_default_and_query_param_select_milestone(self):
        response = self.client.get(reverse('student:project_submission'))
        self.assertEqual(response.context['selected_milestone'], self.next_milestone)
        response = self.client.get(reverse('student:project_submission'), {'milestone': self.later_milestone.pk})
        self.assertEqual(response.context['selected_milestone'], self.later_milestone)

    def test_post_saves_submission_for_selected_milestone(self):
        response = self.client.post(reverse('student:project_submission'), {
            'milestone': self.later_milestone.pk, 'action': 'draft', 'project_name': 'For later milestone',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Submission.objects.filter(team=self.team, milestone=self.later_milestone, project_name='For later milestone').exists())
        self.assertFalse(Submission.objects.filter(team=self.team, milestone=self.next_milestone).exists())

    def test_submission_after_deadline_is_locked_and_unique_per_milestone(self):
        response = self.client.post(reverse('student:project_submission'), {
            'milestone': self.past_milestone.pk, 'action': 'submit', 'project_name': 'Too late',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Submission.objects.filter(team=self.team, milestone=self.past_milestone).exists())
        Submission.objects.create(team=self.team, milestone=self.next_milestone)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Submission.objects.create(team=self.team, milestone=self.next_milestone)


class MentorRequestManagementTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.student = User.objects.create_user(username='request-owner', password='password', role='student')
        self.other_student = User.objects.create_user(username='request-other', password='password', role='student')
        hackathon = Hackathon.objects.create(name='Mentor Hackathon', starts_at=now, ends_at=now + timezone.timedelta(days=2))
        self.team = Team.objects.create(hackathon=hackathon, name='Mentor Team', captain=self.student)
        TeamMembership.objects.create(team=self.team, user=self.student, role='Captain')
        self.pending = MentorRequest.objects.create(student=self.student, team=self.team, subject='Old subject', category='UI/UX Design & User Experience', description='Old details')
        self.accepted = MentorRequest.objects.create(student=self.student, team=self.team, subject='Accepted', category='UI/UX Design & User Experience', description='Details', status=MentorRequest.Status.ACCEPTED)
        self.resolved = MentorRequest.objects.create(student=self.student, team=self.team, subject='Resolved', category='UI/UX Design & User Experience', description='Details', status=MentorRequest.Status.RESOLVED)
        self.other_request = MentorRequest.objects.create(student=self.other_student, subject='Other student request', category='UI/UX Design & User Experience', description='Details')
        self.client.force_login(self.student)

    def test_pending_request_can_be_updated_and_canceled(self):
        response = self.client.post(reverse('student:mentor_request'), {
            'action': 'update', 'request_id': self.pending.pk, 'subject': 'Updated subject',
            'category': 'UI/UX Design & User Experience', 'description': 'Updated details',
            'urgency': 'important', 'meeting_url': '',
        })
        self.assertEqual(response.status_code, 302)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.subject, 'Updated subject')
        self.assertEqual(self.pending.description, 'Updated details')
        self.client.post(reverse('student:mentor_request'), {'action': 'cancel', 'request_id': self.pending.pk})
        self.assertFalse(MentorRequest.objects.filter(pk=self.pending.pk).exists())

    def test_accepted_and_resolved_requests_are_read_only(self):
        for item in (self.accepted, self.resolved):
            response = self.client.post(reverse('student:mentor_request'), {
                'action': 'update', 'request_id': item.pk, 'subject': 'Tampered',
                'category': 'UI/UX Design & User Experience', 'description': 'Tampered', 'urgency': 'normal',
            })
            self.assertEqual(response.status_code, 302)
            item.refresh_from_db()
            self.assertNotEqual(item.subject, 'Tampered')
            self.client.post(reverse('student:mentor_request'), {'action': 'cancel', 'request_id': item.pk})
            self.assertTrue(MentorRequest.objects.filter(pk=item.pk).exists())

    def test_student_cannot_update_or_cancel_another_students_request(self):
        self.client.post(reverse('student:mentor_request'), {
            'action': 'update', 'request_id': self.other_request.pk, 'subject': 'Tampered',
            'category': 'UI/UX Design & User Experience', 'description': 'Tampered', 'urgency': 'normal',
        })
        self.other_request.refresh_from_db()
        self.assertEqual(self.other_request.subject, 'Other student request')
        self.client.post(reverse('student:mentor_request'), {'action': 'cancel', 'request_id': self.other_request.pk})
        self.assertTrue(MentorRequest.objects.filter(pk=self.other_request.pk).exists())

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from student.models import Hackathon, MentorRequest, Milestone, Notification, Submission, Team, TeamMembership

from .models import (DEFAULT_CRITERIA, Criterion, EvaluationScore, MentorAssignment, MentorEvaluation,
                     MentoringSession, RequestTriage)


def make_fixtures():
    User = get_user_model()
    now = timezone.now()
    mentor = User.objects.create_user(username='mentor-t', password='Strong-Test-Pass-428!', role='mentor')
    student = User.objects.create_user(username='student-t', password='Strong-Test-Pass-428!', role='student')
    hackathon = Hackathon.objects.create(name='HackFlow Test', starts_at=now, ends_at=now + timedelta(days=2))
    team = Team.objects.create(hackathon=hackathon, name='EcoTrack', captain=student)
    other_team = Team.objects.create(hackathon=hackathon, name='FinEd', captain=student)
    milestone = Milestone.objects.create(hackathon=hackathon, title='Final', due_at=now + timedelta(days=1))
    submission = Submission.objects.create(team=team, milestone=milestone, project_name='EcoTrack')
    return mentor, student, team, other_team, submission


class CriterionGridTests(TestCase):
    def test_default_grid_is_created_by_migrations(self):
        codes = set(Criterion.objects.values_list('code', flat=True))
        self.assertEqual(codes, {c['code'] for c in DEFAULT_CRITERIA})

    def test_default_grid_totals_100_percent(self):
        self.assertEqual(Criterion.total_weight(Criterion.Scope.JURY), 100)
        self.assertEqual(Criterion.total_weight(Criterion.Scope.MENTOR), 100)

    def test_ensure_default_grid_restores_missing_criteria(self):
        Criterion.objects.filter(code='innovation').delete()
        Criterion.ensure_default_grid()
        self.assertTrue(Criterion.objects.filter(code='innovation').exists())

    def test_ensure_default_grid_keeps_admin_changes(self):
        Criterion.objects.filter(code='technique').update(weight=40)
        Criterion.ensure_default_grid()
        self.assertEqual(Criterion.objects.get(code='technique').weight, 40)

    def test_for_scope_excludes_inactive_and_other_scope(self):
        Criterion.objects.create(code='jury_only', name='Jury', weight=10, scope=Criterion.Scope.JURY)
        Criterion.objects.filter(code='design_ux').update(is_active=False)
        mentor_codes = set(Criterion.for_scope(Criterion.Scope.MENTOR).values_list('code', flat=True))
        self.assertNotIn('jury_only', mentor_codes)
        self.assertNotIn('design_ux', mentor_codes)

    def test_weight_must_be_between_1_and_100(self):
        criterion = Criterion(code='bad', name='Bad', weight=0)
        with self.assertRaises(ValidationError):
            criterion.full_clean()


class MentorAssignmentTests(TestCase):
    def setUp(self):
        self.mentor, self.student, self.team, _, _ = make_fixtures()

    def test_mentor_team_pair_is_unique(self):
        MentorAssignment.objects.create(mentor=self.mentor, team=self.team)
        with self.assertRaises(IntegrityError):
            MentorAssignment.objects.create(mentor=self.mentor, team=self.team)

    def test_only_mentors_can_be_assigned(self):
        assignment = MentorAssignment(mentor=self.student, team=self.team)
        with self.assertRaises(ValidationError):
            assignment.full_clean()

    def test_follow_is_idempotent_and_keeps_first_source(self):
        MentorAssignment.follow(self.mentor, self.team, MentorAssignment.Source.AUTO)
        MentorAssignment.follow(self.mentor, self.team)
        self.assertEqual(MentorAssignment.objects.filter(mentor=self.mentor, team=self.team).count(), 1)
        self.assertEqual(MentorAssignment.objects.get().source, MentorAssignment.Source.AUTO)
        self.assertTrue(MentorAssignment.is_following(self.mentor, self.team))

    def test_follow_refuses_non_mentor(self):
        with self.assertRaises(ValidationError):
            MentorAssignment.follow(self.student, self.team)


class MentoringSessionTests(TestCase):
    def setUp(self):
        self.mentor, self.student, self.team, self.other_team, _ = make_fixtures()
        self.start = timezone.now() + timedelta(hours=1)

    def make_session(self, **kwargs):
        data = {'mentor': self.mentor, 'team': self.team, 'topic': 'Revue API',
                'starts_at': self.start, 'ends_at': self.start + timedelta(minutes=30)}
        data.update(kwargs)
        return MentoringSession(**data)

    def test_valid_session_passes_validation(self):
        session = self.make_session()
        session.full_clean()
        session.save()
        self.assertTrue(session.is_upcoming)

    def test_end_must_be_after_start(self):
        with self.assertRaises(ValidationError):
            self.make_session(ends_at=self.start - timedelta(minutes=5)).full_clean()

    def test_help_request_must_belong_to_same_team(self):
        request = MentorRequest.objects.create(student=self.student, team=self.other_team,
                                               subject='Bug', category='DevOps', description='...')
        with self.assertRaises(ValidationError):
            self.make_session(help_request=request).full_clean()

    def test_cancelled_session_is_not_upcoming(self):
        session = self.make_session(status=MentoringSession.Status.CANCELLED)
        session.save()
        self.assertFalse(session.is_upcoming)


class MentorEvaluationTests(TestCase):
    def setUp(self):
        self.mentor, self.student, self.team, _, self.submission = make_fixtures()
        self.evaluation = MentorEvaluation.objects.create(mentor=self.mentor, submission=self.submission)

    def score(self, code, value):
        return EvaluationScore.objects.create(
            evaluation=self.evaluation, criterion=Criterion.objects.get(code=code), score=Decimal(value))

    def test_weighted_total_on_20(self):
        for code, value in (('innovation', '5'), ('technique', '4'), ('design_ux', '3'), ('valeur_presentation', '4')):
            self.score(code, value)
        # (5 + 4 + 3 + 4) / 20 * 20 = 16
        self.assertEqual(self.evaluation.weighted_total(), Decimal('16.00'))

    def test_weighted_total_respects_weights(self):
        Criterion.objects.filter(code='innovation').update(weight=75)
        self.score('innovation', '5')
        self.score('technique', '0')
        # (1 * 75 + 0 * 25) / 100 * 20 = 15
        self.assertEqual(self.evaluation.weighted_total(), Decimal('15.00'))

    def test_weighted_total_is_none_without_scores(self):
        self.assertIsNone(self.evaluation.weighted_total())

    def test_score_cannot_exceed_criterion_max(self):
        score = EvaluationScore(evaluation=self.evaluation, criterion=Criterion.objects.get(code='technique'),
                                score=Decimal('6'))
        with self.assertRaises(ValidationError):
            score.full_clean()

    def test_one_evaluation_per_mentor_and_submission(self):
        with self.assertRaises(IntegrityError):
            MentorEvaluation.objects.create(mentor=self.mentor, submission=self.submission)

    def test_share_sets_flag_and_date(self):
        self.evaluation.share()
        self.evaluation.refresh_from_db()
        self.assertTrue(self.evaluation.is_shared)
        self.assertIsNotNone(self.evaluation.shared_at)
        self.assertEqual(self.evaluation.team, self.team)


class RequestTriageTests(TestCase):
    def setUp(self):
        _, self.student, self.team, _, _ = make_fixtures()
        self.request = MentorRequest.objects.create(student=self.student, team=self.team,
                                                    subject='Docker crash', category='DevOps', description='...')

    def test_corrections_override_suggestions(self):
        triage = RequestTriage.objects.create(
            help_request=self.request, status=RequestTriage.Status.DONE,
            suggested_category='Back-End', suggested_urgency='normal')
        self.assertEqual(triage.final_category, 'Back-End')
        triage.corrected_category = 'DevOps'
        triage.corrected_urgency = 'blocking'
        self.assertEqual(triage.final_category, 'DevOps')
        self.assertEqual(triage.final_urgency, 'blocking')


class MentorViewsTestBase(TestCase):
    def setUp(self):
        self.mentor, self.student, self.team, self.other_team, self.submission = make_fixtures()
        self.other_mentor = get_user_model().objects.create_user(
            username='mentor-2', password='Strong-Test-Pass-428!', role='mentor')
        TeamMembership.objects.create(team=self.team, user=self.student)
        self.pending = MentorRequest.objects.create(
            student=self.student, team=self.team, subject='Docker crash', category='DevOps',
            description='Le conteneur plante.', urgency=MentorRequest.Urgency.BLOCKING)
        self.client.force_login(self.mentor)

    def take(self, request_obj, user=None):
        if user:
            self.client.force_login(user)
        return self.client.post(reverse('mentor:request_take', args=[request_obj.pk]))


class MentorAccessTests(MentorViewsTestBase):
    pages = ['mentor:dashboard', 'mentor:teams_list', 'mentor:help_requests']

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        for name in self.pages:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('accounts:login'), response.url)

    def test_student_gets_403_everywhere(self):
        self.client.force_login(self.student)
        for name in self.pages:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.assertEqual(self.take(self.pending).status_code, 403)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, MentorRequest.Status.PENDING)

    def test_actions_reject_get(self):
        for name, arg in (('mentor:request_take', self.pending.pk), ('mentor:team_follow', self.team.pk)):
            with self.subTest(action=name):
                self.assertEqual(self.client.get(reverse(name, args=[arg])).status_code, 405)

    def test_unknown_team_returns_404(self):
        self.assertEqual(self.client.get(reverse('mentor:team_detail', args=[999999])).status_code, 404)


class MentorDashboardTests(MentorViewsTestBase):
    def test_dashboard_shows_real_data(self):
        start = timezone.localtime().replace(hour=23, minute=0, second=0, microsecond=0)
        MentoringSession.objects.create(mentor=self.mentor, team=self.team, topic='Point API',
                                        starts_at=start, ends_at=start + timedelta(minutes=30))
        response = self.client.get(reverse('mentor:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Docker crash')
        self.assertContains(response, 'Point API')
        self.assertEqual(response.context['pending_count'], 1)

    def test_sidebar_highlights_only_the_current_page(self):
        # « list » (catalogue des ateliers) ne doit pas activer « Sessions » par sous-chaîne de « sessions_list ».
        sessions_link = f'href="{reverse("mentor:sessions_list")}" class="nav-link-item active"'
        self.assertContains(self.client.get(reverse('mentor:sessions_list')), sessions_link)
        self.assertNotContains(self.client.get(reverse('workshops:list')), sessions_link)


class MentorTeamsTests(MentorViewsTestBase):
    def test_list_and_filter_mine(self):
        response = self.client.get(reverse('mentor:teams_list'))
        self.assertContains(response, 'EcoTrack')
        self.assertContains(response, 'FinEd')
        MentorAssignment.follow(self.mentor, self.team)
        response = self.client.get(reverse('mentor:teams_list'), {'mine': 'on'})
        self.assertContains(response, 'EcoTrack')
        self.assertNotContains(response, 'FinEd')

    def test_search(self):
        response = self.client.get(reverse('mentor:teams_list'), {'q': 'fin'})
        self.assertContains(response, 'FinEd')
        self.assertNotContains(response, 'EcoTrack')

    def test_follow_and_unfollow(self):
        self.client.post(reverse('mentor:team_follow', args=[self.team.pk]))
        self.assertTrue(MentorAssignment.is_following(self.mentor, self.team))
        self.client.post(reverse('mentor:team_unfollow', args=[self.team.pk]))
        self.assertFalse(MentorAssignment.is_following(self.mentor, self.team))

    def test_follow_ignores_external_next_url(self):
        response = self.client.post(reverse('mentor:team_follow', args=[self.team.pk]),
                                    {'next': 'https://evil.example.com/'})
        self.assertEqual(response.url, reverse('mentor:teams_list'))

    def test_team_detail(self):
        response = self.client.get(reverse('mentor:team_detail', args=[self.team.pk]))
        self.assertContains(response, 'EcoTrack')
        self.assertContains(response, 'Docker crash')


class HelpRequestActionTests(MentorViewsTestBase):
    def test_take_assigns_mentor_follows_team_and_notifies(self):
        self.take(self.pending)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, MentorRequest.Status.ACCEPTED)
        self.assertEqual(self.pending.mentor, self.mentor)
        self.assertEqual(MentorAssignment.objects.get(mentor=self.mentor, team=self.team).source,
                         MentorAssignment.Source.AUTO)
        self.assertTrue(Notification.objects.filter(user=self.student, title='Mentor en route').exists())

    def test_cannot_take_already_taken_ticket(self):
        self.take(self.pending)
        self.take(self.pending, user=self.other_mentor)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.mentor, self.mentor)

    def test_resolve_requires_note(self):
        self.take(self.pending)
        self.client.post(reverse('mentor:request_resolve', args=[self.pending.pk]), {'resolution_note': ''})
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, MentorRequest.Status.ACCEPTED)

    def test_resolve_own_ticket(self):
        self.take(self.pending)
        self.client.post(reverse('mentor:request_resolve', args=[self.pending.pk]),
                         {'resolution_note': 'Variables injectées via le fichier .env'})
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, MentorRequest.Status.RESOLVED)
        self.assertIn('.env', self.pending.resolution_note)

    def test_other_mentor_cannot_resolve_or_transfer_my_ticket(self):
        self.take(self.pending)
        self.client.force_login(self.other_mentor)
        resolve = self.client.post(reverse('mentor:request_resolve', args=[self.pending.pk]),
                                   {'resolution_note': 'Je prends ce ticket'})
        transfer = self.client.post(reverse('mentor:request_transfer', args=[self.pending.pk]),
                                    {'mentor': self.other_mentor.pk})
        self.assertEqual(resolve.status_code, 404)
        self.assertEqual(transfer.status_code, 404)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, MentorRequest.Status.ACCEPTED)
        self.assertEqual(self.pending.mentor, self.mentor)

    def test_transfer_to_other_mentor(self):
        self.take(self.pending)
        self.client.post(reverse('mentor:request_transfer', args=[self.pending.pk]),
                         {'mentor': self.other_mentor.pk})
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.mentor, self.other_mentor)
        self.assertTrue(MentorAssignment.is_following(self.other_mentor, self.team))

    def test_cannot_transfer_to_self_or_student(self):
        self.take(self.pending)
        for target in (self.mentor, self.student):
            with self.subTest(target=target.username):
                self.client.post(reverse('mentor:request_transfer', args=[self.pending.pk]), {'mentor': target.pk})
                self.pending.refresh_from_db()
                self.assertEqual(self.pending.mentor, self.mentor)

    def test_queue_views(self):
        self.assertContains(self.client.get(reverse('mentor:help_requests')), 'Docker crash')
        self.take(self.pending)
        self.assertNotContains(self.client.get(reverse('mentor:help_requests')), 'Docker crash')
        self.assertContains(self.client.get(reverse('mentor:help_requests'), {'view': 'mine'}), 'Docker crash')
        filtered = self.client.get(reverse('mentor:help_requests'), {'view': 'mine', 'urgency': 'normal'})
        self.assertNotContains(filtered, 'Docker crash')


def _dt(value):
    return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M')


class MentoringSessionViewTests(MentorViewsTestBase):
    def session_data(self, **overrides):
        start = timezone.now() + timedelta(days=1)
        data = {'team': self.team.pk, 'topic': 'Revue architecture', 'starts_at': _dt(start),
                'ends_at': _dt(start + timedelta(minutes=30)), 'meeting_url': 'https://meet.example.com/eco',
                'location': '', 'notes': ''}
        data.update(overrides)
        return data

    def make_session(self, mentor=None):
        start = timezone.now() + timedelta(days=1)
        return MentoringSession.objects.create(mentor=mentor or self.mentor, team=self.team, topic='Point',
                                               starts_at=start, ends_at=start + timedelta(minutes=30))

    def test_create_session_notifies_team_and_follows(self):
        response = self.client.post(reverse('mentor:session_create'), self.session_data())
        self.assertRedirects(response, reverse('mentor:sessions_list'))
        session = MentoringSession.objects.get()
        self.assertEqual(session.mentor, self.mentor)
        self.assertEqual(session.status, MentoringSession.Status.PLANNED)
        self.assertTrue(MentorAssignment.is_following(self.mentor, self.team))
        self.assertTrue(Notification.objects.filter(user=self.student, title='Session de mentorat planifiée').exists())

    def test_create_rejects_past_start_end_before_start_and_missing_place(self):
        past = timezone.now() - timedelta(days=1)
        start = timezone.now() + timedelta(days=1)
        cases = {
            'passé': self.session_data(starts_at=_dt(past), ends_at=_dt(past + timedelta(hours=1))),
            'fin avant début': self.session_data(ends_at=_dt(start - timedelta(hours=1))),
            'ni visio ni lieu': self.session_data(meeting_url=''),
        }
        for label, data in cases.items():
            with self.subTest(case=label):
                response = self.client.post(reverse('mentor:session_create'), data)
                self.assertEqual(response.status_code, 200)
        self.assertFalse(MentoringSession.objects.exists())

    def test_prefill_from_my_ticket(self):
        self.take(self.pending)
        response = self.client.get(reverse('mentor:session_create'), {'request': self.pending.pk})
        self.assertEqual(response.context['form'].initial['help_request'], self.pending)
        self.assertEqual(response.context['form'].initial['topic'], 'Docker crash')

    def test_update_and_list(self):
        session = self.make_session()
        data = self.session_data(topic='Nouveau sujet', status=MentoringSession.Status.CONFIRMED)
        self.client.post(reverse('mentor:session_update', args=[session.pk]), data)
        session.refresh_from_db()
        self.assertEqual(session.topic, 'Nouveau sujet')
        self.assertEqual(session.status, MentoringSession.Status.CONFIRMED)
        self.assertContains(self.client.get(reverse('mentor:sessions_list')), 'Nouveau sujet')

    def test_cancel_then_listed_in_past(self):
        session = self.make_session()
        self.client.post(reverse('mentor:session_cancel', args=[session.pk]))
        session.refresh_from_db()
        self.assertEqual(session.status, MentoringSession.Status.CANCELLED)
        self.assertNotContains(self.client.get(reverse('mentor:sessions_list')), 'Point</h2>')
        self.assertContains(self.client.get(reverse('mentor:sessions_list'), {'view': 'past'}), 'Point')

    def test_delete_requires_confirmation(self):
        session = self.make_session()
        self.assertEqual(self.client.get(reverse('mentor:session_delete', args=[session.pk])).status_code, 200)
        self.assertTrue(MentoringSession.objects.filter(pk=session.pk).exists())
        self.client.post(reverse('mentor:session_delete', args=[session.pk]))
        self.assertFalse(MentoringSession.objects.filter(pk=session.pk).exists())

    def test_other_mentor_cannot_touch_my_session(self):
        session = self.make_session()
        self.client.force_login(self.other_mentor)
        for name, method in (('mentor:session_update', 'get'), ('mentor:session_cancel', 'post'),
                             ('mentor:session_delete', 'post')):
            with self.subTest(action=name):
                response = getattr(self.client, method)(reverse(name, args=[session.pk]))
                self.assertEqual(response.status_code, 404)
        session.refresh_from_db()
        self.assertEqual(session.status, MentoringSession.Status.PLANNED)


class EvaluationViewTests(MentorViewsTestBase):
    def setUp(self):
        super().setUp()
        self.submission.status = Submission.Status.SUBMITTED
        self.submission.save()
        self.criteria = list(Criterion.for_scope(Criterion.Scope.MENTOR))

    def evaluation_data(self, scores=(5, 4, 3, 4), **overrides):
        data = {'pitch_readiness': MentorEvaluation.PitchReadiness.ON_TRACK, 'general_comment': 'Bon travail'}
        for criterion, value in zip(self.criteria, scores):
            data[f'score_{criterion.pk}'] = value
            data[f'comment_{criterion.pk}'] = ''
        data.update(overrides)
        return data

    def create(self, **kwargs):
        return self.client.post(reverse('mentor:evaluation_create', args=[self.submission.pk]),
                                self.evaluation_data(**kwargs))

    def test_submission_list_shows_note_button(self):
        response = self.client.get(reverse('mentor:submissions'))
        self.assertContains(response, reverse('mentor:evaluation_create', args=[self.submission.pk]))

    def test_draft_submission_cannot_be_evaluated(self):
        self.submission.status = Submission.Status.DRAFT
        self.submission.save()
        self.assertEqual(self.create().status_code, 404)

    def test_create_evaluation_computes_total(self):
        response = self.create()
        evaluation = MentorEvaluation.objects.get()
        self.assertRedirects(response, reverse('mentor:evaluation_detail', args=[evaluation.pk]))
        self.assertEqual(evaluation.scores.count(), 4)
        self.assertEqual(evaluation.weighted_total(), Decimal('16.00'))
        self.assertFalse(evaluation.is_shared)
        self.assertTrue(MentorAssignment.is_following(self.mentor, self.team))

    def test_score_above_max_is_rejected(self):
        response = self.create(scores=(6, 4, 3, 4))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MentorEvaluation.objects.exists())

    def test_missing_score_is_rejected(self):
        data = self.evaluation_data()
        data[f'score_{self.criteria[0].pk}'] = ''
        self.client.post(reverse('mentor:evaluation_create', args=[self.submission.pk]), data)
        self.assertFalse(MentorEvaluation.objects.exists())

    def test_second_create_redirects_to_edit(self):
        self.create()
        evaluation = MentorEvaluation.objects.get()
        response = self.client.get(reverse('mentor:evaluation_create', args=[self.submission.pk]))
        self.assertRedirects(response, reverse('mentor:evaluation_update', args=[evaluation.pk]))

    def test_update_changes_scores(self):
        self.create()
        evaluation = MentorEvaluation.objects.get()
        self.client.post(reverse('mentor:evaluation_update', args=[evaluation.pk]), self.evaluation_data(scores=(5, 5, 5, 5)))
        self.assertEqual(evaluation.weighted_total(), Decimal('20.00'))
        self.assertEqual(evaluation.scores.count(), 4)

    def test_share_notifies_team(self):
        self.create()
        evaluation = MentorEvaluation.objects.get()
        self.client.post(reverse('mentor:evaluation_share', args=[evaluation.pk]))
        evaluation.refresh_from_db()
        self.assertTrue(evaluation.is_shared)
        self.assertTrue(Notification.objects.filter(user=self.student, title='Nouveau feedback mentor').exists())

    def test_list_detail_and_delete(self):
        self.create()
        evaluation = MentorEvaluation.objects.get()
        self.assertContains(self.client.get(reverse('mentor:evaluations')), '16.00')
        self.assertContains(self.client.get(reverse('mentor:evaluation_detail', args=[evaluation.pk])), 'Bon travail')
        self.client.post(reverse('mentor:evaluation_delete', args=[evaluation.pk]))
        self.assertFalse(MentorEvaluation.objects.exists())

    def test_other_mentor_cannot_access_my_evaluation(self):
        self.create()
        evaluation = MentorEvaluation.objects.get()
        self.client.force_login(self.other_mentor)
        for name, method in (('mentor:evaluation_detail', 'get'), ('mentor:evaluation_update', 'post'),
                             ('mentor:evaluation_share', 'post'), ('mentor:evaluation_delete', 'post')):
            with self.subTest(action=name):
                response = getattr(self.client, method)(reverse(name, args=[evaluation.pk]))
                self.assertEqual(response.status_code, 404)
        self.assertTrue(MentorEvaluation.objects.filter(pk=evaluation.pk, is_shared=False).exists())

    def test_each_mentor_has_own_evaluation(self):
        self.create()
        self.client.force_login(self.other_mentor)
        self.create(scores=(1, 1, 1, 1))
        self.assertEqual(MentorEvaluation.objects.count(), 2)


class StatusBadgeTests(TestCase):
    def test_status_colors(self):
        from .templatetags.mentor_tags import status_badge
        self.assertIn('bg-success-subtle', status_badge('confirmed'))
        self.assertIn('text-danger-emphasis', status_badge('cancelled'))
        self.assertIn('bg-warning-subtle', status_badge('pending'))
        self.assertIn('bg-secondary-subtle', status_badge('inconnu'))

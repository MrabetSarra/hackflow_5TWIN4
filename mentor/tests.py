from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from student.models import Hackathon, MentorRequest, Milestone, Submission, Team

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

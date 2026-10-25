"""Tests unitaires du module hackathons : modèles, contraintes, logique métier et formulaires."""
from datetime import timedelta
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from student.models import Hackathon, Team, TeamMembership

from . import services
from .forms import ChallengeForm, HackathonForm, MentorFeedbackForm, ResourceForm, ScheduleItemForm
from .models import (
    Challenge, Favorite, FlashAnnouncement, HackathonProfile, HackathonResource, MentorFeedback,
    Registration, ScheduleItem, Track, validate_upload_size,
)


def make_event(start_in=5, length=2, name='Green Jam'):
    now = timezone.now()
    return Hackathon.objects.create(
        name=name, starts_at=now + timedelta(days=start_in),
        ends_at=now + timedelta(days=start_in + length), is_active=False,
    )


def make_profile(track, start_in=5, length=2, name='Green Jam', **kw):
    kw.setdefault('status', HackathonProfile.Status.PUBLISHED)
    return HackathonProfile.objects.create(event=make_event(start_in, length, name), track=track, **kw)


class TrackModelTests(TestCase):
    def test_slug_is_generated_from_name(self):
        track = Track.objects.create(name='IA Santé')
        self.assertEqual(track.slug, 'ia-sante')

    def test_slug_collisions_get_numbered_suffix(self):
        first = Track.objects.create(name='A-B')
        second = Track.objects.create(name='a b')
        self.assertEqual(first.slug, 'a-b')
        self.assertEqual(second.slug, 'a-b-2')

    def test_track_name_is_unique(self):
        Track.objects.create(name='Unique')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Track.objects.create(name='Unique')

    def test_keyword_list_strips_blanks(self):
        track = Track.objects.create(name='Kw', keywords=' ia, ,data ,  ')
        self.assertEqual(track.keyword_list, ['ia', 'data'])

    def test_image_extension_is_validated(self):
        track = Track(name='Bad', image=SimpleUploadedFile('script.exe', b'MZ'))
        with self.assertRaises(ValidationError) as ctx:
            track.full_clean()
        self.assertIn('image', ctx.exception.message_dict)


class UploadValidatorTests(TestCase):
    def test_file_over_5_mb_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_upload_size(SimpleNamespace(size=5 * 1024 * 1024 + 1))

    def test_file_at_limit_is_accepted(self):
        validate_upload_size(SimpleNamespace(size=5 * 1024 * 1024))


class HackathonProfileModelTests(TestCase):
    def setUp(self):
        self.track = Track.objects.create(name='Santé')

    def test_phase_follows_dates(self):
        self.assertEqual(make_profile(self.track, start_in=5, name='A').phase, 'upcoming')
        self.assertEqual(make_profile(self.track, start_in=-1, length=3, name='B').phase, 'ongoing')
        self.assertEqual(make_profile(self.track, start_in=-10, length=2, name='C').phase, 'finished')

    def test_cancelled_status_overrides_phase(self):
        h = make_profile(self.track, status=HackathonProfile.Status.CANCELLED)
        self.assertEqual(h.phase, 'cancelled')
        self.assertFalse(h.registration_open)

    def test_registration_closes_after_deadline(self):
        h = make_profile(self.track, start_in=5, registration_deadline=timezone.now() - timedelta(hours=1))
        self.assertEqual(h.current_stage, HackathonProfile.Stage.REGISTRATION_CLOSED)
        self.assertFalse(h.registration_open)

    def test_registration_open_when_published_and_before_deadline(self):
        h = make_profile(self.track, start_in=5, registration_deadline=timezone.now() + timedelta(days=1))
        self.assertTrue(h.registration_open)
        self.assertEqual(h.current_stage, HackathonProfile.Stage.REGISTRATION_OPEN)

    def test_draft_never_accepts_registrations(self):
        h = make_profile(self.track, status=HackathonProfile.Status.DRAFT)
        self.assertFalse(h.registration_open)

    def test_stage_steps_mark_done_current_todo(self):
        h = make_profile(self.track, stage=HackathonProfile.Stage.ONGOING)
        states = [step['state'] for step in h.stage_steps]
        self.assertEqual(states, ['done', 'done', 'current', 'todo', 'todo'])

    def test_one_profile_per_event(self):
        h = make_profile(self.track)
        with self.assertRaises(IntegrityError), transaction.atomic():
            HackathonProfile.objects.create(event=h.event, track=self.track)

    def test_slug_is_unique_and_generated(self):
        a = make_profile(self.track, name='Same name')
        b = make_profile(self.track, name='Same name')
        self.assertEqual(a.slug, 'same-name')
        self.assertEqual(b.slug, 'same-name-2')

    def test_max_participants_must_be_at_least_one(self):
        h = make_profile(self.track, max_participants=0)
        with self.assertRaises(ValidationError):
            h.full_clean()


class ChallengeModelTests(TestCase):
    def setUp(self):
        self.track = Track.objects.create(name='Data')
        self.h = make_profile(self.track)
        self.challenge = Challenge.objects.create(hackathon=self.h, title='Ch', status=Challenge.Status.PUBLISHED)
        self.student = User.objects.create_user('s1', password='pw-x-123456', role='student')
        self.student2 = User.objects.create_user('s2', password='pw-x-123456', role='student')

    def test_team_counts_as_one_slot(self):
        team = Team.objects.create(hackathon=self.h.event, name='T')
        for user in (self.student, self.student2):
            TeamMembership.objects.create(team=team, user=user)
            Registration.objects.create(challenge=self.challenge, user=user, team=team)
        self.assertEqual(self.challenge.slots_used, 1)

    def test_solo_students_count_one_slot_each(self):
        Registration.objects.create(challenge=self.challenge, user=self.student)
        Registration.objects.create(challenge=self.challenge, user=self.student2)
        self.assertEqual(self.challenge.slots_used, 2)

    def test_cancelled_registrations_do_not_use_slots(self):
        Registration.objects.create(challenge=self.challenge, user=self.student,
                                    status=Registration.Status.CANCELLED)
        self.assertEqual(self.challenge.slots_used, 0)

    def test_deadline_defaults_to_start_date(self):
        self.assertEqual(self.challenge.deadline, self.h.starts_at)

    def test_draft_challenge_is_not_open(self):
        draft = Challenge.objects.create(hackathon=self.h, title='Draft', status=Challenge.Status.DRAFT)
        self.assertFalse(draft.registration_open)
        self.assertTrue(self.challenge.registration_open)

    def test_technology_list_strips_blanks(self):
        ch = Challenge(technologies='python, ,django ')
        self.assertEqual(ch.technology_list, ['python', 'django'])


class ConstraintTests(TestCase):
    def setUp(self):
        self.track = Track.objects.create(name='Constraints')
        self.h = make_profile(self.track)
        self.challenge = Challenge.objects.create(hackathon=self.h, title='C1', status=Challenge.Status.PUBLISHED)
        self.user = User.objects.create_user('cu', password='pw-x-123456', role='student')
        self.mentor = User.objects.create_user('cm', password='pw-x-123456', role='mentor')

    def test_only_one_active_registration_per_challenge_and_user(self):
        Registration.objects.create(challenge=self.challenge, user=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Registration.objects.create(challenge=self.challenge, user=self.user)

    def test_cancelled_registration_can_be_repeated(self):
        Registration.objects.create(challenge=self.challenge, user=self.user, status=Registration.Status.CANCELLED)
        Registration.objects.create(challenge=self.challenge, user=self.user, status=Registration.Status.CANCELLED)
        self.assertEqual(Registration.objects.filter(user=self.user).count(), 2)

    def test_favorite_needs_exactly_one_target(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Favorite.objects.create(user=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Favorite.objects.create(user=self.user, hackathon=self.h, challenge=self.challenge)

    def test_favorite_is_unique_per_user_and_target(self):
        Favorite.objects.create(user=self.user, hackathon=self.h)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Favorite.objects.create(user=self.user, hackathon=self.h)
        Favorite.objects.create(user=self.user, challenge=self.challenge)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Favorite.objects.create(user=self.user, challenge=self.challenge)

    def test_mentor_feedback_needs_exactly_one_target(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MentorFeedback.objects.create(mentor=self.mentor, review='x')
        with self.assertRaises(IntegrityError), transaction.atomic():
            MentorFeedback.objects.create(mentor=self.mentor, hackathon=self.h, challenge=self.challenge)

    def test_mentor_feedback_rating_bounds(self):
        for bad in (0, 6):
            feedback = MentorFeedback(mentor=self.mentor, hackathon=self.h, rating=bad, review='ok')
            with self.assertRaises(ValidationError):
                feedback.full_clean()

    def test_mentor_feedback_unique_per_hackathon(self):
        MentorFeedback.objects.create(mentor=self.mentor, hackathon=self.h, review='one')
        with self.assertRaises(IntegrityError), transaction.atomic():
            MentorFeedback.objects.create(mentor=self.mentor, hackathon=self.h, review='two')


class ScheduleAndAnnouncementTests(TestCase):
    def setUp(self):
        self.track = Track.objects.create(name='Schedule')
        self.h = make_profile(self.track, start_in=-1, length=3)
        self.challenge = Challenge.objects.create(hackathon=self.h, title='S', status=Challenge.Status.PUBLISHED)

    def test_schedule_item_state(self):
        now = timezone.now()
        upcoming = ScheduleItem(challenge=self.challenge, title='a', starts_at=now + timedelta(hours=1))
        ongoing = ScheduleItem(challenge=self.challenge, title='b', starts_at=now - timedelta(minutes=5),
                               ends_at=now + timedelta(minutes=5))
        done = ScheduleItem(challenge=self.challenge, title='c', starts_at=now - timedelta(hours=2),
                            ends_at=now - timedelta(hours=1))
        self.assertEqual(upcoming.state, 'upcoming')
        self.assertEqual(ongoing.state, 'ongoing')
        self.assertEqual(done.state, 'done')

    def test_flash_announcement_active_window(self):
        now = timezone.now()
        active = FlashAnnouncement(challenge=self.challenge, message='ok', publish_at=now - timedelta(minutes=1))
        expired = FlashAnnouncement(challenge=self.challenge, message='old', publish_at=now - timedelta(hours=2),
                                    expires_at=now - timedelta(hours=1))
        future = FlashAnnouncement(challenge=self.challenge, message='later', publish_at=now + timedelta(hours=1))
        unpublished = FlashAnnouncement(challenge=self.challenge, message='draft', publish_at=now - timedelta(minutes=1),
                                        is_published=False)
        self.assertTrue(active.is_active)
        self.assertFalse(expired.is_active)
        self.assertFalse(future.is_active)
        self.assertFalse(unpublished.is_active)

    def test_resource_requires_url_or_file_in_form(self):
        form = ResourceForm(
            data={'title': 'Docs', 'category': 'docs', 'description': '', 'url': '', 'is_published': 'on'},
            challenge=self.challenge, user=None,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('url', form.errors)

    def test_resource_rejects_disallowed_extension(self):
        resource = HackathonResource(challenge=self.challenge, title='Bad',
                                     file=SimpleUploadedFile('malware.exe', b'MZ'))
        with self.assertRaises(ValidationError) as ctx:
            resource.full_clean()
        self.assertIn('file', ctx.exception.message_dict)


class FormValidationTests(TestCase):
    def setUp(self):
        self.org = User.objects.create_user('forg', password='pw-x-123456', role='organization')
        self.mentor = User.objects.create_user('fmentor', password='pw-x-123456', role='mentor')
        self.student = User.objects.create_user('fstu', password='pw-x-123456', role='student')
        self.track = Track.objects.create(name='Forms')
        self.h = make_profile(self.track, start_in=10, length=3)
        self.challenge = Challenge.objects.create(hackathon=self.h, title='Existing', status=Challenge.Status.DRAFT)

    def test_hackathon_end_must_be_after_start(self):
        start = timezone.now() + timedelta(days=5)
        form = HackathonForm(data={
            'name': 'Valid name', 'track_name': 'Forms', 'location': 'Tunis',
            'starts_at': start.strftime('%Y-%m-%d %H:%M'),
            'ends_at': (start - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'),
            'max_participants': 10,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('ends_at', form.errors)

    def test_hackathon_location_is_required(self):
        start = timezone.now() + timedelta(days=5)
        form = HackathonForm(data={
            'name': 'Valid name', 'track_name': 'Forms', 'location': '',
            'starts_at': start.strftime('%Y-%m-%d %H:%M'),
            'ends_at': (start + timedelta(days=1)).strftime('%Y-%m-%d %H:%M'),
        })
        self.assertFalse(form.is_valid())
        self.assertIn('location', form.errors)

    def test_hackathon_title_too_short_is_rejected(self):
        form = HackathonForm(data={'name': 'a', 'track_name': 'Forms'})
        form.is_valid()
        self.assertIn('name', form.errors)

    def test_duplicate_challenge_title_is_rejected(self):
        form = ChallengeForm(
            data={'title': 'existing', 'difficulty': 'beginner', 'technologies': '', 'reward': ''},
            hackathon=self.h,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('title', form.errors)

    def test_mentor_feedback_requires_review_or_ideas(self):
        form = MentorFeedbackForm(data={'rating': '4', 'review': '   ', 'ideas': ''})
        self.assertFalse(form.is_valid())

    def test_mentor_feedback_accepts_rating_with_review(self):
        form = MentorFeedbackForm(data={'rating': '4', 'review': 'Bien', 'ideas': ''})
        self.assertTrue(form.is_valid(), form.errors)

    def test_schedule_mentor_only_for_mentoring_kind(self):
        start = self.h.starts_at + timedelta(hours=1)
        form = ScheduleItemForm(
            data={'title': 'Opening', 'kind': ScheduleItem.Kind.OPENING,
                  'starts_at': start.strftime('%Y-%m-%d %H:%M'), 'ends_at': '',
                  'mentor': str(self.mentor.pk)},
            challenge=self.challenge, user=self.org,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('mentor', form.errors)

    def test_schedule_mentor_queryset_excludes_students(self):
        form = ScheduleItemForm(challenge=self.challenge, user=self.org)
        ids = set(form.fields['mentor'].queryset.values_list('pk', flat=True))
        self.assertIn(self.mentor.pk, ids)
        self.assertNotIn(self.student.pk, ids)


class ServiceBusinessRuleTests(TestCase):
    def setUp(self):
        self.track = Track.objects.create(name='Services')
        self.h = make_profile(self.track, start_in=5, length=2)
        self.ch = Challenge.objects.create(hackathon=self.h, title='Main', status=Challenge.Status.PUBLISHED)
        self.other = Challenge.objects.create(hackathon=self.h, title='Other', status=Challenge.Status.PUBLISHED)
        self.student = User.objects.create_user('svc1', password='pw-x-123456', role='student')
        self.student2 = User.objects.create_user('svc2', password='pw-x-123456', role='student')

    def test_draft_challenge_refused(self):
        draft = Challenge.objects.create(hackathon=self.h, title='Hidden', status=Challenge.Status.DRAFT)
        with self.assertRaises(services.RegistrationError):
            services.register(self.student, draft)

    def test_unpublished_hackathon_refused(self):
        self.h.status = HackathonProfile.Status.DRAFT
        self.h.save()
        with self.assertRaises(services.RegistrationError):
            services.register(self.student, self.ch)

    def test_one_challenge_per_hackathon(self):
        services.register(self.student, self.ch)
        with self.assertRaisesMessage(services.RegistrationError, 'déjà inscrit à un challenge'):
            services.register(self.student, self.other)

    def test_team_cannot_join_two_challenges(self):
        team = Team.objects.create(hackathon=self.h.event, name='Squad')
        TeamMembership.objects.create(team=team, user=self.student)
        TeamMembership.objects.create(team=team, user=self.student2)
        services.register(self.student, self.ch)
        with self.assertRaises(services.RegistrationError):
            services.register(self.student2, self.other)

    def test_capacity_counts_distinct_participants(self):
        self.h.max_participants = 1
        self.h.save()
        services.register(self.student, self.ch)
        with self.assertRaisesMessage(services.RegistrationError, 'capacité maximale'):
            services.register(self.student2, self.ch)

    def test_double_cancel_refused(self):
        reg = services.register(self.student, self.ch)
        services.cancel(reg)
        reg.refresh_from_db()
        with self.assertRaises(services.RegistrationError):
            services.cancel(reg)

    def test_team_for_returns_team_or_none(self):
        team = Team.objects.create(hackathon=self.h.event, name='Lone')
        TeamMembership.objects.create(team=team, user=self.student)
        self.assertEqual(services.team_for(self.student, self.h), team)
        self.assertIsNone(services.team_for(self.student2, self.h))

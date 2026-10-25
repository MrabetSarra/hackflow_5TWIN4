from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from student.models import Hackathon, Team, TeamMembership

from . import services
from .forms import ChallengeForm
from .models import (
    Challenge, FlashAnnouncement, HackathonProfile, Registration, ScheduleItem, Track,
)


def make_hackathon(track, name='Green Jam', status='published', start_in=5, **kw):
    now = timezone.now()
    event = Hackathon.objects.create(
        name=name, starts_at=now + timedelta(days=start_in), ends_at=now + timedelta(days=start_in + 2), is_active=False)
    return HackathonProfile.objects.create(event=event, track=track, status=status, **kw)


class Base(TestCase):
    def setUp(self):
        self.org = User.objects.create_user('org', password='x', role='organization')
        self.student = User.objects.create_user('stu', password='x', role='student')
        self.student2 = User.objects.create_user('stu2', password='x', role='student')
        self.mentor = User.objects.create_user('men', password='x', role='mentor')
        self.track = Track.objects.create(name='GreenTech')
        self.h = make_hackathon(self.track)
        self.c = Challenge.objects.create(hackathon=self.h, title='Zero waste', status='published')


KINDS = ('schedule', 'announcements', 'resources')


class AccessTests(Base):
    def test_anonymous_redirected(self):
        self.assertEqual(self.client.get(reverse('hackathons:catalog')).status_code, 302)

    def test_student_cannot_manage(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('hackathons:hackathon_list')).status_code, 403)
        self.assertEqual(self.client.post(reverse('hackathons:hackathon_status', args=[self.h.pk]), {'action': 'publish'}).status_code, 403)

    def test_mentor_cannot_manage_schedule(self):
        self.client.force_login(self.mentor)
        self.assertEqual(self.client.get(reverse('hackathons:child_create', args=[self.c.pk, 'schedule'])).status_code, 403)

    def test_organizer_pages_render(self):
        self.client.force_login(self.org)
        urls = [
            reverse('hackathons:hackathon_list'), reverse('hackathons:hackathon_create'),
            reverse('hackathons:hackathon_manage', args=[self.h.pk]),
            reverse('hackathons:hackathon_edit', args=[self.h.pk]),
            reverse('hackathons:challenge_create', args=[self.h.pk]),
            reverse('hackathons:challenge_manage', args=[self.h.pk, self.c.pk]),
            reverse('hackathons:challenge_edit', args=[self.h.pk, self.c.pk]),
        ] + [reverse('hackathons:child_create', args=[self.c.pk, k]) for k in KINDS]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_no_track_management_pages(self):
        self.client.force_login(self.org)
        for path in ('/hackathons/manage/tracks/', f'/hackathons/tracks/{self.track.slug}/'):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_public_pages_render_for_student_and_mentor(self):
        for user in (self.student, self.mentor):
            self.client.force_login(user)
            for url in (
                reverse('hackathons:catalog'), reverse('hackathons:hackathon_detail', args=[self.h.slug]),
                reverse('hackathons:challenge_detail', args=[self.c.pk]),
            ):
                self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_catalog_lists_hackathons_and_filters_by_track(self):
        make_hackathon(Track.objects.create(name='FinTech'), name='Finance Jam')
        self.client.force_login(self.student)
        response = self.client.get(reverse('hackathons:catalog'))
        self.assertContains(response, 'Green Jam')
        self.assertContains(response, 'Finance Jam')
        filtered = self.client.get(reverse('hackathons:catalog'), {'track': self.track.pk})
        self.assertContains(filtered, 'Green Jam')
        self.assertNotContains(filtered, 'Finance Jam')


class ChallengeContentTests(Base):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.other = Challenge.objects.create(hackathon=self.h, title='Other challenge', status='published')
        ScheduleItem.objects.create(challenge=self.c, title='Atelier API zero', starts_at=now + timedelta(days=5))
        FlashAnnouncement.objects.create(challenge=self.c, message='Active message', publish_at=now - timedelta(hours=1))
        FlashAnnouncement.objects.create(challenge=self.c, message='Expired message', publish_at=now - timedelta(days=2), expires_at=now - timedelta(days=1))
        FlashAnnouncement.objects.create(challenge=self.c, message='Future message', publish_at=now + timedelta(days=1))

    def test_content_is_scoped_to_each_challenge(self):
        for user in (self.student, self.mentor):
            self.client.force_login(user)
            body = self.client.get(reverse('hackathons:challenge_detail', args=[self.c.pk])).content.decode()
            self.assertIn('Atelier API zero', body)
            self.assertNotIn('Jury', body)
            self.assertNotIn('Sponsors', body)
            self.assertNotIn('Critères', body)
            self.assertIn('Active message', body)
            self.assertNotIn('Expired message', body)
            self.assertNotIn('Future message', body)
            other_body = self.client.get(reverse('hackathons:challenge_detail', args=[self.other.pk])).content.decode()
            self.assertNotIn('Atelier API zero', other_body)

    def test_hackathon_page_shows_challenges_with_tabs(self):
        self.client.force_login(self.student)
        body = self.client.get(reverse('hackathons:hackathon_detail', args=[self.h.slug])).content.decode()
        self.assertIn('Zero waste', body)
        self.assertIn('Other challenge', body)
        self.assertIn('Programme', body)
        self.assertNotIn('Filtrer les challenges', body)
        self.assertEqual(self.client.get(f'/hackathons/h/{self.h.slug}/challenges/').status_code, 404)

    def test_details_are_hidden_behind_voir_plus_and_map_comes_after_challenges(self):
        self.h.latitude, self.h.longitude = 36.8065, 10.1815
        self.h.description = 'Description cachée'
        self.h.save()
        self.client.force_login(self.student)
        body = self.client.get(reverse('hackathons:hackathon_detail', args=[self.h.slug])).content.decode()
        self.assertIn('Voir plus', body)
        self.assertLess(body.index('Green Jam'), body.index('Voir plus'))
        self.assertLess(body.index('Voir plus'), body.index('Description cachée'))
        self.assertGreater(body.index('hf-map-view'), body.index('Zero waste'))

    def test_registration_closes_automatically_after_deadline(self):
        self.assertEqual(self.h.current_stage, 'registration_open')
        self.h.registration_deadline = timezone.now() - timedelta(minutes=5)
        self.h.save()
        self.assertEqual(self.h.current_stage, 'registration_closed')
        self.assertEqual([s['state'] for s in self.h.stage_steps], ['done', 'current', 'todo', 'todo', 'todo'])
        with self.assertRaises(services.RegistrationError):
            services.register(self.student, self.c)
        self.client.force_login(self.student)
        body = self.client.get(reverse('hackathons:hackathon_detail', args=[self.h.slug])).content.decode()
        self.assertNotIn(reverse('hackathons:challenge_register', args=[self.c.pk]), body)

    def test_registration_closes_automatically_when_hackathon_started(self):
        Hackathon.objects.filter(pk=self.h.event_id).update(starts_at=timezone.now() - timedelta(hours=1))
        self.h = HackathonProfile.objects.get(pk=self.h.pk)
        self.assertEqual(self.h.current_stage, 'registration_closed')

    def test_mentor_has_no_registration_or_join_actions(self):
        self.client.force_login(self.mentor)
        body = self.client.get(reverse('hackathons:hackathon_detail', args=[self.h.slug])).content.decode()
        self.assertNotIn("S'inscrire", body)
        self.assertNotIn(reverse('hackathons:challenge_register', args=[self.c.pk]), body)
        self.assertNotIn('Inscriptions fermées', body)

    def test_student_sees_register_action(self):
        self.client.force_login(self.student)
        body = self.client.get(reverse('hackathons:hackathon_detail', args=[self.h.slug])).content.decode()
        self.assertIn("S'inscrire", body)

    def test_student_sidebar_has_my_registrations(self):
        self.client.force_login(self.student)
        body = self.client.get(reverse('hackathons:catalog')).content.decode()
        self.assertIn(reverse('hackathons:my_registrations'), body)
        self.assertIn('Mes inscriptions', body)


class VisibilityTests(Base):
    def test_draft_hidden(self):
        self.h.status = 'draft'
        self.h.save()
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('hackathons:hackathon_detail', args=[self.h.slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse('hackathons:challenge_detail', args=[self.c.pk])).status_code, 404)

    def test_unpublished_challenge_hidden(self):
        self.c.status = 'draft'
        self.c.save()
        self.client.force_login(self.mentor)
        self.assertEqual(self.client.get(reverse('hackathons:challenge_detail', args=[self.c.pk])).status_code, 404)
        body = self.client.get(reverse('hackathons:hackathon_detail', args=[self.h.slug])).content.decode()
        self.assertNotIn('Zero waste', body)


class RegistrationTests(Base):
    def test_register_and_duplicate(self):
        services.register(self.student, self.c)
        with self.assertRaises(services.RegistrationError):
            services.register(self.student, self.c)

    def test_capacity(self):
        self.h.max_participants = 1
        self.h.save()
        services.register(self.student, self.c)
        with self.assertRaises(services.RegistrationError):
            services.register(self.student2, self.c)

    def test_team_members_share_one_slot(self):
        team = Team.objects.create(hackathon=self.h.event, name='T1')
        for u in (self.student, self.student2):
            TeamMembership.objects.create(team=team, user=u)
        services.register(self.student, self.c)
        services.register(self.student2, self.c)
        self.assertEqual(self.c.slots_used, 1)

    def test_deadline_and_draft(self):
        self.h.registration_deadline = timezone.now() - timedelta(hours=1)
        self.h.save()
        with self.assertRaises(services.RegistrationError):
            services.register(self.student, self.c)
        self.h.registration_deadline = None
        self.h.save()
        self.c.status = 'draft'
        self.c.save()
        with self.assertRaises(services.RegistrationError):
            services.register(self.student, self.c)

    def test_one_challenge_per_hackathon_and_cancel_history(self):
        other = Challenge.objects.create(hackathon=self.h, title='Other', status='published')
        reg = services.register(self.student, self.c)
        with self.assertRaises(services.RegistrationError):
            services.register(self.student, other)
        services.cancel(reg)
        services.register(self.student, other)
        self.assertEqual(Registration.objects.filter(user=self.student).count(), 2)

    def test_cancel_after_start_refused(self):
        reg = services.register(self.student, self.c)
        Hackathon.objects.filter(pk=self.h.event_id).update(starts_at=timezone.now() - timedelta(hours=1))
        reg = Registration.objects.get(pk=reg.pk)
        with self.assertRaises(services.RegistrationError):
            services.cancel(reg)

    def test_register_via_view(self):
        self.client.force_login(self.student)
        url = reverse('hackathons:challenge_register', args=[self.c.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.client.post(url)
        self.assertRedirects(resp, reverse('hackathons:my_registrations'))
        self.assertContains(self.client.get(reverse('hackathons:my_registrations')), 'Zero waste')

    def test_mentor_cannot_register(self):
        self.client.force_login(self.mentor)
        self.assertEqual(self.client.post(reverse('hackathons:challenge_register', args=[self.c.pk])).status_code, 403)

    def test_cannot_cancel_other_users_registration(self):
        reg = services.register(self.student, self.c)
        self.client.force_login(self.student2)
        self.assertEqual(self.client.post(reverse('hackathons:registration_cancel', args=[reg.pk])).status_code, 404)


class AgendaTests(Base):
    def _month(self, hackathon=None):
        return timezone.localtime((hackathon or self.h).starts_at).strftime('%Y-%m')

    def test_registered_hackathon_and_program_step_appear_in_calendar(self):
        ScheduleItem.objects.create(challenge=self.c, title='Atelier agenda', starts_at=self.h.starts_at + timedelta(hours=2))
        services.register(self.student, self.c)
        self.client.force_login(self.student)
        resp = self.client.get(reverse('hackathons:my_registrations'), {'month': self._month()})
        body = resp.content.decode()
        self.assertIn('Green Jam', body)
        self.assertIn('Atelier agenda', body)
        self.assertIn(reverse('hackathons:hackathon_detail', args=[self.h.slug]), body)
        reg = Registration.objects.get()
        self.assertIn(reverse('hackathons:registration_cancel', args=[reg.pk]), body)
        self.assertEqual(len(resp.context['agenda']['weeks'][0]), 7)

    def test_cancelled_registration_not_in_calendar(self):
        reg = services.register(self.student, self.c)
        services.cancel(reg)
        self.client.force_login(self.student)
        resp = self.client.get(reverse('hackathons:my_registrations'), {'month': self._month()})
        self.assertFalse(resp.context['agenda']['has_events'])
        self.assertNotIn('data-kind="hackathon"', resp.content.decode())

    def test_other_students_registrations_are_private(self):
        services.register(self.student2, self.c)
        self.client.force_login(self.student)
        resp = self.client.get(reverse('hackathons:my_registrations'), {'month': self._month()})
        self.assertFalse(resp.context['agenda']['has_events'])

    def test_overlapping_hackathons_raise_conflict_warning(self):
        other_hackathon = make_hackathon(self.track, name='Overlap Jam', start_in=6)
        other = Challenge.objects.create(hackathon=other_hackathon, title='Overlap challenge', status='published')
        services.register(self.student, self.c)
        services.register(self.student, other)
        self.client.force_login(self.student)
        resp = self.client.get(reverse('hackathons:my_registrations'), {'month': self._month()})
        self.assertEqual(len(resp.context['agenda']['conflicts']), 1)
        self.assertContains(resp, "Conflit d'agenda")

    def test_next_up_and_navigation_and_bad_month(self):
        services.register(self.student, self.c)
        self.client.force_login(self.student)
        resp = self.client.get(reverse('hackathons:my_registrations'), {'month': 'abc'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['agenda']['next_up']['title'], 'Green Jam')
        self.assertContains(resp, 'Prochain rendez-vous')
        self.assertContains(resp, 'month=')

    def test_cancel_not_offered_once_hackathon_started(self):
        services.register(self.student, self.c)
        Hackathon.objects.filter(pk=self.h.event_id).update(starts_at=timezone.now() - timedelta(hours=1))
        self.client.force_login(self.student)
        resp = self.client.get(reverse('hackathons:my_registrations'), {'month': timezone.localtime().strftime('%Y-%m')})
        entry = next(e for week in resp.context['agenda']['weeks'] for d in week for e in d['entries'] if e['kind'] == 'hackathon')
        self.assertEqual(entry['cancel_url'], '')


class OrganizerFlowTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.org)
        self.status_url = reverse('hackathons:hackathon_status', args=[self.h.pk])

    def _payload(self, **extra):
        start = timezone.localtime() + timedelta(days=10)
        data = {
            'name': 'New Jam', 'edition': '2026', 'track_name': 'Santé numérique', 'location': 'Tunis',
            'starts_at': start.strftime('%Y-%m-%dT%H:%M'), 'ends_at': (start + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
        }
        data.update(extra)
        return data

    def test_create_hackathon_creates_track_and_inactive_event(self):
        resp = self.client.post(reverse('hackathons:hackathon_create'), self._payload())
        profile = HackathonProfile.objects.get(event__name='New Jam')
        self.assertRedirects(resp, reverse('hackathons:hackathon_manage', args=[profile.pk]))
        self.assertEqual(profile.track.name, 'Santé numérique')
        self.assertEqual(profile.status, 'draft')
        self.assertFalse(profile.event.is_active)

    def test_track_is_reused_case_insensitively(self):
        self.client.post(reverse('hackathons:hackathon_create'), self._payload(track_name='greentech'))
        self.assertEqual(Track.objects.filter(name__iexact='greentech').count(), 1)
        self.assertEqual(HackathonProfile.objects.get(event__name='New Jam').track, self.track)

    def test_track_required_and_date_validation(self):
        resp = self.client.post(reverse('hackathons:hackathon_create'), self._payload(track_name=''))
        self.assertContains(resp, 'obligatoire')
        start = timezone.localtime() + timedelta(days=10)
        resp = self.client.post(reverse('hackathons:hackathon_create'), self._payload(
            ends_at=(start - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'), starts_at=start.strftime('%Y-%m-%dT%H:%M')))
        self.assertContains(resp, 'postérieure au début')
        self.assertFalse(HackathonProfile.objects.filter(event__name='New Jam').exists())

    def test_hackathon_manage_has_only_expected_buttons(self):
        self.h.status = 'draft'
        self.h.save()
        body = self.client.get(reverse('hackathons:hackathon_manage', args=[self.h.pk])).content.decode()
        self.assertIn('Publier hackathon + challenges', body)
        self.assertIn('Publier le hackathon', body)
        self.assertIn('Supprimer', body)
        self.assertNotIn('Archiver', body)
        self.assertNotIn('Annuler', body)

    def test_published_hackathon_shows_unpublish_only(self):
        body = self.client.get(reverse('hackathons:hackathon_manage', args=[self.h.pk])).content.decode()
        self.assertIn('Dépublier', body)
        self.assertNotIn('Publier le hackathon', body)

    def test_unpublish_reverts_challenges_to_draft(self):
        archived = Challenge.objects.create(hackathon=self.h, title='Old', status='archived')
        self.client.post(self.status_url, {'action': 'unpublish'})
        self.h.refresh_from_db()
        self.c.refresh_from_db()
        archived.refresh_from_db()
        self.assertEqual(self.h.status, 'draft')
        self.assertEqual(self.c.status, 'draft')
        self.assertEqual(archived.status, 'archived')

    def test_publish_only_keeps_challenges_draft(self):
        self.h.status = 'draft'
        self.h.save()
        self.c.status = 'draft'
        self.c.save()
        self.client.post(self.status_url, {'action': 'publish'})
        self.h.refresh_from_db()
        self.c.refresh_from_db()
        self.assertEqual(self.h.status, 'published')
        self.assertEqual(self.c.status, 'draft')

    def test_publish_all_publishes_draft_challenges(self):
        self.h.status = 'draft'
        self.h.save()
        draft = Challenge.objects.create(hackathon=self.h, title='Draft challenge', status='draft')
        archived = Challenge.objects.create(hackathon=self.h, title='Archived challenge', status='archived')
        self.client.post(self.status_url, {'action': 'publish_all'})
        self.h.refresh_from_db()
        draft.refresh_from_db()
        archived.refresh_from_db()
        self.assertEqual(self.h.status, 'published')
        self.assertEqual(draft.status, 'published')
        self.assertEqual(archived.status, 'archived')

    def test_single_challenge_publish_toggle(self):
        url = reverse('hackathons:challenge_status', args=[self.h.pk, self.c.pk])
        self.client.post(url, {'action': 'unpublish'})
        self.c.refresh_from_db()
        self.assertEqual(self.c.status, 'draft')
        self.client.post(url, {'action': 'publish'})
        self.c.refresh_from_db()
        self.assertEqual(self.c.status, 'published')

    def test_challenge_with_registration_cannot_be_deleted(self):
        services.register(self.student, self.c)
        self.client.post(reverse('hackathons:challenge_delete', args=[self.h.pk, self.c.pk]))
        self.assertTrue(Challenge.objects.filter(pk=self.c.pk).exists())

    def test_hackathon_with_registrations_cannot_be_deleted(self):
        services.register(self.student, self.c)
        self.client.post(reverse('hackathons:hackathon_delete', args=[self.h.pk]))
        self.assertTrue(HackathonProfile.objects.filter(pk=self.h.pk).exists())

    def test_hackathon_without_registration_deleted_with_event(self):
        event_id = self.h.event_id
        self.client.post(reverse('hackathons:hackathon_delete', args=[self.h.pk]))
        self.assertFalse(Hackathon.objects.filter(pk=event_id).exists())

    def test_create_challenge(self):
        resp = self.client.post(reverse('hackathons:challenge_create', args=[self.h.pk]), {
            'title': 'Smart grid', 'difficulty': 'advanced',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Challenge.objects.filter(title='Smart grid', hackathon=self.h, status='draft').exists())

    def test_add_content_to_challenge(self):
        start = (timezone.now() + timedelta(days=5)).astimezone().strftime('%Y-%m-%dT%H:%M')
        self.client.post(reverse('hackathons:child_create', args=[self.c.pk, 'schedule']), {
            'title': 'Ouverture', 'kind': 'opening', 'starts_at': start,
        })
        item = ScheduleItem.objects.get(challenge=self.c, title='Ouverture')
        self.client.post(reverse('hackathons:child_delete', args=[self.c.pk, 'schedule', item.pk]))
        self.assertFalse(ScheduleItem.objects.filter(pk=item.pk).exists())
        for kind in ('jury', 'sponsors', 'criteria'):
            self.assertEqual(self.client.get(reverse('hackathons:child_create', args=[self.c.pk, kind])).status_code, 404)

    def test_admin_sets_stage_and_everyone_sees_stepper_states(self):
        resp = self.client.post(reverse('hackathons:hackathon_stage', args=[self.h.pk]), {'stage': 'ongoing'})
        self.assertRedirects(resp, reverse('hackathons:hackathon_manage', args=[self.h.pk]))
        self.h.refresh_from_db()
        self.assertEqual(self.h.stage, 'ongoing')
        states = [s['state'] for s in self.h.stage_steps]
        self.assertEqual(states, ['done', 'done', 'current', 'todo', 'todo'])
        for user in (self.student, self.mentor):
            self.client.force_login(user)
            body = self.client.get(reverse('hackathons:hackathon_detail', args=[self.h.slug])).content.decode()
            self.assertIn('hf-step done', body)
            self.assertIn('hf-step current', body)
            self.assertIn('hf-step todo', body)
            self.assertIn('Inscriptions closes', body)
            self.assertNotIn(reverse('hackathons:hackathon_stage', args=[self.h.pk]), body)

    def test_invalid_stage_rejected_and_student_cannot_change(self):
        url = reverse('hackathons:hackathon_stage', args=[self.h.pk])
        self.assertEqual(self.client.post(url, {'stage': 'nope'}).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(url, {'stage': 'finished'}).status_code, 403)

    def test_manage_page_has_clickable_stepper(self):
        body = self.client.get(reverse('hackathons:hackathon_manage', args=[self.h.pk])).content.decode()
        self.assertIn(reverse('hackathons:hackathon_stage', args=[self.h.pk]), body)

    def test_registration_requires_open_registration_stage(self):
        self.h.stage = 'registration_closed'
        self.h.save()
        with self.assertRaises(services.RegistrationError):
            services.register(self.student, self.c)
        self.h.stage = 'registration_open'
        self.h.save()
        services.register(self.student, self.c)

    def test_map_coordinates_saved_and_shown_to_students_and_mentors(self):
        resp = self.client.post(reverse('hackathons:hackathon_create'), self._payload(latitude='36.806500', longitude='10.181500'))
        profile = HackathonProfile.objects.get(event__name='New Jam')
        self.assertEqual(resp.status_code, 302)
        self.assertAlmostEqual(profile.latitude, 36.8065)
        profile.status = 'published'
        profile.save()
        for user in (self.student, self.mentor):
            self.client.force_login(user)
            body = self.client.get(reverse('hackathons:hackathon_detail', args=[profile.slug])).content.decode()
            self.assertIn('hf-map-view', body)
            self.assertIn('36.806500', body)

    def test_map_coordinates_validation(self):
        resp = self.client.post(reverse('hackathons:hackathon_create'), self._payload(latitude='120', longitude='10'))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(reverse('hackathons:hackathon_create'), self._payload(latitude='36.5'))
        self.assertContains(resp, 'point complet')
        self.assertFalse(HackathonProfile.objects.filter(event__name='New Jam').exists())

    def test_hackathon_form_has_map_picker(self):
        body = self.client.get(reverse('hackathons:hackathon_create')).content.decode()
        self.assertIn('hf-map', body)
        self.assertIn('id_latitude', body)
        self.assertEqual(body.count('id="id_location"'), 1)
        self.assertNotIn('Localisation sur la carte', body)
        self.assertIn('tile.openstreetmap.fr', body)
        self.assertNotIn('cartocdn', body)

    def test_announcement_accepts_ambiguous_dst_time(self):
        resp = self.client.post(reverse('hackathons:child_create', args=[self.c.pk, 'announcements']), {
            'message': 'Changement de salle', 'level': 'info', 'publish_at': '2026-10-25T02:32',
            'expires_at': '2026-10-26T10:00', 'is_published': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(FlashAnnouncement.objects.filter(challenge=self.c, message='Changement de salle').exists())

    def test_hackathon_and_challenge_forms_have_no_removed_fields(self):
        body = self.client.get(reverse('hackathons:hackathon_create')).content.decode()
        self.assertNotIn('participation en ligne', body)
        body = self.client.get(reverse('hackathons:challenge_create', args=[self.h.pk])).content.decode()
        self.assertNotIn('Catégorie', body)
        self.assertNotIn("Date limite d'inscription", body)

    def test_new_track_appears_in_filters_for_all_roles(self):
        self.client.post(reverse('hackathons:hackathon_create'), self._payload(track_name='Cybersécurité'))
        profile = HackathonProfile.objects.get(event__name='New Jam')
        self.assertContains(self.client.get(reverse('hackathons:hackathon_list')), 'Cybersécurité')
        profile.status = 'published'
        profile.save()
        for user in (self.student, self.mentor):
            self.client.force_login(user)
            self.assertContains(self.client.get(reverse('hackathons:catalog')), 'Cybersécurité')

    def test_filters(self):
        make_hackathon(Track.objects.create(name='FinTech'), name='Draft Jam', status='draft')
        resp = self.client.get(reverse('hackathons:hackathon_list'), {'status': 'draft'})
        self.assertContains(resp, 'Draft Jam')
        self.assertNotContains(resp, 'Green Jam')
        resp = self.client.get(reverse('hackathons:hackathon_list'), {'track': self.track.pk})
        self.assertContains(resp, 'Green Jam')
        self.assertNotContains(resp, 'Draft Jam')


class FormTests(Base):
    def test_student_registered_in_hackathon_cannot_pick_second_challenge_in_ui(self):
        other = Challenge.objects.create(hackathon=self.h, title='Second pick', status='published')
        services.register(self.student, self.c)
        self.client.force_login(self.student)
        body = self.client.get(reverse('hackathons:hackathon_detail', args=[self.h.slug])).content.decode()
        self.assertIn('Un seul challenge par hackathon', body)
        self.assertNotIn(reverse('hackathons:challenge_register', args=[other.pk]), body)
        with self.assertRaises(services.RegistrationError):
            services.register(self.student, other)

    def test_status_filter_has_no_archived_option(self):
        self.client.force_login(self.org)
        body = self.client.get(reverse('hackathons:hackathon_list')).content.decode()
        self.assertNotIn('Archiv', body)
        self.assertIn('Brouillon', body)
        self.assertIn('Publi', body)

    def test_challenge_and_hackathon_forms_have_no_capacity_or_theme_fields(self):
        challenge_form = ChallengeForm(hackathon=self.h)
        self.assertNotIn('max_teams', challenge_form.fields)
        self.client.force_login(self.org)
        body = self.client.get(reverse('hackathons:hackathon_create')).content.decode()
        self.assertNotIn('id_theme', body)
        self.assertIn('id_max_participants', body)
        body = self.client.get(reverse('hackathons:challenge_create', args=[self.h.pk])).content.decode()
        self.assertNotIn('id_max_teams', body)

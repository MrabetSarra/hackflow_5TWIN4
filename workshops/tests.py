"""
workshops/tests.py
==================
15 tests couvrant P2 → P6 :

 1.  Création d'atelier par admin → OK
 2.  Création par étudiant → 403
 3.  Validation ends_at > starts_at
 4.  Mode onsite exige une salle
 5.  Réservation simple → confirmed + seat_number
 6.  Atelier complet → waiting
 7.  Double réservation → refus (400/redirect + message)
 8.  Conflit d'horaire → refus
 9.  Annulation → promotion du premier en waiting
10.  Lien online non réservé → non exposé dans la réponse
11.  Check-in → attended + certificat créé
12.  Page /verify/ valide un code
13.  Code inexistant → context cert=None
14.  recommend() retourne un score décroissant
15.  Badge débloqué au 1er certificat
 16.  Double annulation → pas de double promotion
 17.  Tri du catalogue par note
 18.  Un étudiant ne peut pas valider sa propre présence
 19.  Atelier passé → réservation impossible
 20.  Atelier à venir → compte à rebours affiché
 21.  Atelier commencé → réservation impossible
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Badge, BadgeAward, Booking, Certificate, Workshop
from .services.badges import ensure_badges_exist

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures communes
# ---------------------------------------------------------------------------

def _make_user(username, role='student', **kwargs):
    u = User.objects.create_user(
        username=username,
        password='Test1234!',
        first_name='Test',
        last_name=username.capitalize(),
        email=f'{username}@test.com',
        role=role,
        **kwargs,
    )
    return u


def _form_datetime(days=7, hour=10):
    """Date future stable pour les formulaires.

    On évite volontairement les heures proches de 02:00-03:00 : lors du
    changement d'heure, une heure locale peut être ambiguë ou inexistante,
    ce qui rendrait le test dépendant de la date d'exécution.
    """
    value = timezone.localtime(timezone.now()) + timedelta(days=days)
    return value.replace(
        hour=hour, minute=0, second=0, microsecond=0,
    ).strftime('%Y-%m-%dT%H:%M')


def _make_workshop(created_by, mode='onsite', capacity=5,
                   starts_offset_h=2, duration_h=2, **kwargs):
    now = timezone.now()
    return Workshop.objects.create(
        title=kwargs.pop('title', 'Atelier Test'),
        description='Desc',
        speaker_name='Speaker',
        mode=mode,
        room='B12' if mode == 'onsite' else '',
        meeting_url='https://zoom.us/j/test' if mode == 'online' else '',
        starts_at=now + timedelta(hours=starts_offset_h),
        ends_at=now + timedelta(hours=starts_offset_h + duration_h),
        capacity=capacity,
        is_open=True,
        created_by=created_by,
        topic_tags=['Python', 'Django'],
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class WorkshopCrudTests(TestCase):


    def setUp(self):
        self.admin   = _make_user('admin_user',   role='admin')
        self.student = _make_user('student_user', role='student',
                                  skills=['Python', 'Docker'],
                                  specialty='Backend')
        self.client  = Client()

    # ------------------------------------------------------------------
    # Test 1 — Création par admin → OK
    # ------------------------------------------------------------------
    def test_01_admin_can_create_workshop(self):
        self.client.login(username='admin_user', password='Test1234!')
        response = self.client.post(reverse('workshops:create'), {
            'title':       'Workshop Django',
            'description': 'Learn Django',
            'speaker_name': 'Alice',
            'mode':        'onsite',
            'room':        'A01',
            'level':       'beginner',
            'starts_at':   _form_datetime(hour=10),
            'ends_at':     _form_datetime(hour=12),
            'capacity':    20,
            'is_open':     'on',
        })
        self.assertEqual(Workshop.objects.count(), 1)
        ws = Workshop.objects.first()
        self.assertRedirects(response, reverse('workshops:detail',
                                               kwargs={'slug': ws.slug}))

    # ------------------------------------------------------------------
    # Test 2 — Création par étudiant → 403
    # ------------------------------------------------------------------
    def test_02_student_cannot_create_workshop(self):
        self.client.login(username='student_user', password='Test1234!')
        response = self.client.post(reverse('workshops:create'), {
            'title':       'Atelier pirate',
            'description': 'desc',
            'speaker_name': 'Bob',
            'mode':        'onsite',
            'room':        'A01',
            'level':       'beginner',
            'starts_at':   _form_datetime(hour=10),
            'ends_at':     _form_datetime(hour=12),
            'capacity':    10,
            'is_open':     'on',
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Workshop.objects.count(), 0)

    # ------------------------------------------------------------------
    # Test 3 — Validation ends_at > starts_at
    # ------------------------------------------------------------------
    def test_03_ends_before_starts_invalid(self):
        from .forms import WorkshopForm
        form = WorkshopForm(data={
            'title':       'Bad dates',
            'description': 'desc',
            'speaker_name': 'Alice',
            'mode':        'onsite',
            'room':        'A01',
            'level':       'beginner',
            'starts_at':   _form_datetime(hour=12),
            'ends_at':     _form_datetime(hour=10),
            'capacity':    10,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('ends_at', form.errors)

    # ------------------------------------------------------------------
    # Test 4 — Mode onsite sans salle → invalide
    # ------------------------------------------------------------------
    def test_04_onsite_requires_room(self):
        from .forms import WorkshopForm
        form = WorkshopForm(data={
            'title':       'Sans salle',
            'description': 'desc',
            'speaker_name': 'Alice',
            'mode':        'onsite',
            'room':        '',          # manquant
            'level':       'beginner',
            'starts_at':   _form_datetime(hour=10),
            'ends_at':     _form_datetime(hour=12),
            'capacity':    10,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('room', form.errors)

    # ------------------------------------------------------------------
    # Test 5 — Réservation simple → confirmed + seat_number attribué
    # ------------------------------------------------------------------
    def test_05_booking_confirmed_with_seat(self):
        ws = _make_workshop(self.admin, capacity=10)
        self.client.login(username='student_user', password='Test1234!')
        self.client.post(reverse('workshops:book', kwargs={'pk': ws.pk}))
        booking = Booking.objects.get(workshop=ws, user=self.student)
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertIsNotNone(booking.seat_number)
        self.assertGreaterEqual(booking.seat_number, 1)

    # ------------------------------------------------------------------
    # Test 6 — Atelier complet → waiting
    # ------------------------------------------------------------------
    def test_06_full_workshop_creates_waitlist(self):
        # capacity=1 et déjà une réservation
        ws = _make_workshop(self.admin, capacity=1)
        other = _make_user('other_student', role='student')
        Booking.objects.create(
            workshop=ws, user=other,
            status=Booking.Status.CONFIRMED,
            seat_number=1,
        )
        self.client.login(username='student_user', password='Test1234!')
        self.client.post(reverse('workshops:book', kwargs={'pk': ws.pk}))
        booking = Booking.objects.get(workshop=ws, user=self.student)
        self.assertEqual(booking.status, Booking.Status.WAITING)
        self.assertIsNone(booking.seat_number)

    # ------------------------------------------------------------------
    # Test 7 — Double réservation refusée (UniqueConstraint)
    # ------------------------------------------------------------------
    def test_07_double_booking_refused(self):
        ws = _make_workshop(self.admin, capacity=10)
        self.client.login(username='student_user', password='Test1234!')
        # Première réservation
        self.client.post(reverse('workshops:book', kwargs={'pk': ws.pk}))
        # Deuxième tentative
        response = self.client.post(
            reverse('workshops:book', kwargs={'pk': ws.pk}),
            follow=True,
        )
        # Toujours un seul booking
        self.assertEqual(
            Booking.objects.filter(workshop=ws, user=self.student).count(), 1
        )
        # Message d'avertissement dans les messages
        messages_list = list(response.context['messages'])
        has_warning = any(
            'déjà réservé' in str(m).lower() or
            'already' in str(m).lower()
            for m in messages_list
        )
        self.assertTrue(has_warning)

    # ------------------------------------------------------------------
    # Test 8 — Conflit d'horaire refusé
    # ------------------------------------------------------------------
    def test_08_schedule_conflict_refused(self):
        now = timezone.now()
        # Atelier 1 déjà réservé : 10h00 → 12h00
        ws1 = Workshop.objects.create(
            title='WS Conflit A', description='d', speaker_name='S',
            mode='onsite', room='A1',
            starts_at=now + timedelta(hours=2),
            ends_at=now + timedelta(hours=4),
            capacity=10, is_open=True, created_by=self.admin,
        )
        Booking.objects.create(
            workshop=ws1, user=self.student,
            status=Booking.Status.CONFIRMED, seat_number=1,
        )
        # Atelier 2 qui chevauche : 11h00 → 13h00
        ws2 = Workshop.objects.create(
            title='WS Conflit B', description='d', speaker_name='S',
            mode='onsite', room='B1',
            starts_at=now + timedelta(hours=3),
            ends_at=now + timedelta(hours=5),
            capacity=10, is_open=True, created_by=self.admin,
        )
        self.client.login(username='student_user', password='Test1234!')
        response = self.client.post(
            reverse('workshops:book', kwargs={'pk': ws2.pk}),
            follow=True,
        )
        self.assertFalse(
            Booking.objects.filter(workshop=ws2, user=self.student).exists()
        )
        messages_list = list(response.context['messages'])
        has_conflict = any('conflit' in str(m).lower() for m in messages_list)
        self.assertTrue(has_conflict)

    # ------------------------------------------------------------------
    # Test 9 — Annulation → promotion du premier en waiting
    # ------------------------------------------------------------------
    def test_09_cancel_promotes_first_waiting(self):
        ws = _make_workshop(self.admin, capacity=1)
        waiting_user = _make_user('waiting_student', role='student')

        # 1 place confirmée → student
        Booking.objects.create(
            workshop=ws, user=self.student,
            status=Booking.Status.CONFIRMED, seat_number=1,
        )
        # waiting_user en attente
        w_booking = Booking.objects.create(
            workshop=ws, user=waiting_user,
            status=Booking.Status.WAITING,
        )

        self.client.login(username='student_user', password='Test1234!')
        self.client.post(reverse('workshops:cancel', kwargs={'pk': ws.pk}))

        # Le booking student est annulé
        b_student = Booking.objects.get(workshop=ws, user=self.student)
        self.assertEqual(b_student.status, Booking.Status.CANCELLED)

        # waiting_user promu
        w_booking.refresh_from_db()
        self.assertEqual(w_booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(w_booking.seat_number, 1)

    # ------------------------------------------------------------------
    # Test 10 — Lien online non réservé → non exposé dans la réponse
    # ------------------------------------------------------------------
    def test_10_online_link_hidden_if_not_booked(self):
        ws = _make_workshop(self.admin, mode='online')
        # On s'assure que le meeting_url est bien défini sur l'atelier
        ws.meeting_url = 'https://zoom.us/j/SECRET123'
        ws.save(update_fields=['meeting_url'])
        self.client.login(username='student_user', password='Test1234!')
        response = self.client.get(
            reverse('workshops:detail', kwargs={'slug': ws.slug})
        )
        self.assertEqual(response.status_code, 200)
        # Le lien Zoom ne doit PAS apparaître dans la réponse HTML
        self.assertNotContains(response, 'SECRET123')
        # Et pas dans le contexte non plus
        self.assertIsNone(response.context.get('meeting_url'))

    # ------------------------------------------------------------------
    # Test 11 — Check-in → attended + certificat créé
    # ------------------------------------------------------------------
    def test_11_checkin_creates_certificate(self):
        ws = _make_workshop(self.admin, capacity=10)
        booking = Booking.objects.create(
            workshop=ws, user=self.student,
            status=Booking.Status.CONFIRMED, seat_number=1,
        )
        self.client.login(username='admin_user', password='Test1234!')
        url = reverse('workshops:checkin',
                      kwargs={'pk': ws.pk, 'token': booking.checkin_token})

        # GET = page de confirmation, aucun changement d'état.
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Confirmer la présence')
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

        # POST = validation réelle.
        response = self.client.post(url, follow=True)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.ATTENDED)
        self.assertIsNotNone(booking.attended_at)
        self.assertTrue(
            Certificate.objects.filter(workshop=ws, user=self.student).exists()
        )

    # ------------------------------------------------------------------
    # Test 12 — Page /verify/ valide un code existant non révoqué
    # ------------------------------------------------------------------
    def test_12_verify_valid_certificate(self):
        ws = _make_workshop(self.admin, capacity=10)
        cert = Certificate.objects.create(
            workshop=ws, user=self.student,
            hours=2.0, is_revoked=False,
        )
        # Public : pas besoin d'être connecté
        response = self.client.get(
            reverse('workshops:verify', kwargs={'code': cert.code})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cert'], cert)
        self.assertFalse(response.context['cert'].is_revoked)
        self.assertContains(response, cert.code)

    # ------------------------------------------------------------------
    # Test 13 — Code inexistant → context cert=None
    # ------------------------------------------------------------------
    def test_13_verify_unknown_code_returns_none(self):
        response = self.client.get(
            reverse('workshops:verify', kwargs={'code': 'HF-0000-FAKE-CODE'})
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['cert'])

    # ------------------------------------------------------------------
    # Test 14 — recommend() retourne scores décroissants
    # ------------------------------------------------------------------
    def test_14_recommend_returns_decreasing_scores(self):
        from .services.recommend import recommend

        # Utilisateur avec compétences Python/Django
        user = _make_user('ai_student', role='student',
                          skills=['Python', 'Django', 'Docker'],
                          specialty='Backend Development',
                          bio='Experienced backend developer')

        # Ateliers : un très pertinent, un moins
        ws_relevant = Workshop.objects.create(
            title='Django Advanced', description='Deep dive into Django ORM',
            speaker_name='Expert', mode='onsite', room='A1',
            starts_at=timezone.now() + timedelta(hours=2),
            ends_at=timezone.now() + timedelta(hours=4),
            capacity=20, is_open=True, created_by=self.admin,
            topic_tags=['Django', 'Python', 'Backend'],
        )
        ws_unrelated = Workshop.objects.create(
            title='Figma UX Workshop', description='Design prototypes with Figma',
            speaker_name='Designer', mode='online',
            meeting_url='https://zoom.us/j/design',
            starts_at=timezone.now() + timedelta(hours=5),
            ends_at=timezone.now() + timedelta(hours=7),
            capacity=20, is_open=True, created_by=self.admin,
            topic_tags=['Figma', 'UI', 'Design'],
        )

        results = recommend(user, [ws_relevant, ws_unrelated], top_n=6)

        # Les scores doivent être présents
        for r in results:
            self.assertTrue(hasattr(r, 'ai_score'))
            self.assertIsInstance(r.ai_score, int)

        # Scores décroissants
        scores = [r.ai_score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

        # Le workshop pertinent doit avoir un score >= à l'autre
        if len(results) >= 2:
            self.assertGreaterEqual(results[0].ai_score, results[-1].ai_score)

    # ------------------------------------------------------------------
    # Test 15 — Badge first-workshop débloqué au 1er certificat
    # ------------------------------------------------------------------
    def test_15_first_workshop_badge_awarded(self):
        ensure_badges_exist()
        ws = _make_workshop(self.admin, capacity=10)

        # Simuler un certificat créé
        cert = Certificate.objects.create(
            workshop=ws, user=self.student, hours=2.0,
        )

        from .services.badges import check_badges_for_certificate
        check_badges_for_certificate(cert)

        self.assertTrue(
            BadgeAward.objects.filter(
                user=self.student,
                badge__slug='first-workshop',
            ).exists()
        )

    # ------------------------------------------------------------------
    # Test 16 — Double annulation → pas de double promotion
    # ------------------------------------------------------------------
    def test_16_cancel_twice_does_not_double_promote(self):
        ws = _make_workshop(self.admin, capacity=1)
        waiter_a = _make_user('waiter_a', role='student')
        waiter_b = _make_user('waiter_b', role='student')

        Booking.objects.create(
            workshop=ws, user=self.student,
            status=Booking.Status.CONFIRMED, seat_number=1,
        )
        booking_a = Booking.objects.create(
            workshop=ws, user=waiter_a, status=Booking.Status.WAITING,
        )
        booking_b = Booking.objects.create(
            workshop=ws, user=waiter_b, status=Booking.Status.WAITING,
        )

        self.client.login(username='student_user', password='Test1234!')
        url = reverse('workshops:cancel', kwargs={'pk': ws.pk})

        self.client.post(url)  # annulation réelle → waiter_a promu
        booking_a.refresh_from_db()
        self.assertEqual(booking_a.status, Booking.Status.CONFIRMED)

        self.client.post(url)  # 2e clic → ne doit rien promouvoir
        booking_b.refresh_from_db()
        self.assertEqual(booking_b.status, Booking.Status.WAITING)

    # ------------------------------------------------------------------
    # Test 17 — Tri du catalogue par note
    # ------------------------------------------------------------------
    def test_17_list_sorts_by_rating(self):
        good = _make_workshop(self.admin, title='Excellent atelier')
        bad = _make_workshop(self.admin, title='Atelier moyen')

        rater = _make_user('rater_student', role='student')
        Booking.objects.create(
            workshop=good, user=rater,
            status=Booking.Status.ATTENDED, rating=5,
        )
        Booking.objects.create(
            workshop=bad, user=self.student,
            status=Booking.Status.ATTENDED, rating=2,
        )

        # Client anonyme : la recommandation IA n'entre pas en jeu
        response = self.client.get(
            reverse('workshops:list'), {'sort': 'rating'})
        self.assertEqual(response.status_code, 200)
        ids = [w.pk for w in response.context['workshops']]
        self.assertLess(ids.index(good.pk), ids.index(bad.pk))

    # ------------------------------------------------------------------
    # Test 18 — Un étudiant ne peut pas valider sa propre présence
    # ------------------------------------------------------------------
    def test_18_student_cannot_self_checkin(self):
        ws = _make_workshop(self.admin, capacity=10)
        booking = Booking.objects.create(
            workshop=ws, user=self.student,
            status=Booking.Status.CONFIRMED, seat_number=1,
        )

        self.client.login(username='student_user', password='Test1234!')
        response = self.client.get(
            reverse('workshops:checkin',
                    kwargs={'pk': ws.pk, 'token': booking.checkin_token})
        )

        self.assertEqual(response.status_code, 403)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertFalse(
            Certificate.objects.filter(workshop=ws, user=self.student).exists()
        )

    # ------------------------------------------------------------------
    # Test 19 — Atelier passé : bouton désactivé + réservation refusée
    # ------------------------------------------------------------------
    def test_19_past_workshop_cannot_be_booked(self):
        ws = _make_workshop(self.admin, starts_offset_h=-3, duration_h=2)
        self.client.login(username='student_user', password='Test1234!')

        response = self.client.get(
            reverse('workshops:detail', kwargs={'slug': ws.slug}))
        self.assertContains(response, 'Atelier terminé')
        self.assertNotContains(response, 'Réserver ma place')

        self.client.post(reverse('workshops:book', kwargs={'pk': ws.pk}))
        self.assertFalse(
            Booking.objects.filter(workshop=ws, user=self.student).exists()
        )

    # ------------------------------------------------------------------
    # Test 20 — Atelier à venir : compte à rebours affiché
    # ------------------------------------------------------------------
    def test_20_upcoming_workshop_shows_countdown(self):
        ws = _make_workshop(self.admin, starts_offset_h=5)
        self.client.login(username='student_user', password='Test1234!')

        response = self.client.get(
            reverse('workshops:detail', kwargs={'slug': ws.slug}))
        self.assertContains(response, 'data-workshop-countdown')
        self.assertContains(response, 'Réserver ma place')

    # ------------------------------------------------------------------
    # Test 21 — Atelier commencé mais pas terminé : réservation refusée
    # ------------------------------------------------------------------
    def test_21_started_workshop_cannot_be_booked(self):
        ws = _make_workshop(self.admin, starts_offset_h=-1, duration_h=2)
        self.client.login(username='student_user', password='Test1234!')

        response = self.client.get(
            reverse('workshops:detail', kwargs={'slug': ws.slug}))
        self.assertContains(response, 'Atelier commencé')

        self.client.post(reverse('workshops:book', kwargs={'pk': ws.pk}))
        self.assertFalse(
            Booking.objects.filter(workshop=ws, user=self.student).exists()
        )

    # ------------------------------------------------------------------
    # Test 22 — Numéros de série uniques et croissants
    # ------------------------------------------------------------------
    def test_22_certificate_serial_numbers_are_unique(self):
        ws1 = _make_workshop(self.admin, title='Série A')
        ws2 = _make_workshop(self.admin, title='Série B')
        cert1 = Certificate.objects.create(workshop=ws1, user=self.student)
        cert2 = Certificate.objects.create(workshop=ws2, user=self.student)

        self.assertIsNotNone(cert1.serial)
        self.assertIsNotNone(cert2.serial)
        self.assertNotEqual(cert1.serial, cert2.serial)
        self.assertEqual(cert2.serial, cert1.serial + 1)

    # ------------------------------------------------------------------
    # Test 23 — PDF généré avec un nom accentué / non Latin-1
    # ------------------------------------------------------------------
    def test_23_certificate_pdf_supports_unicode_names(self):
        from .services.certificate import generate_certificate_pdf

        self.student.first_name = 'Zoé'
        self.student.last_name = 'Müller'
        self.student.save(update_fields=['first_name', 'last_name'])

        ws = _make_workshop(self.admin, title='Atelier Élégant')
        cert = Certificate.objects.create(workshop=ws, user=self.student)

        pdf = generate_certificate_pdf(cert)
        self.assertIsNotNone(pdf)
        self.assertTrue(pdf.startswith(b'%PDF'))

    # ------------------------------------------------------------------
    # Test 24 — API places publique, API recommandations protégée
    # ------------------------------------------------------------------
    def test_24_api_endpoints(self):
        ws = _make_workshop(self.admin, capacity=10)

        # /seats/ est public
        response = self.client.get(
            reverse('workshops:api_seats', kwargs={'pk': ws.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], ws.pk)

        # /recommend/ exige une authentification
        response = self.client.get(reverse('workshops:api_recommend'))
        self.assertEqual(response.status_code, 302)

        self.client.login(username='student_user', password='Test1234!')
        response = self.client.get(reverse('workshops:api_recommend'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('recommendations', response.json())

    # ------------------------------------------------------------------
    # Test 25 — Export .ics limité à un atelier depuis le détail
    # ------------------------------------------------------------------
    def test_25_export_ics_single_workshop(self):
        ws1 = _make_workshop(self.admin, title='Atelier Un')
        ws2 = _make_workshop(self.admin, title='Atelier Deux')
        Booking.objects.create(
            workshop=ws1, user=self.student,
            status=Booking.Status.CONFIRMED, seat_number=1)
        Booking.objects.create(
            workshop=ws2, user=self.student,
            status=Booking.Status.CONFIRMED, seat_number=1)

        self.client.login(username='student_user', password='Test1234!')
        response = self.client.get(
            reverse('workshops:export_ics'), {'workshop': ws1.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/calendar', response['Content-Type'])
        body = response.content.decode('utf-8')
        self.assertIn('Atelier Un', body)
        self.assertNotIn('Atelier Deux', body)

    # ------------------------------------------------------------------
    # Test 26 — Prévision heuristique : valeurs bornées
    # ------------------------------------------------------------------
    def test_26_forecast_heuristic_is_bounded(self):
        from .services.forecast import forecast

        ws = _make_workshop(self.admin, capacity=10, starts_offset_h=2)
        result = forecast(ws)
        self.assertGreaterEqual(result['fill_proba'], 0)
        self.assertLessEqual(result['fill_proba'], 1)
        self.assertGreaterEqual(result['noshow_proba'], 0)
        self.assertLessEqual(result['noshow_proba'], 1)

        unlimited = _make_workshop(self.admin, capacity=0, title='Illimité')
        result = forecast(unlimited)
        self.assertEqual(result['fill_proba'], 0.0)

    # ------------------------------------------------------------------
    # Test 27 — Pagination du catalogue
    # ------------------------------------------------------------------
    def test_27_catalog_is_paginated(self):
        for index in range(13):
            _make_workshop(
                self.admin, title=f'Atelier pagination {index}',
                starts_offset_h=index + 1,
            )

        response = self.client.get(reverse('workshops:list'))
        self.assertEqual(len(response.context['workshops']), 12)
        self.assertEqual(response.context['total_count'], 13)

        response = self.client.get(reverse('workshops:list'), {'page': 2})
        self.assertEqual(len(response.context['workshops']), 1)

    # ------------------------------------------------------------------
    # Test 28 — Pas de bonus artificiel de 5 % dans la recommandation
    # ------------------------------------------------------------------
    def test_28_recommendation_has_no_artificial_bonus(self):
        from .services.recommend import recommend

        user = _make_user('rust_student', role='student',
                          skills=['Rust'], specialty='Systems')
        unrelated = Workshop.objects.create(
            title='Figma UX', description='Design with Figma',
            speaker_name='Designer', mode='online',
            meeting_url='https://zoom.us/j/design',
            starts_at=timezone.now() + timedelta(hours=2),
            ends_at=timezone.now() + timedelta(hours=4),
            capacity=20, is_open=True, created_by=self.admin,
            topic_tags=['Figma', 'Design'],
        )

        result = recommend(user, [unrelated])
        self.assertEqual(result[0].ai_score, 0)

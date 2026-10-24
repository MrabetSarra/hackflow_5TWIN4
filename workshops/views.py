"""
workshops/views.py
==================
16 vues couvrant P2 → P7 :

Catalogue & CRUD (organisateur)
  workshop_list        GET          catalogue + filtres + IA recommandation
  workshop_detail      GET          détail atelier (lien Zoom masqué si non réservé)
  workshop_create      GET/POST     créer un atelier  [admin/mentor]
  workshop_edit        GET/POST     modifier          [admin/créateur]
  workshop_delete      GET/POST     supprimer         [admin/créateur]
  workshop_close       POST         fermer inscriptions

Réservation (étudiant)
  book                 POST         réserver (places / waitlist / conflit)
  cancel               POST         annuler + promotion waitlist
  rate                 GET/POST     noter 1-5 + commentaire
  checkin              GET          valider présence via token QR

Replay (mode recorded)
  replay_progress      POST/GET     enregistrer progression (AJAX)
  replay_complete      POST         100% → attended + certificat

Certificat & vérification
  my_bookings          GET          mes réservations + mes certificats
  verify_certificate   GET          page publique (sans auth)
  revoke_certificate   POST         révoquer [admin]
  download_certificate GET          télécharger le PDF

Dashboard & calendrier
  organizer_dashboard  GET          stats + prédictions IA [admin/mentor]
  export_ics           GET          fichier .ics
"""

import io
import secrets
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q
from django.http import (FileResponse, HttpResponse, HttpResponseBadRequest,
                          JsonResponse)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import role_required
from student.models import Notification

from .forms import RatingForm, WorkshopFilterForm, WorkshopForm
from .models import (Badge, BadgeAward, Booking, Certificate, Workshop,
                     WorkshopActivity)


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _notify(user, title: str, message: str, icon: str = 'bi-bell-fill',
            url: str = ''):
    """Crée une notification non-bloquante."""
    try:
        Notification.objects.create(
            user=user, title=title, message=message,
            icon=icon, url=url,
        )
    except Exception:
        pass


def _log_activity(workshop, user, kind, detail=''):
    try:
        WorkshopActivity.objects.create(
            workshop=workshop, user=user, kind=kind, detail=detail)
    except Exception:
        pass


def _get_user_booking(workshop, user):
    """Retourne le Booking de l'utilisateur pour cet atelier ou None."""
    if not user.is_authenticated:
        return None
    return Booking.objects.filter(
        workshop=workshop, user=user).first()


def _check_schedule_conflict(user, workshop, exclude_booking=None):
    """
    Retourne le Booking en conflit ou None.
    Ne vérifie que les ateliers onsite/online (pas recorded).
    """
    if workshop.mode == Workshop.Mode.RECORDED:
        return None
    qs = Booking.objects.filter(
        user=user,
        status__in=['confirmed', 'attended'],
        workshop__mode__in=['onsite', 'online'],
    ).exclude(workshop=workshop).select_related('workshop')
    if exclude_booking:
        qs = qs.exclude(pk=exclude_booking.pk)
    for b in qs:
        other = b.workshop
        if not (workshop.ends_at <= other.starts_at
                or workshop.starts_at >= other.ends_at):
            return b
    return None


def _can_manage(user, workshop):
    """True si l'utilisateur peut éditer/supprimer cet atelier."""
    return user.role == 'admin' or workshop.created_by == user


def _ics_escape(value: str) -> str:
    """Échappe une valeur texte pour le format iCalendar (RFC 5545)."""
    return (
        str(value)
        .replace('\\', '\\\\')
        .replace(';', '\\;')
        .replace(',', '\\,')
        .replace('\n', '\\n')
    )


# ---------------------------------------------------------------------------
# P2 — Catalogue
# ---------------------------------------------------------------------------

def workshop_list(request):
    """
    Catalogue d'ateliers avec filtres.
    Si l'utilisateur est étudiant, applique les recommandations IA.
    """
    form = WorkshopFilterForm(request.GET or None)
    qs = Workshop.objects.select_related('created_by').prefetch_related('bookings')

    if form.is_valid():
        q        = form.cleaned_data.get('q', '')
        mode     = form.cleaned_data.get('mode', '')
        level    = form.cleaned_data.get('level', '')
        only_open = form.cleaned_data.get('only_open', False)
        sort     = form.cleaned_data.get('sort', 'date')

        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(speaker_name__icontains=q)
                | Q(description__icontains=q)
            )
        if mode:
            qs = qs.filter(mode=mode)
        if level:
            qs = qs.filter(level=level)
        if only_open:
            qs = qs.filter(is_open=True)

        if sort == '-date':
            qs = qs.order_by('-starts_at')
        else:
            qs = qs.order_by('starts_at')
    else:
        qs = qs.order_by('starts_at')

    workshops = list(qs)

    # Les tris par note et par places restantes portent sur des propriétés
    # calculées : ils sont donc appliqués en Python, pas en SQL.
    sort_key = form.cleaned_data.get('sort') if form.is_valid() else 'date'
    if sort_key == 'rating':
        workshops.sort(
            key=lambda w: (w.average_rating is not None, w.average_rating or 0),
            reverse=True,
        )
    elif sort_key == 'fill':
        workshops.sort(
            key=lambda w: (
                w.seats_left is None,
                w.seats_left if w.seats_left is not None else 999,
            )
        )

    # Recommandation IA pour les étudiants
    recommended = []
    schedule_plan = []
    if request.user.is_authenticated and request.user.role == 'student':
        try:
            from .services.recommend import recommend
            from .services.schedule import optimise_schedule
            recommended = recommend(request.user, workshops, top_n=6)
            schedule_plan = optimise_schedule(request.user, recommended, top_n=3)
        except Exception:
            pass

    # Marquer les ateliers déjà réservés par l'utilisateur courant
    booked_ids = set()
    if request.user.is_authenticated:
        booked_ids = set(
            Booking.objects.filter(
                user=request.user,
                status__in=['confirmed', 'waiting', 'attended'],
            ).values_list('workshop_id', flat=True)
        )

    return render(request, 'workshops/workshop_list.html', {
        'workshops':     workshops,
        'recommended':   recommended,
        'schedule_plan': schedule_plan,
        'filter_form':   form,
        'booked_ids':    booked_ids,
    })


# ---------------------------------------------------------------------------
# P2 — Détail
# ---------------------------------------------------------------------------

@login_required
def workshop_detail(request, slug):
    ws = get_object_or_404(Workshop, slug=slug)
    booking = _get_user_booking(ws, request.user)

    # Lien Zoom : jamais exposé si non réservé (contrôle serveur)
    meeting_url = None
    if ws.mode == Workshop.Mode.ONLINE:
        if booking and booking.status in ['confirmed', 'attended']:
            meeting_url = ws.meeting_url

    # Replay : disponible uniquement si réservé et non expiré
    replay_accessible = False
    if ws.mode == Workshop.Mode.RECORDED:
        if booking and booking.status in ['confirmed', 'attended']:
            replay_accessible = ws.is_replay_available

    # Prédiction de remplissage (organisateur uniquement)
    forecast_data = None
    if request.user.role in ('admin', 'mentor') or ws.created_by == request.user:
        try:
            from .services.forecast import forecast
            forecast_data = forecast(ws)
        except Exception:
            pass

    avis = ws.bookings.filter(
        rating__isnull=False
    ).select_related('user').order_by('-booked_at')[:10]

    return render(request, 'workshops/workshop_detail.html', {
        'workshop':          ws,
        'booking':           booking,
        'meeting_url':       meeting_url,
        'replay_accessible': replay_accessible,
        'forecast':          forecast_data,
        'avis':              avis,
        'can_manage':        _can_manage(request.user, ws),
    })


# ---------------------------------------------------------------------------
# P2 — CRUD organisateur
# ---------------------------------------------------------------------------

@role_required('admin', 'mentor')
def workshop_create(request):
    form = WorkshopForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        ws = form.save(commit=False)
        ws.created_by = request.user
        ws.save()
        _log_activity(ws, request.user, 'created', f'Créé par {request.user}')
        messages.success(request, f'Atelier «{ws.title}» créé avec succès.')
        return redirect('workshops:detail', slug=ws.slug)
    return render(request, 'workshops/workshop_form.html', {
        'form':  form,
        'action': 'Créer',
    })


@login_required
def workshop_edit(request, pk):
    ws = get_object_or_404(Workshop, pk=pk)
    if not _can_manage(request.user, ws):
        raise PermissionDenied

    form = WorkshopForm(
        request.POST or None,
        request.FILES or None,
        instance=ws,
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        _log_activity(ws, request.user, 'updated')
        messages.success(request, f'Atelier «{ws.title}» mis à jour.')
        return redirect('workshops:detail', slug=ws.slug)
    return render(request, 'workshops/workshop_form.html', {
        'form':     form,
        'workshop': ws,
        'action':   'Modifier',
    })


@login_required
def workshop_delete(request, pk):
    ws = get_object_or_404(Workshop, pk=pk)
    if not _can_manage(request.user, ws):
        raise PermissionDenied

    if request.method == 'POST':
        title = ws.title
        ws.delete()
        messages.success(request, f'Atelier «{title}» supprimé.')
        return redirect('workshops:list')
    return render(request, 'workshops/workshop_confirm_delete.html',
                  {'workshop': ws})


@login_required
@require_POST
def workshop_close(request, pk):
    ws = get_object_or_404(Workshop, pk=pk)
    if not _can_manage(request.user, ws):
        raise PermissionDenied
    ws.is_open = False
    ws.save(update_fields=['is_open'])
    _log_activity(ws, request.user, 'closed')
    messages.info(request, f'Inscriptions fermées pour «{ws.title}».')
    return redirect('workshops:detail', slug=ws.slug)


# ---------------------------------------------------------------------------
# P3 — Réservation
# ---------------------------------------------------------------------------

@role_required('student')
@require_POST
def book(request, pk):
    ws = get_object_or_404(Workshop, pk=pk)

    if not ws.is_open:
        messages.error(request, 'Les inscriptions pour cet atelier sont fermées.')
        return redirect('workshops:detail', slug=ws.slug)

    try:
        with transaction.atomic():
            # Verrouillage en lecture pour éviter les doublons concurrents
            ws_locked = Workshop.objects.select_for_update().get(pk=pk)

            # Vérifier conflit d'horaire
            conflict = _check_schedule_conflict(request.user, ws_locked)
            if conflict:
                messages.error(
                    request,
                    f'Conflit d\'horaire avec «{conflict.workshop.title}» '
                    f'({conflict.workshop.starts_at.strftime("%d/%m à %Hh%M")}).'
                )
                return redirect('workshops:detail', slug=ws.slug)

            # Déterminer le statut
            seats = ws_locked.seats_left
            if seats is None or seats > 0:
                status = Booking.Status.CONFIRMED
                # Prochain numéro de place
                last_seat = (
                    Booking.objects.filter(
                        workshop=ws_locked,
                        status__in=['confirmed', 'attended'],
                        seat_number__isnull=False,
                    ).order_by('-seat_number').first()
                )
                seat_number = (last_seat.seat_number + 1) if last_seat else 1
            else:
                status = Booking.Status.WAITING
                seat_number = None

            booking = Booking.objects.create(
                workshop=ws_locked,
                user=request.user,
                status=status,
                seat_number=seat_number,
            )

    except IntegrityError:
        messages.warning(request, 'Vous avez déjà réservé cet atelier.')
        return redirect('workshops:detail', slug=ws.slug)

    _log_activity(ws, request.user, 'booked',
                  f'status={booking.status}')

    if booking.status == Booking.Status.CONFIRMED:
        _notify(
            request.user,
            title=f'Réservation confirmée — {ws.title}',
            message=f'Place n°{booking.seat_number} confirmée pour le '
                    f'{ws.starts_at.strftime("%d/%m/%Y à %Hh%M")}.',
            icon='bi-check-circle-fill',
            url=ws.get_absolute_url(),
        )
        messages.success(
            request,
            f'Réservation confirmée ! Place n°{booking.seat_number}.')
    else:
        pos = booking.waitlist_position
        _notify(
            request.user,
            title=f'Liste d\'attente — {ws.title}',
            message=f'Vous êtes en position {pos} sur la liste d\'attente.',
            icon='bi-hourglass-split',
            url=ws.get_absolute_url(),
        )
        messages.info(
            request,
            f'Complet — vous êtes en position {pos} sur la liste d\'attente.')

    return redirect('workshops:detail', slug=ws.slug)


# ---------------------------------------------------------------------------
# P3 — Annulation (avec promotion waitlist)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def cancel(request, pk):
    ws = get_object_or_404(Workshop, pk=pk)
    booking = get_object_or_404(Booking, workshop=ws, user=request.user)

    if booking.status == Booking.Status.ATTENDED:
        messages.error(request, 'Vous avez déjà participé, impossible d\'annuler.')
        return redirect('workshops:my_bookings')

    if booking.status == Booking.Status.CANCELLED:
        messages.info(request, 'Cette réservation est déjà annulée.')
        return redirect('workshops:my_bookings')

    # Seule une réservation confirmée libère réellement une place.
    # Annuler une place "en attente" ne doit jamais promouvoir quelqu'un.
    freed_a_seat = booking.status == Booking.Status.CONFIRMED

    with transaction.atomic():
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.save(update_fields=['status', 'cancelled_at'])

        _log_activity(ws, request.user, 'cancelled')

        # Promouvoir le premier en attente
        if freed_a_seat and ws.seats_left is not None and ws.seats_left > 0:
            first_wait = (
                Booking.objects.select_for_update()
                .filter(workshop=ws, status=Booking.Status.WAITING)
                .order_by('booked_at')
                .first()
            )
            if first_wait:
                # Attribuer le numéro de place libéré
                first_wait.status = Booking.Status.CONFIRMED
                first_wait.seat_number = booking.seat_number
                first_wait.save(update_fields=['status', 'seat_number'])
                _notify(
                    first_wait.user,
                    title=f'Bonne nouvelle ! Place disponible — {ws.title}',
                    message=f'Vous avez été promu(e) de la liste d\'attente. '
                            f'Place n°{first_wait.seat_number} confirmée.',
                    icon='bi-arrow-up-circle-fill',
                    url=ws.get_absolute_url(),
                )

    messages.success(request, f'Votre réservation pour «{ws.title}» a été annulée.')
    return redirect('workshops:my_bookings')


# ---------------------------------------------------------------------------
# P5 — Notation
# ---------------------------------------------------------------------------

@role_required('student')
def rate(request, pk):
    ws = get_object_or_404(Workshop, pk=pk)
    booking = get_object_or_404(
        Booking, workshop=ws, user=request.user,
        status=Booking.Status.ATTENDED,
    )

    form = RatingForm(request.POST or None, instance=booking)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Votre avis a été enregistré, merci !')
        return redirect('workshops:my_bookings')

    return render(request, 'workshops/rate.html', {
        'form':    form,
        'workshop': ws,
        'booking': booking,
    })


# ---------------------------------------------------------------------------
# P5 — Check-in QR
# ---------------------------------------------------------------------------

@login_required
def checkin(request, pk, token):
    """
    Valide la présence d'un étudiant via son token QR.

    Réservée aux organisateurs / mentors : un étudiant ne peut pas valider
    sa propre présence (intégrité du certificat).
    """
    ws = get_object_or_404(Workshop, pk=pk)
    booking = get_object_or_404(Booking, workshop=ws, checkin_token=token)

    if request.user.role not in ('admin', 'mentor'):
        raise PermissionDenied

    if booking.status == Booking.Status.ATTENDED:
        messages.info(request, 'Présence déjà enregistrée.')
        return redirect('workshops:detail', slug=ws.slug)

    if booking.status != Booking.Status.CONFIRMED:
        messages.error(request, 'Cette réservation n\'est pas confirmée.')
        return redirect('workshops:detail', slug=ws.slug)

    with transaction.atomic():
        booking.status = Booking.Status.ATTENDED
        booking.attended_at = timezone.now()
        booking.save(update_fields=['status', 'attended_at'])
        _log_activity(ws, booking.user, 'checkin')

        # Créer le certificat
        _issue_certificate(ws, booking)

    _notify(
        booking.user,
        title='Présence enregistrée 🎓',
        message=f'Votre certificat pour «{ws.title}» est en cours de génération.',
        icon='bi-patch-check-fill',
        url='/workshops/my/',
    )
    messages.success(
        request,
        f'Check-in validé pour {booking.user.get_full_name() or booking.user.username}.'
    )
    return redirect('workshops:detail', slug=ws.slug)


# ---------------------------------------------------------------------------
# P4 — Replay (mode recorded)
# ---------------------------------------------------------------------------

@login_required
def replay_progress(request, pk):
    """
    GET  → renvoie la progression actuelle (JSON)
    POST → met à jour la progression (AJAX)
    """
    ws = get_object_or_404(
        Workshop, pk=pk, mode=Workshop.Mode.RECORDED)
    booking = get_object_or_404(
        Booking, workshop=ws, user=request.user,
        status__in=['confirmed', 'attended'],
    )

    if request.method == 'POST':
        try:
            progress = int(request.POST.get('progress', 0))
            progress = max(0, min(100, progress))
        except (ValueError, TypeError):
            return HttpResponseBadRequest('progress invalide')

        booking.replay_progress = progress
        booking.save(update_fields=['replay_progress'])
        return JsonResponse({'progress': progress, 'ok': True})

    return JsonResponse({'progress': booking.replay_progress})


@role_required('student')
@require_POST
def replay_complete(request, pk):
    """L'étudiant déclare avoir terminé la vidéo → attended + certificat."""
    ws = get_object_or_404(
        Workshop, pk=pk, mode=Workshop.Mode.RECORDED)
    booking = get_object_or_404(
        Booking, workshop=ws, user=request.user,
        status__in=['confirmed'],
    )

    with transaction.atomic():
        booking.replay_progress = 100
        booking.status = Booking.Status.ATTENDED
        booking.attended_at = timezone.now()
        booking.save(update_fields=['replay_progress', 'status', 'attended_at'])
        _issue_certificate(ws, booking)
        _log_activity(ws, request.user, 'checkin', 'replay 100%')

    messages.success(
        request,
        'Félicitations ! Votre certificat est en cours de génération.')
    return redirect('workshops:my_bookings')


# ---------------------------------------------------------------------------
# P5 — Mes réservations & certificats
# ---------------------------------------------------------------------------

@login_required
def my_bookings(request):
    bookings = (
        Booking.objects.filter(user=request.user)
        .select_related('workshop')
        .prefetch_related('workshop__certificates')
        .order_by('-booked_at')
    )
    certificates = Certificate.objects.filter(
        user=request.user
    ).select_related('workshop').order_by('-issued_at')

    badges_awarded = BadgeAward.objects.filter(
        user=request.user
    ).select_related('badge', 'workshop').order_by('-awarded_at')

    return render(request, 'workshops/my_bookings.html', {
        'bookings':     bookings,
        'certificates': certificates,
        'badges':       badges_awarded,
    })


# ---------------------------------------------------------------------------
# P5 — Certificat : vérification publique (sans auth)
# ---------------------------------------------------------------------------

def verify_certificate(request, code):
    """Page publique /workshops/verify/<code>/"""
    cert = Certificate.objects.filter(code=code).select_related(
        'user', 'workshop').first()
    return render(request, 'workshops/certificate_verify.html', {
        'cert': cert,
        'code': code,
    })


# ---------------------------------------------------------------------------
# P5 — Téléchargement PDF
# ---------------------------------------------------------------------------

@login_required
def download_certificate(request, pk):
    cert = get_object_or_404(Certificate, pk=pk)
    # Seul le propriétaire ou un admin peut télécharger
    if cert.user != request.user and request.user.role != 'admin':
        raise PermissionDenied

    if cert.is_revoked:
        messages.error(request, 'Ce certificat a été révoqué.')
        return redirect('workshops:my_bookings')

    if not cert.pdf:
        # Tentative de régénération
        from .services.certificate import attach_pdf_to_certificate
        attach_pdf_to_certificate(cert)
        cert.refresh_from_db()

    if cert.pdf:
        try:
            response = FileResponse(
                cert.pdf.open('rb'),
                content_type='application/pdf',
            )
            response['Content-Disposition'] = (
                f'attachment; filename="certificate_{cert.code}.pdf"'
            )
            return response
        except Exception:
            pass

    messages.error(request, 'PDF indisponible pour le moment.')
    return redirect('workshops:my_bookings')


# ---------------------------------------------------------------------------
# P5 — Révoquer un certificat (admin)
# ---------------------------------------------------------------------------

@role_required('admin')
@require_POST
def revoke_certificate(request, pk):
    cert = get_object_or_404(Certificate, pk=pk)
    cert.is_revoked = True
    cert.save(update_fields=['is_revoked'])
    _log_activity(cert.workshop, request.user, 'revoked',
                  f'Certificat {cert.code}')
    messages.warning(request, f'Certificat {cert.code} révoqué.')
    return redirect('workshops:dashboard')


# ---------------------------------------------------------------------------
# P7 — Dashboard organisateur
# ---------------------------------------------------------------------------

@role_required('admin', 'mentor')
def organizer_dashboard(request):
    workshops = (
        Workshop.objects.filter(created_by=request.user)
        .annotate(
            nb_confirmed=Count(
                'bookings',
                filter=Q(bookings__status__in=['confirmed', 'attended']),
            ),
            avg_rating=Avg('bookings__rating'),
        )
        .order_by('-starts_at')
    )

    # Si admin → tous les ateliers
    if request.user.role == 'admin':
        workshops = (
            Workshop.objects.annotate(
                nb_confirmed=Count(
                    'bookings',
                    filter=Q(bookings__status__in=['confirmed', 'attended']),
                ),
                avg_rating=Avg('bookings__rating'),
            ).order_by('-starts_at')
        )

    # Prédictions IA sur les ateliers à venir
    now = timezone.now()
    upcoming = [w for w in workshops if w.starts_at > now]
    forecasts = {}
    try:
        from .services.forecast import forecast as do_forecast
        for w in upcoming[:5]:
            forecasts[w.pk] = do_forecast(w)
    except Exception:
        pass

    # Statistiques globales
    total_confirmed = sum(getattr(w, 'nb_confirmed', 0) for w in workshops)
    total_attended  = sum(
        w.bookings.filter(status='attended').count() for w in workshops
    )
    total_certs = Certificate.objects.filter(
        workshop__in=workshops
    ).count()

    return render(request, 'workshops/organizer_dashboard.html', {
        'workshops':       workshops,
        'forecasts':       forecasts,
        'total_confirmed': total_confirmed,
        'total_attended':  total_attended,
        'total_certs':     total_certs,
        'now':             now,
    })


# ---------------------------------------------------------------------------
# P7 — Export .ics
# ---------------------------------------------------------------------------

@login_required
def export_ics(request):
    """
    Génère un fichier iCalendar (.ics) pour les ateliers réservés
    (ou tous si organisateur).
    """
    if request.user.role in ('admin', 'mentor'):
        workshops = Workshop.objects.filter(created_by=request.user)
    else:
        booked_ids = Booking.objects.filter(
            user=request.user,
            status__in=['confirmed', 'attended', 'waiting'],
        ).values_list('workshop_id', flat=True)
        workshops = Workshop.objects.filter(pk__in=booked_ids)

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//HackFlow//Workshops//FR',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
    ]

    for ws in workshops:
        uid = f'workshop-{ws.pk}@hackflow.app'
        # iCalendar attend de l'UTC explicite (suffixe Z)
        dtstart = ws.starts_at.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        dtend   = ws.ends_at.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        now_str = timezone.now().astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        location = ws.room if ws.mode == 'onsite' else (
            ws.meeting_url if ws.mode == 'online' else 'En ligne (replay)')
        summary = _ics_escape(ws.title)
        desc = _ics_escape(ws.description[:200] + '…')

        lines += [
            'BEGIN:VEVENT',
            f'UID:{uid}',
            f'DTSTAMP:{now_str}',
            f'DTSTART:{dtstart}',
            f'DTEND:{dtend}',
            f'SUMMARY:{summary}',
            f'DESCRIPTION:{desc}',
            f'LOCATION:{_ics_escape(location)}',
            'END:VEVENT',
        ]

    lines.append('END:VCALENDAR')
    content = '\r\n'.join(lines)

    response = HttpResponse(content, content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="workshops.ics"'
    return response


# ---------------------------------------------------------------------------
# Helper interne : émettre un certificat
# ---------------------------------------------------------------------------

def _issue_certificate(workshop, booking):
    """
    Crée le Certificate s'il n'existe pas encore.
    La génération PDF est déclenchée par le signal post_save.
    """
    from decimal import Decimal

    duration = workshop.ends_at - workshop.starts_at
    hours = Decimal(str(round(duration.total_seconds() / 3600, 1)))

    try:
        Certificate.objects.get_or_create(
            workshop=workshop,
            user=booking.user,
            defaults={'hours': hours},
        )
    except IntegrityError:
        pass  # Déjà existant (race condition)

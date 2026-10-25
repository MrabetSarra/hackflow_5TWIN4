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

from datetime import timezone as dt_timezone
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q
from django.http import (FileResponse, HttpResponse, HttpResponseBadRequest,
                          JsonResponse)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

import logging

from accounts.decorators import role_required
from student.models import Notification

from .forms import RatingForm, WorkshopFilterForm, WorkshopForm
from .models import (Badge, BadgeAward, Booking, Certificate, Workshop,
                     WorkshopActivity, WorkshopFavorite)

logger = logging.getLogger(__name__)


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


def _taken_seat_numbers(workshop):
    """Numéros de places réellement occupés (confirmés ou présents)."""
    return set(
        Booking.objects.filter(
            workshop=workshop,
            status__in=['confirmed', 'attended'],
            seat_number__isnull=False,
        ).values_list('seat_number', flat=True)
    )


def _next_available_seat(workshop):
    """Première place libre, ou None si l'atelier est complet."""
    if not workshop.capacity:
        return None
    taken = _taken_seat_numbers(workshop)
    for number in range(1, workshop.capacity + 1):
        if number not in taken:
            return number
    return None


def _can_view_content(user, workshop):
    """
    True si l'utilisateur peut voir le contenu de l'atelier (lien, vidéo, salle)
    sans avoir besoin de réservation.
    Admin et mentor : accès libre.
    Étudiant : doit avoir une réservation confirmée/attended.
    """
    if not user.is_authenticated:
        return False
    if getattr(user, 'role', None) in ('admin', 'mentor'):
        return True
    return False


def _can_manage(user, workshop):
    """True si l'utilisateur peut éditer/supprimer cet atelier."""
    if getattr(user, 'role', None) == 'admin':
        return True
    return (
        getattr(user, 'role', None) == 'mentor'
        and workshop.created_by_id == user.pk
    )


def _workshop_base_template(user):
    """Layout cohérent avec le rôle de l'utilisateur."""
    role = getattr(user, 'role', None)
    if role == 'mentor':
        return 'layouts/base_mentor.html'
    if role in ('admin', 'organization'):
        return 'layouts/base_admin.html'
    return 'layouts/base_student.html'


def _redirect_back(request, fallback):
    """Redirige vers ``next``/Referer uniquement si la cible est sûre."""
    target = request.POST.get('next') or request.META.get('HTTP_REFERER') or ''
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(target)
    return redirect(fallback)


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
    favorites_only = (
        request.user.is_authenticated
        and request.user.role == 'student'
        and request.GET.get('favorites') == '1'
    )
    qs = Workshop.objects.select_related('created_by').prefetch_related('bookings')
    if favorites_only:
        qs = qs.filter(favorites__user=request.user)

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

    # Recommandation IA pour les étudiants (masquée quand on filtre les favoris)
    recommended = []
    schedule_plan = []
    if (
        request.user.is_authenticated
        and request.user.role == 'student'
        and not favorites_only
    ):
        try:
            from .services.recommend import recommend
            from .services.schedule import optimise_schedule
            recommended = recommend(request.user, workshops, top_n=6)
            schedule_plan = optimise_schedule(request.user, recommended, top_n=3)
        except Exception:
            pass

    # Marquer les ateliers déjà réservés / favoris de l'utilisateur courant
    booked_ids = set()
    favorite_ids = set()
    if request.user.is_authenticated:
        booked_ids = set(
            Booking.objects.filter(
                user=request.user,
                status__in=['confirmed', 'waiting', 'attended'],
            ).values_list('workshop_id', flat=True)
        )
        favorite_ids = set(
            WorkshopFavorite.objects.filter(
                user=request.user,
            ).values_list('workshop_id', flat=True)
        )

    # Pagination : 12 cartes par page, sans perdre les filtres courants.
    total_count = len(workshops)
    paginator = Paginator(workshops, 12)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    filter_query = params.urlencode()

    return render(request, 'workshops/workshop_list.html', {
        'workshops':     list(page_obj.object_list),
        'page_obj':      page_obj,
        'total_count':   total_count,
        'filter_query':  filter_query,
        'recommended':   recommended,
        'schedule_plan': schedule_plan,
        'filter_form':   form,
        'booked_ids':    booked_ids,
        'favorite_ids':  favorite_ids,
        'favorites_only': favorites_only,
        'workshop_base_template': _workshop_base_template(request.user),
    })


# ---------------------------------------------------------------------------
# P2 — Détail
# ---------------------------------------------------------------------------

@login_required
def workshop_detail(request, slug):
    ws = get_object_or_404(
        Workshop.objects.prefetch_related('bookings'), slug=slug)
    booking = _get_user_booking(ws, request.user)

    # Lien Zoom : exposé si réservé (étudiant) ou accès libre (admin/mentor)
    meeting_url = None
    can_access_meeting = False
    if ws.mode == Workshop.Mode.ONLINE:
        can_access_meeting = (
            (booking and booking.status in ['confirmed', 'attended'])
            or _can_view_content(request.user, ws)
        )
        if can_access_meeting:
            meeting_url = ws.meeting_url

    # Replay : disponible si réservé (étudiant) ou accès libre (admin/mentor)
    replay_accessible = False
    can_access_replay = False
    replay_is_direct = False
    if ws.mode == Workshop.Mode.RECORDED:
        can_access_replay = (
            (booking and booking.status in ['confirmed', 'attended'])
            or _can_view_content(request.user, ws)
        )
        if can_access_replay:
            replay_accessible = ws.is_replay_available
        clean_url = (ws.replay_url or '').split('?', 1)[0].lower()
        replay_is_direct = clean_url.endswith(
            ('.mp4', '.webm', '.ogg', '.ogv', '.mov', '.m4v'))

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

    is_favorite = (
        request.user.role == 'student'
        and WorkshopFavorite.objects.filter(
            user=request.user, workshop=ws).exists()
    )

    return render(request, 'workshops/workshop_detail.html', {
        'workshop':          ws,
        'booking':           booking,
        'meeting_url':       meeting_url,
        'can_access_meeting': can_access_meeting,
        'replay_accessible': replay_accessible,
        'can_access_replay': can_access_replay,
        'replay_is_direct':  replay_is_direct,
        'forecast':          forecast_data,
        'avis':              avis,
        'can_manage':        _can_manage(request.user, ws),
        'is_favorite':       is_favorite,
        'workshop_base_template': _workshop_base_template(request.user),
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
        'workshop_base_template': _workshop_base_template(request.user),
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
        'workshop_base_template': _workshop_base_template(request.user),
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
    return render(request, 'workshops/workshop_confirm_delete.html', {
        'workshop': ws,
        'workshop_base_template': _workshop_base_template(request.user),
    })


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

    closed_reason = ws.booking_closed_reason
    if closed_reason:
        messages.error(request, f'Réservation impossible : {closed_reason.lower()}.')
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

            existing = (
                Booking.objects.select_for_update()
                .filter(workshop=ws_locked, user=request.user)
                .first()
            )
            if existing and existing.status != Booking.Status.CANCELLED:
                messages.warning(request, 'Vous avez déjà réservé cet atelier.')
                return redirect('workshops:detail', slug=ws.slug)

            # Sélection explicite d'une place (atelier présentiel).
            requested_seat = None
            if ws_locked.mode == Workshop.Mode.ONSITE and ws_locked.capacity > 0:
                raw_seat = (request.POST.get('seat_number') or '').strip()
                if raw_seat:
                    try:
                        requested_seat = int(raw_seat)
                    except (TypeError, ValueError):
                        messages.error(request, 'Place invalide.')
                        return redirect('workshops:seats', pk=ws.pk)
                    if not 1 <= requested_seat <= ws_locked.capacity:
                        messages.error(request, 'Cette place n\'existe pas.')
                        return redirect('workshops:seats', pk=ws.pk)
                    if requested_seat in _taken_seat_numbers(ws_locked):
                        messages.error(
                            request,
                            'Cette place vient d\'être réservée. '
                            'Choisissez-en une autre.',
                        )
                        return redirect('workshops:seats', pk=ws.pk)

            # Déterminer le statut et la place.
            seats = ws_locked.seats_left
            status = Booking.Status.WAITING
            seat_number = None
            if seats is None or seats > 0:
                status = Booking.Status.CONFIRMED
                if ws_locked.mode == Workshop.Mode.ONSITE:
                    if ws_locked.capacity > 0:
                        seat_number = (
                            requested_seat
                            if requested_seat is not None
                            else _next_available_seat(ws_locked)
                        )
                    # capacity=0 : atelier présentiel sans places numérotées.
                # En visio ou replay, il n'y a pas de place physique : on ne
                # stocke pas de seat_number pour ne pas afficher « Place n°1 »
                # à un participant en ligne.

            if (
                status == Booking.Status.CONFIRMED
                and ws_locked.mode == Workshop.Mode.ONSITE
                and ws_locked.capacity > 0
                and seat_number is None
            ):
                # Toutes les places ont été prises entre-temps : waitlist.
                status = Booking.Status.WAITING

            if existing:
                # Réutilisation d'une réservation annulée : évite de bloquer
                # l'étudiant à cause de la contrainte unique (atelier, user).
                existing.status = status
                existing.seat_number = seat_number
                existing.cancelled_at = None
                existing.attended_at = None
                existing.rating = None
                existing.comment = ''
                existing.replay_progress = 0
                existing.save(update_fields=[
                    'status', 'seat_number', 'cancelled_at', 'attended_at',
                    'rating', 'comment', 'replay_progress',
                ])
                booking = existing
            else:
                booking = Booking.objects.create(
                    workshop=ws_locked,
                    user=request.user,
                    status=status,
                    seat_number=seat_number,
                )

    except IntegrityError as exc:
        error_text = str(exc).lower()
        if 'seat_number' in error_text or 'unique_active_seat' in error_text:
            messages.error(
                request,
                'Cette place vient d\'être réservée. Choisissez-en une autre.',
            )
            return redirect('workshops:seats', pk=ws.pk)
        messages.warning(request, 'Vous avez déjà réservé cet atelier.')
        return redirect('workshops:detail', slug=ws.slug)

    _log_activity(ws, request.user, 'booked',
                  f'status={booking.status}')

    if booking.status == Booking.Status.CONFIRMED:
        if booking.seat_number:
            confirmation = (
                f'Place n°{booking.seat_number} confirmée pour le '
                f'{ws.starts_at.strftime("%d/%m/%Y à %Hh%M")}.'
            )
            success = f'Réservation confirmée ! Place n°{booking.seat_number}.'
        else:
            confirmation = (
                f'Réservation confirmée pour le '
                f'{ws.starts_at.strftime("%d/%m/%Y à %Hh%M")}.'
            )
            success = 'Réservation confirmée !'
        _notify(
            request.user,
            title=f'Réservation confirmée — {ws.title}',
            message=confirmation,
            icon='bi-check-circle-fill',
            url=ws.get_absolute_url(),
        )
        messages.success(request, success)
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


@role_required('student')
def select_seat(request, pk):
    """Carte des places pour un atelier présentiel."""
    ws = get_object_or_404(Workshop, pk=pk)

    if ws.mode != Workshop.Mode.ONSITE:
        messages.info(
            request,
            'Cet atelier ne nécessite pas de sélection de place.',
        )
        return redirect('workshops:detail', slug=ws.slug)

    if ws.capacity <= 0:
        messages.info(
            request,
            'Cet atelier ne propose pas de places numérotées.',
        )
        return redirect('workshops:detail', slug=ws.slug)

    existing = (
        Booking.objects.filter(workshop=ws, user=request.user)
        .exclude(status=Booking.Status.CANCELLED)
        .first()
    )
    if existing:
        messages.info(
            request,
            'Vous avez déjà une réservation pour cet atelier.',
        )
        return redirect('workshops:detail', slug=ws.slug)

    closed_reason = ws.booking_closed_reason
    if closed_reason:
        messages.error(
            request,
            f'Réservation impossible : {closed_reason.lower()}.',
        )
        return redirect('workshops:detail', slug=ws.slug)

    taken = _taken_seat_numbers(ws)
    columns = 12
    seat_rows = []
    for start in range(1, ws.capacity + 1, columns):
        seat_rows.append([
            {'number': number, 'taken': number in taken}
            for number in range(
                start, min(start + columns, ws.capacity + 1))
        ])

    return render(request, 'workshops/workshop_seats.html', {
        'workshop': ws,
        'seat_rows': seat_rows,
        'taken_count': len(taken),
        'free_count': max(0, ws.capacity - len(taken)),
        'columns': columns,
    })


# ---------------------------------------------------------------------------
# P3 — Annulation (avec promotion waitlist)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def cancel(request, pk):
    with transaction.atomic():
        # Verrouiller l'atelier et la réservation : deux annulations
        # simultanées ne peuvent pas promouvoir deux personnes.
        ws = get_object_or_404(
            Workshop.objects.select_for_update(), pk=pk)
        booking = get_object_or_404(
            Booking.objects.select_for_update(),
            workshop=ws, user=request.user,
        )

        if booking.status == Booking.Status.ATTENDED:
            messages.error(
                request, 'Vous avez déjà participé, impossible d\'annuler.')
            return redirect('workshops:my_bookings')

        if booking.status == Booking.Status.CANCELLED:
            messages.info(request, 'Cette réservation est déjà annulée.')
            return redirect('workshops:my_bookings')

        # Seule une réservation confirmée libère réellement une place.
        # Annuler une place "en attente" ne doit jamais promouvoir quelqu'un.
        freed_a_seat = booking.status == Booking.Status.CONFIRMED
        freed_seat_number = booking.seat_number

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
                # Attribuer le numéro de place libéré (présentiel uniquement).
                first_wait.status = Booking.Status.CONFIRMED
                first_wait.seat_number = (
                    freed_seat_number
                    if ws.mode == Workshop.Mode.ONSITE
                    else None
                )
                first_wait.save(update_fields=['status', 'seat_number'])
                if first_wait.seat_number:
                    promotion_message = (
                        'Vous avez été promu(e) de la liste d\'attente. '
                        f'Place n°{first_wait.seat_number} confirmée.'
                    )
                else:
                    promotion_message = (
                        'Vous avez été promu(e) de la liste d\'attente. '
                        'Votre réservation est confirmée.'
                    )
                _notify(
                    first_wait.user,
                    title=f'Bonne nouvelle ! Place disponible — {ws.title}',
                    message=promotion_message,
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

    GET  → page de confirmation (aucune modification d'état).
    POST → valide réellement le check-in. Cela évite qu'un simple aperçu
           de lien, un robot d'indexation ou une balise <img> déclenche
           un check-in accidentel.
    """
    ws = get_object_or_404(Workshop, pk=pk)
    booking = get_object_or_404(
        Booking.objects.select_related('user'), workshop=ws,
        checkin_token=token,
    )

    if request.user.role not in ('admin', 'mentor'):
        raise PermissionDenied

    if booking.status == Booking.Status.ATTENDED:
        messages.info(request, 'Présence déjà enregistrée.')
        return redirect('workshops:detail', slug=ws.slug)

    if booking.status != Booking.Status.CONFIRMED:
        messages.error(request, 'Cette réservation n\'est pas confirmée.')
        return redirect('workshops:detail', slug=ws.slug)

    if request.method != 'POST':
        return render(request, 'workshops/checkin_confirm.html', {
            'workshop': ws,
            'booking':  booking,
        })

    with transaction.atomic():
        locked = Booking.objects.select_for_update().get(pk=booking.pk)
        if locked.status == Booking.Status.ATTENDED:
            messages.info(request, 'Présence déjà enregistrée.')
            return redirect('workshops:detail', slug=ws.slug)
        if locked.status != Booking.Status.CONFIRMED:
            messages.error(request, 'Cette réservation n\'est pas confirmée.')
            return redirect('workshops:detail', slug=ws.slug)

        locked.status = Booking.Status.ATTENDED
        locked.attended_at = timezone.now()
        locked.save(update_fields=['status', 'attended_at'])
        booking = locked
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

        # La progression ne régresse jamais (un retour en arrière dans la
        # vidéo ne doit pas effacer une progression déjà enregistrée).
        progress = max(booking.replay_progress, progress)
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
        .prefetch_related('workshop__bookings')
        .order_by('-booked_at')
    )
    certificates = list(
        Certificate.objects.filter(user=request.user)
        .select_related('workshop')
        .order_by('-issued_at')
    )
    badges_awarded = list(
        BadgeAward.objects.filter(user=request.user)
        .select_related('badge', 'workshop')
        .order_by('-awarded_at')
    )

    # Associe le badge obtenu à l'atelier correspondant pour l'afficher sur
    # la carte du certificat (un seul badge par atelier dans ce résumé).
    badge_by_workshop = {}
    for award in badges_awarded:
        if award.workshop_id and award.workshop_id not in badge_by_workshop:
            badge_by_workshop[award.workshop_id] = award

    for cert in certificates:
        cert.badge_award = badge_by_workshop.get(cert.workshop_id)
        verify_url = request.build_absolute_uri(cert.get_verify_url())
        cert.linkedin_share_url = (
            'https://www.linkedin.com/sharing/share-offsite/?url='
            + quote(verify_url, safe='')
        )

    booked_ids = set(
        Booking.objects.filter(
            user=request.user,
            status__in=['confirmed', 'waiting', 'attended'],
        ).values_list('workshop_id', flat=True)
    )
    favorite_ids = set(
        WorkshopFavorite.objects.filter(
            user=request.user,
        ).values_list('workshop_id', flat=True)
    )

    favorite_workshops = []
    recommended = []
    if request.user.role == 'student':
        favorite_workshops = list(
            Workshop.objects.filter(favorites__user=request.user)
            .select_related('created_by')
            .prefetch_related('bookings')
            .order_by('starts_at')
        )
        candidates = list(
            Workshop.objects.filter(
                is_open=True,
                starts_at__gte=timezone.now(),
            )
            .exclude(pk__in=booked_ids)
            .select_related('created_by')
            .prefetch_related('bookings')
            .order_by('starts_at')
        )
        try:
            from .services.recommend import recommend
            recommended = [
                w for w in recommend(request.user, candidates, top_n=6)
                if getattr(w, 'ai_score', 0) > 0
            ][:3]
        except Exception:
            recommended = []

    return render(request, 'workshops/my_bookings.html', {
        'bookings':           bookings,
        'certificates':       certificates,
        'badges':             badges_awarded,
        'favorite_workshops': favorite_workshops,
        'recommended':        recommended,
        'booked_ids':         booked_ids,
        'favorite_ids':       favorite_ids,
    })


@role_required('student')
@require_POST
def toggle_favorite(request, pk):
    """Ajoute ou retire un atelier des favoris de l'étudiant connecté."""
    workshop = get_object_or_404(Workshop, pk=pk)
    favorite, created = WorkshopFavorite.objects.get_or_create(
        user=request.user, workshop=workshop)
    if created:
        messages.success(
            request, f'«{workshop.title}» ajouté à vos favoris.')
    else:
        favorite.delete()
        messages.info(
            request, f'«{workshop.title}» retiré de vos favoris.')
    return _redirect_back(request, reverse('workshops:list'))


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
    base_qs = (
        Workshop.objects.filter(created_by=request.user)
        if request.user.role != 'admin'
        else Workshop.objects.all()
    )
    workshops = list(
        base_qs.annotate(
            nb_confirmed=Count(
                'bookings',
                filter=Q(bookings__status__in=['confirmed', 'attended']),
                distinct=True,
            ),
            nb_attended=Count(
                'bookings',
                filter=Q(bookings__status='attended'),
                distinct=True,
            ),
            nb_waiting=Count(
                'bookings',
                filter=Q(bookings__status='waiting'),
                distinct=True,
            ),
            avg_rating=Avg('bookings__rating'),
        ).order_by('-starts_at')
    )

    # Statistiques globales (aucune requête par atelier)
    total_confirmed = sum(w.confirmed_count for w in workshops)
    total_attended  = sum(w.attendee_count for w in workshops)
    total_certs = Certificate.objects.filter(
        workshop__in=workshops
    ).count()

    now = timezone.now()

    return render(request, 'workshops/organizer_dashboard.html', {
        'workshops':       workshops,
        'total_confirmed': total_confirmed,
        'total_attended':  total_attended,
        'total_certs':     total_certs,
        'now':             now,
        'workshop_base_template': _workshop_base_template(request.user),
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
    role = request.user.role
    if role == 'admin':
        workshops = Workshop.objects.all()
    elif role == 'mentor':
        workshops = Workshop.objects.filter(created_by=request.user)
    else:
        booked_ids = Booking.objects.filter(
            user=request.user,
            status__in=['confirmed', 'attended', 'waiting'],
        ).values_list('workshop_id', flat=True)
        workshops = Workshop.objects.filter(pk__in=booked_ids)

    # Le lien Zoom/Meet ne doit être exporté que pour les étudiants dont la
    # place est confirmée (ou qui ont participé), jamais pour une liste
    # d'attente.
    confirmed_meeting_ids = set()
    if role == 'student':
        confirmed_meeting_ids = set(
            Booking.objects.filter(
                user=request.user,
                status__in=['confirmed', 'attended'],
            ).values_list('workshop_id', flat=True)
        )

    # Depuis la page de détail, on n'exporte que l'atelier demandé.
    workshop_id = request.GET.get('workshop')
    if workshop_id:
        try:
            workshops = workshops.filter(pk=int(workshop_id))
        except (TypeError, ValueError):
            pass

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
        if ws.mode == 'onsite':
            location = ws.room
        elif ws.mode == 'online':
            if role in ('admin', 'mentor') or ws.pk in confirmed_meeting_ids:
                location = ws.meeting_url
            else:
                location = 'En ligne (lien après confirmation)'
        else:
            location = 'En ligne (replay)'
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


# ---------------------------------------------------------------------------
# Quiz de compréhension (mode replay)
# ---------------------------------------------------------------------------

@login_required
def workshop_quiz(request, pk):
    """Affiche le quiz d'un atelier enregistré pour un étudiant inscrit."""
    ws = get_object_or_404(Workshop, pk=pk)
    if ws.mode != Workshop.Mode.RECORDED:
        messages.error(request, 'Le quiz est uniquement disponible pour les ateliers en replay.')
        return redirect('workshops:detail', slug=ws.slug)

    booking = get_object_or_404(Booking, workshop=ws, user=request.user,
                                status__in=['confirmed', 'attended'])
    questions = list(ws.quiz_questions.all())

    context = {
        'workshop':       ws,
        'booking':        booking,
        'questions':      questions,
        'workshop_base_template': _workshop_base_template(request.user),
    }
    return render(request, 'workshops/quiz.html', context)


@login_required
@require_POST
def workshop_quiz_submit(request, pk):
    """Traite la soumission du quiz et calcule le score."""
    ws = get_object_or_404(Workshop, pk=pk)
    questions = list(ws.quiz_questions.all())

    if not questions:
        messages.error(request, 'Aucune question de quiz configurée pour cet atelier.')
        return redirect('workshops:detail', slug=ws.slug)

    score = 0
    results = []
    for q in questions:
        user_answer = request.POST.get(f'question_{q.pk}')
        correct = q.options()[q.correct_index]
        is_correct = (user_answer is not None and int(user_answer) == q.correct_index)
        if is_correct:
            score += 1
        results.append({
            'question': q,
            'user_answer': user_answer,
            'correct_answer': correct,
            'is_correct': is_correct,
            'explanation': q.explanation,
        })

    percentage = round(100 * score / len(questions))

    # Marquer l'atelier comme complété si score >= 80%
    booking = get_object_or_404(Booking, workshop=ws, user=request.user,
                                status__in=['confirmed', 'attended'])
    if percentage >= 80 and booking.status != 'attended':
        booking.status = 'attended'
        booking.attended_at = timezone.now()
        booking.save(update_fields=['status', 'attended_at'])
        messages.success(
            request,
            f'Quiz réussi avec {score}/{len(questions)} ({percentage}%) ! '
            f'Présence validée et certificat disponible.'
        )
    else:
        messages.warning(
            request,
            f'Quiz : {score}/{len(questions)} ({percentage}%). '
            f'Il faut 80% pour valider la présence.'
        )

    context = {
        'workshop':             ws,
        'booking':              booking,
        'questions':            questions,
        'results':              results,
        'score':                score,
        'total':                len(questions),
        'percentage':           percentage,
        'passed':               percentage >= 80,
        'workshop_base_template': _workshop_base_template(request.user),
    }
    return render(request, 'workshops/quiz_result.html', context)


# ---------------------------------------------------------------------------
# Quiz de compréhension — gestion des questions (admin/mentor/créateur)
# ---------------------------------------------------------------------------

@login_required
def workshop_quiz_manage(request, pk):
    """Liste et gestion des questions de quiz d'un atelier."""
    ws = get_object_or_404(Workshop, pk=pk)
    if not _can_manage(request.user, ws):
        raise PermissionDenied
    if ws.mode != Workshop.Mode.RECORDED:
        messages.error(request, 'Le quiz est uniquement disponible pour les ateliers en replay.')
        return redirect('workshops:detail', slug=ws.slug)

    questions = ws.quiz_questions.all().order_by('created_at')
    return render(request, 'workshops/quiz_manage.html', {
        'workshop': ws,
        'questions': questions,
        'workshop_base_template': _workshop_base_template(request.user),
    })


@login_required
def workshop_quiz_question_add(request, pk):
    """Ajouter une question de quiz."""
    ws = get_object_or_404(Workshop, pk=pk)
    if not _can_manage(request.user, ws):
        raise PermissionDenied
    if ws.mode != Workshop.Mode.RECORDED:
        messages.error(request, 'Le quiz est uniquement disponible pour les ateliers en replay.')
        return redirect('workshops:detail', slug=ws.slug)

    if request.method == 'POST':
        question = request.POST.get('question', '').strip()
        option_a = request.POST.get('option_a', '').strip()
        option_b = request.POST.get('option_b', '').strip()
        option_c = request.POST.get('option_c', '').strip()
        option_d = request.POST.get('option_d', '').strip()
        correct_index = int(request.POST.get('correct_index', 0))
        explanation = request.POST.get('explanation', '').strip()

        if not all([question, option_a, option_b, option_c, option_d]):
            messages.error(request, 'Tous les champs sont requis.')
        else:
            WorkshopQuiz.objects.create(
                workshop=ws,
                question=question,
                option_a=option_a,
                option_b=option_b,
                option_c=option_c,
                option_d=option_d,
                correct_index=correct_index,
                explanation=explanation,
                created_by=request.user,
            )
            messages.success(request, 'Question ajoutée avec succès.')
            return redirect('workshops:quiz_manage', pk=pk)

    # Pré-remplissage depuis les paramètres GET (génération IA)
    prefill = None
    if request.GET.get('question'):
        prefill = type('obj', (object,), {
            'question': request.GET.get('question', ''),
            'option_a': request.GET.get('option_a', ''),
            'option_b': request.GET.get('option_b', ''),
            'option_c': request.GET.get('option_c', ''),
            'option_d': request.GET.get('option_d', ''),
            'correct_index': int(request.GET.get('correct_index', 0)),
            'explication': request.GET.get('explication', ''),
        })()

    return render(request, 'workshops/quiz_question_form.html', {
        'workshop': ws,
        'action': 'Ajouter',
        'question': prefill,
        'workshop_base_template': _workshop_base_template(request.user),
    })


@login_required
def workshop_quiz_question_edit(request, pk, qid):
    """Éditer une question de quiz."""
    ws = get_object_or_404(Workshop, pk=pk)
    question = get_object_or_404(WorkshopQuiz, pk=qid, workshop=ws)
    if not _can_manage(request.user, ws):
        raise PermissionDenied

    if request.method == 'POST':
        question.question = request.POST.get('question', '').strip()
        question.option_a = request.POST.get('option_a', '').strip()
        question.option_b = request.POST.get('option_b', '').strip()
        question.option_c = request.POST.get('option_c', '').strip()
        question.option_d = request.POST.get('option_d', '').strip()
        question.correct_index = int(request.POST.get('correct_index', 0))
        question.explanation = request.POST.get('explanation', '').strip()
        question.save()
        messages.success(request, 'Question mise à jour.')
        return redirect('workshops:quiz_manage', pk=pk)

    return render(request, 'workshops/quiz_question_form.html', {
        'workshop': ws,
        'question': question,
        'action': 'Modifier',
        'workshop_base_template': _workshop_base_template(request.user),
    })


@login_required
def workshop_quiz_question_delete(request, pk, qid):
    """Supprimer une question de quiz."""
    ws = get_object_or_404(Workshop, pk=pk)
    question = get_object_or_404(WorkshopQuiz, pk=qid, workshop=ws)
    if not _can_manage(request.user, ws):
        raise PermissionDenied
    question.delete()
    messages.success(request, 'Question supprimée.')
    return redirect('workshops:quiz_manage', pk=pk)

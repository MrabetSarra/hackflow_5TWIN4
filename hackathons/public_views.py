from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import role_required

from . import services
from .agenda import build_agenda, parse_month
from .models import Challenge, HackathonProfile, Registration, Track
from .views import page, phase_filter, with_counts

viewer_only = role_required('student', 'mentor')

VISIBLE_STATUSES = (HackathonProfile.Status.PUBLISHED,)


def visible_hackathons():
    return HackathonProfile.objects.filter(status__in=VISIBLE_STATUSES)


def _my_challenge_ids(user):
    if user.role != 'student':
        return set()
    return set(Registration.objects.filter(user=user, status=Registration.Status.CONFIRMED).values_list('challenge_id', flat=True))


def _has_registration(user, hackathon):
    return user.role == 'student' and Registration.objects.filter(
        user=user, challenge__hackathon=hackathon, status=Registration.Status.CONFIRMED).exists()


def _visible_challenge(pk):
    return get_object_or_404(
        Challenge.objects.select_related('hackathon', 'hackathon__track', 'hackathon__event'),
        pk=pk, status=Challenge.Status.PUBLISHED, hackathon__status__in=VISIBLE_STATUSES,
    )


def _published_challenges(h):
    return h.published_challenges.prefetch_related(
        'schedule_items__mentor', 'flash_announcements', 'resources')


@viewer_only
def catalog(request):
    qs = with_counts(visible_hackathons(), published_only=True)
    q = request.GET.get('q', '').strip()
    track = request.GET.get('track', '').strip()
    phase = request.GET.get('phase', '').strip()
    if q:
        qs = qs.filter(Q(event__name__icontains=q) | Q(track__name__icontains=q))
    if track.isdigit():
        qs = qs.filter(track_id=int(track))
    qs = phase_filter(qs, phase)
    tracks = Track.objects.filter(hackathons__status__in=VISIBLE_STATUSES).distinct().order_by('name')
    return page(request, 'hackathons/public/catalog.html', {
        'hackathons': qs, 'tracks': tracks, 'q': q, 'track': track, 'phase': phase,
    })


@viewer_only
def hackathon_detail(request, slug):
    h = get_object_or_404(visible_hackathons().select_related('track', 'event'), slug=slug)
    my_registration = None
    if request.user.role == 'student':
        my_registration = Registration.objects.filter(
            challenge__hackathon=h, user=request.user, status=Registration.Status.CONFIRMED,
        ).select_related('challenge').first()
    countdown_target = h.starts_at if h.phase == 'upcoming' else h.ends_at if h.phase == 'ongoing' else None
    return page(request, 'hackathons/public/hackathon_detail.html', {
        'h': h, 'challenges': _published_challenges(h), 'mine': _my_challenge_ids(request.user),
        'countdown_target': countdown_target, 'my_registration': my_registration,
        'has_registration': my_registration is not None,
    })


@viewer_only
def challenge_detail(request, pk):
    challenge = _visible_challenge(pk)
    my_registration = None
    if request.user.role == 'student':
        my_registration = challenge.registrations.filter(user=request.user, status=Registration.Status.CONFIRMED).first()
    return page(request, 'hackathons/public/challenge_detail.html', {
        'h': challenge.hackathon, 'c': challenge, 'my_registration': my_registration,
        'mine': _my_challenge_ids(request.user), 'has_registration': _has_registration(request.user, challenge.hackathon),
    })


@role_required('student')
def challenge_register(request, pk):
    challenge = _visible_challenge(pk)
    if request.method == 'POST':
        try:
            services.register(request.user, challenge)
        except services.RegistrationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f'Inscription confirmée au challenge « {challenge.title} ».')
            return redirect('hackathons:my_registrations')
        return redirect('hackathons:challenge_detail', pk=pk)
    return page(request, 'hackathons/public/confirm_registration.html', {
        'challenge': challenge, 'h': challenge.hackathon, 'team': services.team_for(request.user, challenge.hackathon),
    })


@role_required('student')
@require_POST
def registration_cancel(request, pk):
    registration = get_object_or_404(Registration, pk=pk, user=request.user)
    try:
        services.cancel(registration)
    except services.RegistrationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'Inscription annulée.')
    return redirect('hackathons:my_registrations')


@role_required('student')
def my_registrations(request):
    regs = Registration.objects.filter(user=request.user).select_related(
        'challenge', 'challenge__hackathon', 'challenge__hackathon__event', 'team')
    today = timezone.localdate()
    first = parse_month(request.GET.get('month', ''), today)
    return page(request, 'hackathons/public/my_registrations.html', {
        'registrations': regs, 'agenda': build_agenda(regs, first, today),
        'weekdays': ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'],
    })

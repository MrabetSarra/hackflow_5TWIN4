from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from student.models import Notification

from .forms import (
    ChallengeForm, FlashAnnouncementForm, HackathonForm, MentorFeedbackForm,
    ResourceForm, ScheduleItemForm,
)
from .models import (
    Challenge, Favorite, FlashAnnouncement, HackathonProfile, HackathonResource,
    MentorFeedback, Registration, ScheduleItem, Track,
)

organizer_only = role_required('admin', 'organization')

LAYOUTS = {
    'student': 'layouts/base_student.html',
    'mentor': 'layouts/base_mentor.html',
}


def page(request, template, context=None, status=200):
    """Rend une page du module dans le layout correspondant au rôle de l'utilisateur."""
    role = getattr(request.user, 'role', 'student')
    ctx = {
        'base_layout': LAYOUTS.get(role, 'layouts/base_admin.html'),
        'page_template': template,
        'is_organizer': role in ('admin', 'organization'),
        'is_mentor': role == 'mentor',
        'is_student': role == 'student',
    }
    ctx.update(context or {})
    return render(request, 'hackathons/shell.html', ctx, status=status)


def phase_filter(qs, phase):
    now = timezone.now()
    if phase == 'upcoming':
        return qs.filter(event__starts_at__gt=now)
    if phase == 'ongoing':
        return qs.filter(event__starts_at__lte=now, event__ends_at__gte=now)
    if phase == 'finished':
        return qs.filter(event__ends_at__lt=now)
    return qs


def with_counts(qs, published_only=False):
    challenge_filter = Q(challenges__status=Challenge.Status.PUBLISHED) if published_only else None
    return qs.select_related('track', 'event').annotate(
        challenge_count=Count('challenges', filter=challenge_filter, distinct=True),
    )


# ------------------------------------------------------------ Hackathons

HACKATHON_AI_CONFIG = {
    'feature': 'hackathon_draft', 'title_input': 'id_name', 'track_input': 'id_track_name',
    'fields': [
        {'key': 'short_description', 'label': 'Description courte', 'input': 'id_short_description'},
        {'key': 'description', 'label': 'Description complète', 'input': 'id_description'},
        {'key': 'rules', 'label': 'Règlement', 'input': 'id_rules'},
    ],
}

CHALLENGE_AI_FIELDS = [
    ('short_description', 'Description courte'), ('description', 'Description détaillée'), ('objectives', 'Objectifs'),
    ('problem_statement', 'Problématique'), ('constraints', 'Contraintes'), ('deliverables', 'Livrables attendus'),
    ('guidelines', 'Consignes spécifiques'), ('technologies', 'Technologies recommandées'),
]


def challenge_ai_config(hackathon):
    return {
        'feature': 'challenge_draft', 'title_input': 'id_title', 'hackathon_id': hackathon.pk,
        'difficulty_input': 'id_difficulty', 'reward_input': 'id_reward',
        'fields': [{'key': key, 'label': label, 'input': f'id_{key}'} for key, label in CHALLENGE_AI_FIELDS],
    }

@organizer_only
def hackathon_list(request):
    qs = with_counts(HackathonProfile.objects.all())
    q = request.GET.get('q', '').strip()
    track = request.GET.get('track', '')
    status = request.GET.get('status', '')
    phase = request.GET.get('phase', '')
    if q:
        qs = qs.filter(Q(event__name__icontains=q) | Q(track__name__icontains=q))
    if track.isdigit():
        qs = qs.filter(track_id=int(track))
    if status in HackathonProfile.Status.values:
        qs = qs.filter(status=status)
    qs = phase_filter(qs, phase)
    return page(request, 'hackathons/manage/hackathon_list.html', {
        'hackathons': qs, 'tracks': Track.objects.filter(hackathons__isnull=False).distinct().order_by('name'),
        'q': q, 'track': track, 'status': status, 'phase': phase,
        'statuses': [(HackathonProfile.Status.DRAFT, 'Brouillon'), (HackathonProfile.Status.PUBLISHED, 'Publié')],
    })


@organizer_only
def hackathon_form(request, pk=None):
    profile = get_object_or_404(HackathonProfile, pk=pk) if pk else None
    form = HackathonForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        profile = form.save(organizer=request.user)
        messages.success(request, f'Hackathon « {profile.title} » enregistré.')
        return redirect('hackathons:hackathon_manage', pk=profile.pk)
    back = reverse('hackathons:hackathon_manage', args=[profile.pk]) if profile else reverse('hackathons:hackathon_list')
    return page(request, 'hackathons/manage/form.html', {
        'form': form, 'title': 'Modifier le hackathon' if profile else 'Nouveau hackathon', 'multipart': True,
        'back_href': back, 'track_suggestions': Track.objects.order_by('name').values_list('name', flat=True),
        'map_picker': True, 'ai_config': HACKATHON_AI_CONFIG, 'banner_ai': True,
    })


@organizer_only
def hackathon_manage(request, pk):
    profile = get_object_or_404(HackathonProfile.objects.select_related('track', 'event'), pk=pk)
    return page(request, 'hackathons/manage/hackathon_detail.html', {
        'h': profile,
        'challenges': profile.challenges.prefetch_related('registrations'),
        'participants': Registration.objects.filter(
            challenge__hackathon=profile, status=Registration.Status.CONFIRMED).values('user').distinct().count(),
    })


@organizer_only
@require_POST
def hackathon_status(request, pk):
    profile = get_object_or_404(HackathonProfile, pk=pk)
    action = request.POST.get('action')
    S, C = HackathonProfile.Status, Challenge.Status
    if action not in ('publish', 'publish_all', 'unpublish'):
        raise Http404
    with transaction.atomic():
        if action == 'unpublish':
            profile.status = S.DRAFT
            profile.save(update_fields=['status'])
            reverted = profile.challenges.filter(status=C.PUBLISHED).update(status=C.DRAFT)
            messages.success(request, f'Hackathon dépublié ({reverted} challenge(s) repassé(s) en brouillon).')
        elif action == 'publish_all':
            profile.status = S.PUBLISHED
            profile.save(update_fields=['status'])
            published = profile.challenges.filter(status=C.DRAFT).update(status=C.PUBLISHED)
            messages.success(request, f'Hackathon publié avec {published} challenge(s).')
        else:
            profile.status = S.PUBLISHED
            profile.save(update_fields=['status'])
            messages.success(request, 'Hackathon publié. Ses challenges restent dans leur état actuel.')
    return redirect('hackathons:hackathon_manage', pk=pk)


@organizer_only
@require_POST
def hackathon_stage(request, pk):
    profile = get_object_or_404(HackathonProfile, pk=pk)
    stage = request.POST.get('stage')
    if stage not in HackathonProfile.Stage.values:
        raise Http404
    profile.stage = stage
    profile.save(update_fields=['stage'])
    messages.success(request, f'Étape du hackathon : {profile.get_stage_display()}.')
    return redirect('hackathons:hackathon_manage', pk=pk)


@organizer_only
def hackathon_delete(request, pk):
    profile = get_object_or_404(HackathonProfile.objects.select_related('event'), pk=pk)
    event = profile.event
    reasons = []
    if event.teams.exists() or event.registrations.exists():
        reasons.append("l'événement est utilisé par d'autres modules (équipes ou inscriptions)")
    back = reverse('hackathons:hackathon_manage', args=[pk])
    if request.method == 'POST':
        if reasons:
            messages.error(request, 'Suppression impossible : ' + ' ; '.join(reasons) + '.')
            return redirect(back)
        with transaction.atomic():
            participant_ids = Registration.objects.filter(
                challenge__hackathon=profile, status=Registration.Status.CONFIRMED,
            ).values_list('user_id', flat=True).distinct()
            notifications = [
                Notification(
                    user_id=user_id,
                    title='Hackathon annulé',
                    message=f'Le hackathon « {profile.title} » a été annulé. Vos inscriptions à ses challenges ont été supprimées.',
                    icon='bi-calendar-x-fill',
                    url='/hackathons/',
                )
                for user_id in participant_ids
            ]
            Notification.objects.bulk_create(notifications)
            event.delete()
        if notifications:
            messages.success(request, f'Hackathon supprimé. {len(notifications)} étudiant(s) ont été avertis.')
        else:
            messages.success(request, 'Hackathon supprimé.')
        return redirect('hackathons:hackathon_list')
    return page(request, 'hackathons/manage/confirm.html', {
        'title': 'Supprimer le hackathon', 'object_label': profile.title,
        'warning': ('Suppression impossible : ' + ' ; '.join(reasons) + '.') if reasons else
               'Le hackathon, ses challenges et contenus seront supprimés. Chaque étudiant inscrit recevra une notification.',
        'blocked': bool(reasons), 'back_href': back,
    })


# ------------------------------------------------------------- Challenges

@organizer_only
def challenge_form(request, hackathon_id, pk=None):
    h = get_object_or_404(HackathonProfile, pk=hackathon_id)
    challenge = get_object_or_404(Challenge, pk=pk, hackathon=h) if pk else None
    form = ChallengeForm(request.POST or None, instance=challenge, hackathon=h)
    if request.method == 'POST' and form.is_valid():
        challenge = form.save()
        messages.success(request, f'Challenge « {challenge.title} » enregistré.')
        return redirect('hackathons:challenge_manage', hackathon_id=h.pk, pk=challenge.pk)
    back = reverse('hackathons:challenge_manage', args=[h.pk, challenge.pk]) if challenge \
        else reverse('hackathons:hackathon_manage', args=[h.pk])
    return page(request, 'hackathons/manage/form.html', {
        'form': form, 'title': 'Modifier le challenge' if challenge else 'Nouveau challenge', 'back_href': back,
        'ai_config': challenge_ai_config(h),
    })


# Clé d'URL -> (modèle, formulaire, libellé, singulier, icône, nom de la relation)
KINDS = {
    'schedule': (ScheduleItem, ScheduleItemForm, 'Programme', 'étape', 'bi-calendar-event-fill', 'schedule_items'),
    'announcements': (FlashAnnouncement, FlashAnnouncementForm, 'Annonces flash', 'annonce', 'bi-megaphone-fill', 'flash_announcements'),
    'resources': (HackathonResource, ResourceForm, 'Ressources & starter kit', 'ressource', 'bi-box-seam-fill', 'resources'),
}


def _kind(kind):
    if kind not in KINDS:
        raise Http404
    return KINDS[kind]


@organizer_only
def challenge_manage(request, hackathon_id, pk):
    h = get_object_or_404(HackathonProfile.objects.select_related('track', 'event'), pk=hackathon_id)
    challenge = get_object_or_404(Challenge, pk=pk, hackathon=h)
    sections = [
        {'kind': kind, 'label': label, 'icon': icon, 'singular': singular,
         'items': getattr(challenge, related).all()}
        for kind, (_m, _f, label, singular, icon, related) in KINDS.items()
    ]
    return page(request, 'hackathons/manage/challenge_detail.html', {
        'h': h, 'challenge': challenge, 'sections': sections,
        'registrations': challenge.registrations.select_related('user', 'team'),
    })


@organizer_only
@require_POST
def challenge_status(request, hackathon_id, pk):
    challenge = get_object_or_404(Challenge, pk=pk, hackathon_id=hackathon_id)
    S = Challenge.Status
    targets = {'publish': S.PUBLISHED, 'unpublish': S.DRAFT}
    action = request.POST.get('action')
    if action not in targets:
        raise Http404
    challenge.status = targets[action]
    challenge.save(update_fields=['status'])
    messages.success(request, f'Challenge : {challenge.get_status_display().lower()}.')
    return redirect('hackathons:challenge_manage', hackathon_id=hackathon_id, pk=pk)


@organizer_only
def challenge_delete(request, hackathon_id, pk):
    challenge = get_object_or_404(Challenge, pk=pk, hackathon_id=hackathon_id)
    blocked = challenge.registrations.exists()
    back = reverse('hackathons:challenge_manage', args=[hackathon_id, pk])
    if request.method == 'POST':
        if blocked:
            messages.error(request, 'Ce challenge a des inscriptions : il ne peut pas être supprimé.')
            return redirect(back)
        challenge.delete()
        messages.success(request, 'Challenge supprimé.')
        return redirect('hackathons:hackathon_manage', pk=hackathon_id)
    return page(request, 'hackathons/manage/confirm.html', {
        'title': 'Supprimer le challenge', 'object_label': challenge.title, 'blocked': blocked,
        'warning': 'Ce challenge a des inscriptions : il ne peut pas être supprimé.' if blocked else
                   'Son programme, ses annonces et ses ressources seront supprimés.',
        'back_href': back,
    })


# ------------------------------------- Contenus rattachés à un challenge

def _challenge_back(challenge):
    return reverse('hackathons:challenge_manage', args=[challenge.hackathon_id, challenge.pk])


@organizer_only
def child_form(request, challenge_id, kind, pk=None):
    model, form_class, _label, singular, _icon, _related = _kind(kind)
    challenge = get_object_or_404(Challenge.objects.select_related('hackathon'), pk=challenge_id)
    obj = get_object_or_404(model, pk=pk, challenge=challenge) if pk else None
    form = form_class(request.POST or None, request.FILES or None, instance=obj, challenge=challenge, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'{singular.capitalize()} enregistré(e).')
        return redirect(f'{_challenge_back(challenge)}#tab-{kind}')
    return page(request, 'hackathons/manage/form.html', {
        'form': form, 'title': f"{'Modifier' if obj else 'Ajouter'} : {singular}", 'multipart': True,
        'back_href': f'{_challenge_back(challenge)}#tab-{kind}',
    })


@organizer_only
def child_delete(request, challenge_id, kind, pk):
    model, _form, _label, singular, _icon, _related = _kind(kind)
    challenge = get_object_or_404(Challenge.objects.select_related('hackathon'), pk=challenge_id)
    obj = get_object_or_404(model, pk=pk, challenge=challenge)
    back = f'{_challenge_back(challenge)}#tab-{kind}'
    if request.method == 'POST':
        obj.delete()
        messages.success(request, f'{singular.capitalize()} supprimé(e).')
        return redirect(back)
    return page(request, 'hackathons/manage/confirm.html', {
        'title': f'Supprimer : {singular}', 'object_label': str(obj), 'blocked': False, 'back_href': back,
    })


@role_required('student')
@require_POST
def favorite_toggle(request, kind, pk):
    if kind == 'hackathon':
        target = get_object_or_404(HackathonProfile, pk=pk, status=HackathonProfile.Status.PUBLISHED)
        lookup = {'user': request.user, 'hackathon': target, 'challenge__isnull': True}
        label = target.title
    elif kind == 'challenge':
        target = get_object_or_404(
            Challenge.objects.select_related('hackathon'), pk=pk, status=Challenge.Status.PUBLISHED,
            hackathon__status=HackathonProfile.Status.PUBLISHED,
        )
        lookup = {'user': request.user, 'challenge': target, 'hackathon__isnull': True}
        label = target.title
    else:
        raise Http404

    favorite = Favorite.objects.filter(**lookup).first()
    if favorite:
        favorite.delete()
        messages.success(request, f'« {label} » retiré de vos favoris.')
    else:
        Favorite.objects.create(user=request.user, **{kind: target})
        messages.success(request, f'« {label} » ajouté à vos favoris.')

    destination = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(destination, allowed_hosts={request.get_host()}):
        destination = reverse('hackathons:my_favorites')
    return redirect(destination)


@role_required('student')
def my_favorites(request):
    favorites = Favorite.objects.filter(user=request.user).select_related(
        'hackathon', 'hackathon__event', 'hackathon__track', 'challenge', 'challenge__hackathon',
        'challenge__hackathon__event', 'challenge__hackathon__track',
    )
    q = request.GET.get('q', '').strip()
    kind = request.GET.get('kind', '')
    track = request.GET.get('track', '')
    if kind == 'hackathon':
        favorites = favorites.filter(hackathon__isnull=False)
    elif kind == 'challenge':
        favorites = favorites.filter(challenge__isnull=False)
    if track.isdigit():
        favorites = favorites.filter(Q(hackathon__track_id=int(track)) | Q(challenge__hackathon__track_id=int(track)))
    if q:
        favorites = favorites.filter(
            Q(hackathon__event__name__icontains=q)
            | Q(hackathon__track__name__icontains=q)
            | Q(challenge__title__icontains=q)
            | Q(challenge__hackathon__event__name__icontains=q)
            | Q(challenge__hackathon__track__name__icontains=q)
        )
    tracks = Track.objects.filter(
        Q(hackathons__favorites__user=request.user)
        | Q(hackathons__challenges__favorites__user=request.user)
    ).distinct().order_by('name')
    return page(request, 'hackathons/public/my_favorites.html', {
        'favorites': favorites, 'q': q, 'kind': kind, 'track': track, 'tracks': tracks,
    })


@role_required('mentor')
def mentor_feedback_hackathon(request, pk):
    hackathon = get_object_or_404(HackathonProfile, pk=pk, status=HackathonProfile.Status.PUBLISHED)
    feedback = MentorFeedback.objects.filter(mentor=request.user, hackathon=hackathon).first()
    if request.method == 'POST':
        if feedback:
            messages.info(request, 'Votre avis existe déjà. Consultez-le ou supprimez-le avant d’en rédiger un nouveau.')
            return redirect('hackathons:mentor_feedback_hackathon', pk=hackathon.pk)
        form = MentorFeedbackForm(request.POST, instance=MentorFeedback(mentor=request.user, hackathon=hackathon))
        if form.is_valid():
            form.save()
            messages.success(request, 'Votre avis sur ce hackathon a été envoyé à l’équipe organisatrice.')
            return redirect('hackathons:hackathon_detail', slug=hackathon.slug)
    else:
        form = MentorFeedbackForm(instance=MentorFeedback(mentor=request.user, hackathon=hackathon))
    return page(request, 'hackathons/public/mentor_feedback_form.html', {
        'form': form, 'feedback': feedback, 'hackathon': hackathon, 'feedback_target': hackathon.title,
        'back_url': reverse('hackathons:hackathon_detail', args=[hackathon.slug]),
    })


@role_required('mentor')
def mentor_feedback_challenge(request, pk):
    challenge = get_object_or_404(
        Challenge.objects.select_related('hackathon', 'hackathon__event'),
        pk=pk, status=Challenge.Status.PUBLISHED, hackathon__status=HackathonProfile.Status.PUBLISHED,
    )
    feedback = MentorFeedback.objects.filter(mentor=request.user, challenge=challenge).first()
    if request.method == 'POST':
        if feedback:
            messages.info(request, 'Votre avis existe déjà. Consultez-le ou supprimez-le avant d’en rédiger un nouveau.')
            return redirect('hackathons:mentor_feedback_challenge', pk=challenge.pk)
        form = MentorFeedbackForm(request.POST, instance=MentorFeedback(mentor=request.user, challenge=challenge))
        if form.is_valid():
            form.save()
            messages.success(request, 'Votre avis sur ce challenge a été envoyé à l’équipe organisatrice.')
            return redirect('hackathons:hackathon_detail', slug=challenge.hackathon.slug)
    else:
        form = MentorFeedbackForm(instance=MentorFeedback(mentor=request.user, challenge=challenge))
    return page(request, 'hackathons/public/mentor_feedback_form.html', {
        'form': form, 'feedback': feedback, 'hackathon': challenge.hackathon, 'feedback_target': challenge.title,
        'back_url': reverse('hackathons:hackathon_detail', args=[challenge.hackathon.slug]),
    })


@role_required('mentor', 'admin', 'organization')
@require_POST
def mentor_feedback_delete(request, pk):
    if request.user.role in ('admin', 'organization'):
        feedback = get_object_or_404(MentorFeedback, pk=pk)
        feedback.delete()
        messages.success(request, 'L’avis mentor a été supprimé.')
        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
        return redirect('hackathons:mentor_feedback_list')
    feedback = get_object_or_404(MentorFeedback, pk=pk, mentor=request.user)
    hackathon = feedback.hackathon if feedback.hackathon_id else feedback.challenge.hackathon
    feedback.delete()
    messages.success(request, 'Votre avis a été supprimé. Vous pouvez en rédiger un nouveau.')
    return redirect('hackathons:hackathon_detail', slug=hackathon.slug)


@role_required('admin', 'organization')
def mentor_feedback_list(request):
    reviews = MentorFeedback.objects.select_related(
        'mentor', 'hackathon', 'hackathon__event', 'challenge', 'challenge__hackathon', 'challenge__hackathon__event',
    ).distinct()
    hackathon_id = request.GET.get('hackathon', '')
    target_type = request.GET.get('type', '')
    if hackathon_id.isdigit():
        reviews = reviews.filter(Q(hackathon_id=int(hackathon_id)) | Q(challenge__hackathon_id=int(hackathon_id)))
    if target_type == 'hackathon':
        reviews = reviews.filter(hackathon__isnull=False)
    elif target_type == 'challenge':
        reviews = reviews.filter(challenge__isnull=False)

    grouped = {}
    seen_mentors_by_hackathon = {}
    for review in reviews:
        target_hackathon = review.hackathon if review.hackathon_id else review.challenge.hackathon
        if target_hackathon not in grouped:
            grouped[target_hackathon] = []
            seen_mentors_by_hackathon[target_hackathon.pk] = set()

        # Remove duplicated mentor reviews: keep only the latest feedback per mentor per hackathon
        if review.mentor_id in seen_mentors_by_hackathon[target_hackathon.pk]:
            continue

        seen_mentors_by_hackathon[target_hackathon.pk].add(review.mentor_id)
        grouped[target_hackathon].append(review)

    review_groups = sorted(grouped.items(), key=lambda item: item[0].event.name.casefold())
    return page(request, 'hackathons/manage/mentor_feedback_list.html', {
        'review_groups': review_groups, 'hackathons': HackathonProfile.objects.select_related('event').order_by('event__name'),
        'selected_hackathon': hackathon_id, 'target_type': target_type,
    })

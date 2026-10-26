"""Organizer views for AI-assisted jury preparation and JuryScore-based ranking."""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from student.models import Hackathon, Submission, Team

from .models import JuryScore
from .project_evaluation import JUDGING_RUBRIC, ProjectEvaluationError, analyze_project_submission


def _reviewable_submissions():
    active_hackathon = Hackathon.objects.filter(is_active=True).order_by('-starts_at', '-pk').first()
    submissions = Submission.objects.select_related('team', 'team__hackathon', 'milestone').filter(
        status__in=(Submission.Status.SUBMITTED, Submission.Status.APPROVED, Submission.Status.REVISION),
        submitted_at__isnull=False,
    )
    if active_hackathon:
        submissions = submissions.filter(team__hackathon=active_hackathon)
    return active_hackathon, submissions


def build_ranking(active_hackathon):
    """Build ranking from JuryScore entries (single rating 1-5 per team)."""
    teams = list(
        Team.objects.filter(hackathon=active_hackathon).prefetch_related('jury_score')
        if active_hackathon
        else Team.objects.all().prefetch_related('jury_score')
    )
    scores_by_team = {
        js.team_id: js
        for js in JuryScore.objects.filter(
            team__hackathon=active_hackathon
        ).select_related('team') if active_hackathon
    }

    ranking = []
    for t in teams:
        js = scores_by_team.get(t.pk)
        ranking.append({
            'team': t.name,
            'team_id': t.pk,
            'category': t.category or 'Innovation',
            'rating': js.rating if js else None,
            'notes': js.notes if js else '',
            'scored': js is not None,
        })

    ranking.sort(key=lambda r: (not r['scored'], -(r['rating'] or 0), r['team'].casefold()))

    for i, row in enumerate(ranking, 1):
        row['rank'] = i
        if i == 1:
            row['award'] = '1er Prix'
            row['badge_color'] = 'warning'
        elif i == 2:
            row['award'] = '2e Prix'
            row['badge_color'] = 'secondary'
        elif i == 3:
            row['award'] = '3e Prix'
            row['badge_color'] = 'info'
        else:
            row['award'] = f'#{i} Finaliste'
            row['badge_color'] = 'light'

    podium = [r for r in ranking[:3] if r['scored']]
    return podium, ranking, scores_by_team


@role_required('admin', 'organization')
def judging(request):
    active_hackathon, submissions = _reviewable_submissions()
    podium, teams_ranking, scores_by_team = build_ranking(active_hackathon)
    return render(request, 'dashboard_admin/judging.html', {
        'active_hackathon': active_hackathon,
        'submissions': submissions.order_by('team__name', '-submitted_at', '-pk'),
        'judging_rubric': JUDGING_RUBRIC,
        'podium': podium,
        'teams_ranking': teams_ranking,
        'scores_by_team': scores_by_team,
        'evaluate_url_template': reverse('dashboard_admin:project_evaluate', args=[0]),
    })


@role_required('admin', 'organization')
@require_POST
def save_jury_score(request, team_id):
    """Save or update a jury rating for a team."""
    active_hackathon = Hackathon.objects.filter(is_active=True).order_by('-starts_at', '-pk').first()
    team = get_object_or_404(Team, pk=team_id)

    try:
        rating = max(1, min(5, int(request.POST.get('rating', 0))))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Note invalide (1–5 requis).'}, status=400)

    notes = request.POST.get('notes', '').strip()[:500]

    JuryScore.objects.update_or_create(
        team=team,
        defaults={
            'rating': rating,
            'notes': notes,
            'scored_by': request.user,
        },
    )

    podium, teams_ranking, _ = build_ranking(active_hackathon)
    winner = podium[0] if podium else None
    return JsonResponse({
        'ok': True,
        'teams_ranking': teams_ranking,
        'podium': podium,
        'winner': winner,
    })


@role_required('admin', 'organization')
@require_POST
def project_evaluate(request, submission_id):
    _, submissions = _reviewable_submissions()
    submission = get_object_or_404(submissions, pk=submission_id)
    try:
        result = analyze_project_submission(submission)
    except ProjectEvaluationError as exc:
        return JsonResponse({'error': str(exc)}, status=503)
    return JsonResponse(result)

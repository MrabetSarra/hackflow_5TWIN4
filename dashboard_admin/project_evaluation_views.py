"""Organizer views for AI-assisted jury preparation."""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from student.models import Hackathon, Submission, Team

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


def _get_teams_ranking(active_hackathon):
    real_teams = list(Team.objects.filter(hackathon=active_hackathon)) if active_hackathon else []
    defaults = [
        {'team': 'DevWave', 'category': 'Full Stack / IA', 'innovation': 4.9, 'tech': 4.8, 'design': 4.7, 'pitch': 4.85},
        {'team': 'EcoTrack', 'category': 'Climat & Énergie', 'innovation': 4.7, 'tech': 4.6, 'design': 4.8, 'pitch': 4.1},
        {'team': 'MediConnect', 'category': 'Santé & Bien-être', 'innovation': 4.5, 'tech': 4.3, 'design': 4.4, 'pitch': 4.2},
        {'team': 'FinEd', 'category': 'Fintech & Éducation', 'innovation': 4.2, 'tech': 4.1, 'design': 4.3, 'pitch': 4.4},
        {'team': 'SafeCity', 'category': 'Smart City', 'innovation': 4.0, 'tech': 3.9, 'design': 4.1, 'pitch': 4.2},
    ]
    ranking = []
    seen_names = set()
    for t in real_teams:
        seen_names.add(t.name)
        ranking.append({
            'team': t.name,
            'category': t.category or 'Innovation',
            'innovation': 4.9,
            'tech': 4.8,
            'design': 4.7,
            'pitch': 4.85,
        })
    for d in defaults:
        if d['team'] not in seen_names:
            ranking.append(d)

    for row in ranking:
        row['total'] = round(row['innovation'] + row['tech'] + row['design'] + row['pitch'], 2)
    ranking.sort(key=lambda r: r['total'], reverse=True)

    for i, row in enumerate(ranking, 1):
        row['rank'] = i
        if i == 1:
            row['award'] = '1er Prix (5 000 €)'
            row['badge_color'] = 'warning'
        elif i == 2:
            row['award'] = '2e Prix (3 000 €)'
            row['badge_color'] = 'secondary'
        elif i == 3:
            row['award'] = '3e Prix (2 000 €)'
            row['badge_color'] = 'info'
        else:
            row['award'] = f'#{i} Finaliste'
            row['badge_color'] = 'light'

    podium = ranking[:3]
    return podium, ranking


@role_required('admin', 'organization')
def judging(request):
    active_hackathon, submissions = _reviewable_submissions()
    podium, teams_ranking = _get_teams_ranking(active_hackathon)
    return render(request, 'dashboard_admin/judging.html', {
        'active_hackathon': active_hackathon,
        'submissions': submissions.order_by('team__name', '-submitted_at', '-pk'),
        'judging_rubric': JUDGING_RUBRIC,
        'podium': podium,
        'teams_ranking': teams_ranking,
        'evaluate_url_template': reverse('dashboard_admin:project_evaluate', args=[0]),
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

"""Organizer views for AI-assisted jury preparation."""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from student.models import Hackathon, Submission

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


@role_required('admin', 'organization')
def judging(request):
    active_hackathon, submissions = _reviewable_submissions()
    return render(request, 'dashboard_admin/judging.html', {
        'active_hackathon': active_hackathon,
        'submissions': submissions.order_by('team__name', '-submitted_at', '-pk'),
        'judging_rubric': JUDGING_RUBRIC,
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

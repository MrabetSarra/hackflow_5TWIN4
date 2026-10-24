"""Background AI task generation."""
import time

from django.db import transaction

from hackflow.celery import celery_app
from .ai_tasks import TaskSuggestionError, generate_tasks
from .models import AITaskJob


@celery_app.task(name='student.generate_ai_task_job')
def generate_ai_task_job(job_id):
    with transaction.atomic():
        job = AITaskJob.objects.select_for_update().select_related('team', 'user').filter(pk=job_id).first()
        if job is None or job.status == AITaskJob.Status.DONE:
            return
        job.status = AITaskJob.Status.RUNNING
        job.error_message = ''
        job.save(update_fields=['status', 'error_message'])

    started = time.perf_counter()
    try:
        result = generate_tasks(job)
    except TaskSuggestionError as exc:
        result, error = [], str(exc)[:500]
    except Exception:
        result, error = [], 'Task suggestions are unavailable right now. Please try again later.'
    else:
        error = ''

    with transaction.atomic():
        job = AITaskJob.objects.select_for_update().filter(pk=job_id).first()
        if job is None or job.status == AITaskJob.Status.DONE:
            return
        job.status = AITaskJob.Status.FAILED if error else AITaskJob.Status.DONE
        job.result = result
        job.error_message = error
        job.proposed_count = len(result)
        job.latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        job.save(update_fields=['status', 'result', 'error_message', 'proposed_count', 'latency_ms'])

"""Tâche Celery de l'assistant IA (exécutée de façon synchrone si Celery est en mode eager)."""
from hackflow.celery import celery_app


@celery_app.task(name='hackathons.run_ai_job')
def run_ai_job(job_id):
    from .ai_services import run_job
    run_job(job_id)

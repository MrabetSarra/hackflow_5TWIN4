"""Analyse IA des demandes d'aide en arrière-plan (Celery + Redis, ou thread en développement)."""
import logging
import os
import threading
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from hackflow.celery import celery_app

from .ai import TriageError, classify, model_name, suggest_mentor
from .models import RequestTriage

logger = logging.getLogger(__name__)

# Bien au-delà du délai maximal d'un appel au modèle (MENTOR_AI_TIMEOUT, 90 s par défaut).
STALE_AFTER = timedelta(minutes=3)


def ai_enabled():
    return os.environ.get('MENTOR_AI_ENABLED', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}


def run_triage(triage_id):
    """Analyse un ticket et enregistre le résultat ; ne lève jamais d'exception."""
    with transaction.atomic():
        triage = (RequestTriage.objects.select_for_update().select_related('help_request')
                  .filter(pk=triage_id).first())
        if triage is None or triage.status in (RequestTriage.Status.RUNNING, RequestTriage.Status.DONE):
            return
        triage.status = RequestTriage.Status.RUNNING
        triage.error_message = ''
        triage.save(update_fields=['status', 'error_message', 'updated_at'])

    help_request = triage.help_request
    try:
        result, latency_ms = classify(help_request.subject, help_request.description)
    except TriageError as exc:
        _finish(triage_id, status=RequestTriage.Status.FAILED, error_message=str(exc)[:500])
        return
    except Exception:  # erreur imprévue : on la journalise, l'application continue de fonctionner
        logger.exception('Mentor triage failed for request %s', help_request.pk)
        _finish(triage_id, status=RequestTriage.Status.FAILED, error_message='Analyse IA indisponible.')
        return

    _finish(
        triage_id, status=RequestTriage.Status.DONE, suggested_category=result['category'],
        suggested_urgency=result['urgency'], summary=result['summary'], latency_ms=latency_ms,
        model_name=model_name(), suggested_mentor=suggest_mentor(result['category']),
    )


def _finish(triage_id, **fields):
    RequestTriage.objects.filter(pk=triage_id).update(**fields)


@celery_app.task(name='mentor.run_triage')
def triage_request(triage_id):
    run_triage(triage_id)


# Une analyse à la fois en développement : SQLite refuse deux transactions d'écriture
# simultanées (« database is locked ») et Ollama traite de toute façon un appel à la fois.
_thread_lock = threading.Lock()


def _run_in_thread(triage_id):
    try:
        with _thread_lock:
            run_triage(triage_id)
    except Exception:  # le ticket reste « en attente » et sera relancé (voir ensure_triages)
        logger.exception('Mentor triage thread failed for triage %s', triage_id)
    finally:
        close_old_connections()


def enqueue_triage(triage_id):
    """Lance l'analyse sans bloquer la requête HTTP du mentor.

    Avec Redis (production), la tâche part dans Celery. En développement, Celery
    s'exécute en mode « eager » (synchrone) : on utilise alors un thread pour que
    la page s'affiche tout de suite pendant que le modèle travaille.
    """
    if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        threading.Thread(target=_run_in_thread, args=(triage_id,), daemon=True).start()
    else:
        triage_request.delay(triage_id)


def ensure_triages(help_requests):
    """Crée et lance l'analyse des tickets en attente qui n'en ont pas encore.

    Une analyse restée « en cours » trop longtemps a été interrompue (redémarrage du
    serveur ou du worker) : elle est relancée au lieu d'afficher un chargement sans fin.
    """
    if not ai_enabled():
        return
    stale_before = timezone.now() - STALE_AFTER
    unfinished = (RequestTriage.Status.PENDING, RequestTriage.Status.RUNNING)
    for help_request in help_requests:
        if help_request.status == help_request.Status.RESOLVED:
            continue
        triage = getattr(help_request, 'triage', None)
        if triage is None:
            if help_request.status != help_request.Status.PENDING:
                continue
            triage, created = RequestTriage.objects.get_or_create(help_request=help_request)
            help_request.triage = triage
            if created:
                transaction.on_commit(lambda pk=triage.pk: enqueue_triage(pk))
        elif triage.status in unfinished and triage.updated_at < stale_before:
            restarted = RequestTriage.objects.filter(
                pk=triage.pk, status__in=unfinished, updated_at__lt=stale_before,
            ).update(status=RequestTriage.Status.PENDING, updated_at=timezone.now())
            if restarted:
                triage.status = RequestTriage.Status.PENDING
                transaction.on_commit(lambda pk=triage.pk: enqueue_triage(pk))


def retry_triage(triage):
    """Relance une analyse échouée."""
    RequestTriage.objects.filter(pk=triage.pk, status=RequestTriage.Status.FAILED).update(
        status=RequestTriage.Status.PENDING, error_message='')
    transaction.on_commit(lambda: enqueue_triage(triage.pk))

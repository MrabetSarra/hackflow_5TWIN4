"""Tâches d'arrière-plan du module Ateliers.

La génération du PDF de certificat est déléguée à Celery après le commit
de la transaction. En développement (``CELERY_TASK_ALWAYS_EAGER=True``),
la tâche s'exécute immédiatement ; en production, un worker la prend en
charge, ce qui évite de bloquer la réponse HTTP du check-in.
"""

import logging

from hackflow.celery import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name='workshops.generate_certificate_pdf')
def generate_certificate_pdf(certificate_id):
    """Génère et attache le PDF d'un certificat s'il n'existe pas encore."""
    from .models import Certificate
    from .services.certificate import attach_pdf_to_certificate

    certificate = Certificate.objects.filter(pk=certificate_id).first()
    if certificate is None or certificate.is_revoked or certificate.pdf:
        return False

    try:
        return attach_pdf_to_certificate(certificate)
    except Exception:
        logger.exception(
            'Échec de génération du PDF du certificat %s', certificate_id)
        return False

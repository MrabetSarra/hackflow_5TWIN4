"""
workshops/signals.py
=====================
post_save sur Certificate → planifie la génération du PDF + vérifie les badges.
post_save sur Booking     → vérifie les badges early-bird / top-reviewer.
"""

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _generate_pdf_after_commit(certificate_id):
    """Planifie la génération PDF, avec repli synchrone si Celery échoue."""
    from workshops.tasks import generate_certificate_pdf

    try:
        generate_certificate_pdf.delay(certificate_id)
    except Exception as exc:
        logger.warning(
            'Celery indisponible pour le certificat %s : %s',
            certificate_id, exc,
        )
        from workshops.models import Certificate
        from workshops.services.certificate import attach_pdf_to_certificate

        certificate = Certificate.objects.filter(pk=certificate_id).first()
        if certificate and not certificate.pdf and not certificate.is_revoked:
            try:
                attach_pdf_to_certificate(certificate)
            except Exception:
                logger.exception(
                    'Impossible de générer le PDF du certificat %s',
                    certificate_id,
                )


@receiver(post_save, sender='workshops.Certificate')
def on_certificate_created(sender, instance, created, **kwargs):
    if not created:
        return

    from workshops.services.badges import (
        check_badges_for_certificate,
        ensure_badges_exist,
    )

    ensure_badges_exist()
    check_badges_for_certificate(instance)

    # Le PDF est généré après le commit : la transaction de check-in reste
    # courte et la réponse HTTP n'attend pas fpdf2/qrcode.
    transaction.on_commit(
        lambda certificate_id=instance.pk:
        _generate_pdf_after_commit(certificate_id)
    )


@receiver(post_save, sender='workshops.Booking')
def on_booking_saved(sender, instance, created, **kwargs):
    update_fields = kwargs.get('update_fields') or set()
    # Une simple progression de replay ne doit pas relancer les badges.
    if update_fields and set(update_fields) <= {'replay_progress'}:
        return

    from workshops.services.badges import (
        check_badges_for_booking,
        ensure_badges_exist,
    )

    ensure_badges_exist()
    check_badges_for_booking(instance)

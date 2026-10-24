"""
workshops/signals.py
=====================
post_save sur Certificate → génère le PDF + vérifie les badges.
post_save sur Booking     → vérifie les badges early-bird / top-reviewer.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='workshops.Certificate')
def on_certificate_created(sender, instance, created, **kwargs):
    if not created:
        return

    # Génération asynchrone du PDF (synchrone ici, assez rapide)
    from workshops.services.certificate import attach_pdf_to_certificate
    from workshops.services.badges import check_badges_for_certificate, ensure_badges_exist

    ensure_badges_exist()
    attach_pdf_to_certificate(instance)
    check_badges_for_certificate(instance)


@receiver(post_save, sender='workshops.Booking')
def on_booking_saved(sender, instance, created, **kwargs):
    from workshops.services.badges import check_badges_for_booking, ensure_badges_exist
    ensure_badges_exist()
    check_badges_for_booking(instance)

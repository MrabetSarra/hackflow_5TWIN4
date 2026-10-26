from django.db import transaction
from django.utils import timezone

from student.models import TeamMembership

from .models import HackathonProfile, Registration

# Règle métier retenue : une équipe (et un étudiant) ne participe qu'à un Challenge par Hackathon.
ONE_CHALLENGE_PER_HACKATHON = True


class RegistrationError(Exception):
    pass


def team_for(user, hackathon):
    membership = (
        TeamMembership.objects.filter(user=user, team__hackathon=hackathon.event, team__is_archived=False)
        .select_related('team').first()
    )
    return membership.team if membership else None


def register(user, challenge):
    hackathon = challenge.hackathon
    now = timezone.now()
    with transaction.atomic():
        if not hackathon.is_published or challenge.status != challenge.Status.PUBLISHED:
            raise RegistrationError("Ce challenge n'est pas ouvert aux inscriptions.")
        if hackathon.phase in ('cancelled', 'finished'):
            raise RegistrationError('Ce hackathon est terminé ou annulé.')
        if now > challenge.deadline or not hackathon.registration_open:
            raise RegistrationError("La date limite d'inscription est dépassée.")
        if challenge.registrations.filter(user=user, status=Registration.Status.CONFIRMED).exists():
            raise RegistrationError('Vous êtes déjà inscrit à ce challenge.')

        team = team_for(user, hackathon)
        if ONE_CHALLENGE_PER_HACKATHON:
            mine = Registration.objects.filter(
                challenge__hackathon=hackathon, status=Registration.Status.CONFIRMED,
            )
            if mine.filter(user=user).exists():
                raise RegistrationError('Vous êtes déjà inscrit à un challenge de ce hackathon. Annulez-le avant de changer.')
            if team and mine.filter(team=team).exclude(challenge=challenge).exists():
                raise RegistrationError('Votre équipe participe déjà à un autre challenge de ce hackathon.')

        overlapping = Registration.objects.filter(
            user=user, status=Registration.Status.CONFIRMED,
            challenge__hackathon__event__starts_at__lt=hackathon.ends_at,
            challenge__hackathon__event__ends_at__gt=hackathon.starts_at,
        ).exclude(challenge__hackathon=hackathon).exclude(
            challenge__hackathon__status=HackathonProfile.Status.CANCELLED,
        ).select_related('challenge__hackathon__event').first()
        if overlapping:
            raise RegistrationError(
                f'Vous êtes déjà inscrit au hackathon « {overlapping.challenge.hackathon.title} » '
                'qui a lieu aux mêmes dates. Annulez cette inscription pour participer à celui-ci.'
            )

        if hackathon.max_participants:
            participants = Registration.objects.filter(
                challenge__hackathon=hackathon, status=Registration.Status.CONFIRMED,
            ).values('user').distinct().count()
            if participants >= hackathon.max_participants:
                raise RegistrationError('La capacité maximale du hackathon est atteinte.')

        return Registration.objects.create(challenge=challenge, user=user, team=team)


def cancel(registration):
    if registration.status != Registration.Status.CONFIRMED:
        raise RegistrationError('Cette inscription est déjà annulée.')
    if timezone.now() >= registration.challenge.hackathon.starts_at:
        raise RegistrationError("Le hackathon a commencé : l'annulation n'est plus possible.")
    registration.status = Registration.Status.CANCELLED
    registration.cancelled_at = timezone.now()
    registration.save(update_fields=['status', 'cancelled_at'])
    return registration

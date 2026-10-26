from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class JuryScore(models.Model):
    """
    Stores a single jury rating (1–5) per team.
    Replaces MentorFeedback which requires a HackathonProfile (not always present).
    Admin / jury enter scores on the judging page; results are shown on the results page.
    """
    team = models.OneToOneField(
        'student.Team',
        on_delete=models.CASCADE,
        related_name='jury_score',
    )
    rating = models.PositiveSmallIntegerField(
        'Note / 5',
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text='Note attribuée par le jury (1 à 5)',
    )
    notes = models.TextField('Commentaire jury', blank=True)
    scored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
        verbose_name='Noté par',
    )
    scored_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'note jury'
        verbose_name_plural = 'notes jury'

    def __str__(self):
        return f'{self.team.name} — {self.rating}/5'

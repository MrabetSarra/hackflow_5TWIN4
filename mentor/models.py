from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum

# Grille de jugement par défaut : créée automatiquement par la migration 0002
# et reprise ici pour pouvoir la restaurer ou la tester.
DEFAULT_CRITERIA = [
    {
        'code': 'innovation',
        'name': 'Innovation et originalité',
        'description': "Caractère novateur de l'idée et originalité de la solution proposée.",
        'weight': 25,
        'order': 1,
    },
    {
        'code': 'technique',
        'name': 'Qualité technique',
        'description': "Architecture, qualité du code, robustesse et maîtrise des technologies.",
        'weight': 25,
        'order': 2,
    },
    {
        'code': 'design_ux',
        'name': 'Design et expérience utilisateur',
        'description': "Ergonomie, clarté de l'interface et qualité du parcours utilisateur.",
        'weight': 25,
        'order': 3,
    },
    {
        'code': 'valeur_presentation',
        'name': 'Valeur, usages et présentation',
        'description': "Utilité réelle, cas d'usage, modèle de valeur et qualité du pitch.",
        'weight': 25,
        'order': 4,
    },
]


class Criterion(models.Model):
    """Critère pondéré de la grille de jugement, partagé par le jury et les mentors."""

    class Scope(models.TextChoices):
        BOTH = 'both', 'Jury et mentors'
        JURY = 'jury', 'Jury uniquement'
        MENTOR = 'mentor', 'Mentors uniquement'

    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    weight = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text='Pondération en pourcentage.',
    )
    max_score = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    scope = models.CharField(max_length=10, choices=Scope.choices, default=Scope.BOTH)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'critère de jugement'
        verbose_name_plural = 'grille de jugement'

    def __str__(self):
        return f'{self.name} ({self.weight}%)'

    @classmethod
    def for_scope(cls, scope):
        """Critères actifs utilisables par le jury ou par les mentors."""
        return cls.objects.filter(is_active=True, scope__in=(scope, cls.Scope.BOTH))

    @classmethod
    def total_weight(cls, scope):
        return cls.for_scope(scope).aggregate(total=Sum('weight'))['total'] or 0

    @classmethod
    def ensure_default_grid(cls):
        """Crée les critères par défaut manquants sans écraser les modifications de l'admin."""
        for data in DEFAULT_CRITERIA:
            cls.objects.get_or_create(code=data['code'], defaults=data)

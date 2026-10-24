from django.db import migrations

# Données figées ici (et non importées de models.py) pour que la migration
# reste identique même si la grille par défaut évolue plus tard.
CRITERIA = [
    ('innovation', 'Innovation et originalité',
     "Caractère novateur de l'idée et originalité de la solution proposée.", 25, 1),
    ('technique', 'Qualité technique',
     "Architecture, qualité du code, robustesse et maîtrise des technologies.", 25, 2),
    ('design_ux', 'Design et expérience utilisateur',
     "Ergonomie, clarté de l'interface et qualité du parcours utilisateur.", 25, 3),
    ('valeur_presentation', 'Valeur, usages et présentation',
     "Utilité réelle, cas d'usage, modèle de valeur et qualité du pitch.", 25, 4),
]


def create_default_criteria(apps, schema_editor):
    Criterion = apps.get_model('mentor', 'Criterion')
    for code, name, description, weight, order in CRITERIA:
        Criterion.objects.get_or_create(
            code=code,
            defaults={'name': name, 'description': description, 'weight': weight, 'order': order},
        )


def remove_default_criteria(apps, schema_editor):
    Criterion = apps.get_model('mentor', 'Criterion')
    Criterion.objects.filter(code__in=[row[0] for row in CRITERIA]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('mentor', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_default_criteria, remove_default_criteria),
    ]

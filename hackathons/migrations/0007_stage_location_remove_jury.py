from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hackathons', '0006_delete_sponsor_evaluationcriterion'),
    ]

    operations = [
        migrations.DeleteModel(name='JuryMember'),
        migrations.AddField(
            model_name='hackathonprofile',
            name='stage',
            field=models.CharField(
                choices=[
                    ('registration_open', 'Inscriptions ouvertes'), ('registration_closed', 'Inscriptions closes'),
                    ('ongoing', 'En cours'), ('evaluation', 'Évaluation'), ('finished', 'Terminé'),
                ],
                default='registration_open', max_length=20, verbose_name='Étape du hackathon',
            ),
        ),
        migrations.AddField(model_name='hackathonprofile', name='latitude', field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='hackathonprofile', name='longitude', field=models.FloatField(blank=True, null=True)),
    ]

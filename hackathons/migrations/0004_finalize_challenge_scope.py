import django.db.models.deletion
from django.db import migrations, models

SCOPED = {
    'sponsor': 'sponsors',
    'jurymember': 'jury_members',
    'scheduleitem': 'schedule_items',
    'flashannouncement': 'flash_announcements',
    'hackathonresource': 'resources',
    'evaluationcriterion': 'criteria',
}


class Migration(migrations.Migration):

    dependencies = [
        ('hackathons', '0003_copy_items_to_challenges'),
    ]

    operations = [
        migrations.RemoveField(model_name=model, name='hackathon') for model in SCOPED
    ] + [
        migrations.AlterField(
            model_name=model,
            name='challenge',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name=related, to='hackathons.challenge',
            ),
        )
        for model, related in SCOPED.items()
    ]

from django.db import migrations

MODELS = ['Sponsor', 'JuryMember', 'ScheduleItem', 'FlashAnnouncement', 'HackathonResource', 'EvaluationCriterion']


def move_to_challenges(apps, schema_editor):
    """Chaque ancien élément du hackathon est dupliqué dans chacun de ses challenges."""
    Challenge = apps.get_model('hackathons', 'Challenge')
    for name in MODELS:
        Model = apps.get_model('hackathons', name)
        for item in list(Model.objects.filter(challenge__isnull=True)):
            challenge_ids = list(
                Challenge.objects.filter(hackathon_id=item.hackathon_id).order_by('pk').values_list('pk', flat=True))
            if not challenge_ids:
                item.delete()
                continue
            original_pk = item.pk
            for challenge_id in challenge_ids[1:]:
                item.pk = None
                item.challenge_id = challenge_id
                item.save()
            Model.objects.filter(pk=original_pk).update(challenge_id=challenge_ids[0])


class Migration(migrations.Migration):

    dependencies = [
        ('hackathons', '0002_challenge_scoped_fields'),
    ]

    operations = [
        migrations.RunPython(move_to_challenges, migrations.RunPython.noop),
    ]

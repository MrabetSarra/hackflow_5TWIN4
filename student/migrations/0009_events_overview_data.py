import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def register_existing_users_to_active_event(apps, schema_editor):
    Hackathon = apps.get_model('student', 'Hackathon')
    Registration = apps.get_model('student', 'HackathonRegistration')
    User = apps.get_model('accounts', 'User')
    active_event = Hackathon.objects.filter(
        is_active=True,
        ends_at__gte=django.utils.timezone.now(),
    ).order_by('starts_at').first()
    if not active_event:
        return
    user_ids = User.objects.filter(role__in=('student', 'mentor')).values_list('pk', flat=True)
    Registration.objects.bulk_create(
        [Registration(hackathon_id=active_event.pk, user_id=user_id) for user_id in user_ids],
        batch_size=500,
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0006_promote_existing_superusers'),
        ('student', '0008_announcement_delivery_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='hackathon',
            name='location',
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.CreateModel(
            name='HackathonRegistration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('registered_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('hackathon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='registrations', to='student.hackathon')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hackathon_registrations', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['registered_at', 'pk']},
        ),
        migrations.AddConstraint(
            model_name='hackathonregistration',
            constraint=models.UniqueConstraint(fields=('hackathon', 'user'), name='unique_hackathon_registration'),
        ),
        migrations.RunPython(register_existing_users_to_active_event, migrations.RunPython.noop),
    ]

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('hackathons', '0004_finalize_challenge_scope'),
    ]

    operations = [
        migrations.RemoveField(model_name='hackathonprofile', name='online_url'),
        migrations.RemoveField(model_name='challenge', name='category'),
        migrations.RemoveField(model_name='challenge', name='registration_deadline'),
    ]

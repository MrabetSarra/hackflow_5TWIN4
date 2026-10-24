from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('student', '0010_announcement_scheduled_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='announcement',
            name='is_draft',
            field=models.BooleanField(default=False),
        ),
    ]

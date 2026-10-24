from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('student', '0009_events_overview_data'),
    ]

    operations = [
        migrations.AddField(
            model_name='announcement',
            name='scheduled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

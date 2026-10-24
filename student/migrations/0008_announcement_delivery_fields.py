from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('student', '0007_submission_unique_team_milestone_submission'),
    ]

    operations = [
        migrations.AddField(
            model_name='announcement',
            name='body',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='announcement',
            name='audience',
            field=models.CharField(
                choices=[
                    ('all', 'Everyone'),
                    ('students', 'Students'),
                    ('mentors', 'Mentors'),
                    ('captains', 'Team captains'),
                ],
                default='all',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='announcement',
            name='priority',
            field=models.CharField(
                choices=[('info', 'Info'), ('important', 'Important'), ('urgent', 'Urgent')],
                default='info',
                max_length=9,
            ),
        ),
    ]

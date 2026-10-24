from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('career_opportunities', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='opportunitycollectionjob',
            name='discovered_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='opportunitycollectionjob',
            name='updated_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='opportunitycollectionjob',
            name='skipped_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddConstraint(
            model_name='opportunitycollectionjob',
            constraint=models.UniqueConstraint(
                fields=('source',),
                condition=models.Q(source__isnull=False, status='running', finished_at__isnull=True),
                name='career_one_running_job_per_source',
            ),
        ),
    ]

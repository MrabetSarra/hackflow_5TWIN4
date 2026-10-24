from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('career_opportunities', '0005_remove_opportunitycollectionjob_source_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='careerapplication',
            name='interview_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='careerapplication',
            name='organizer_update',
            field=models.CharField(blank=True, max_length=500),
        ),
    ]

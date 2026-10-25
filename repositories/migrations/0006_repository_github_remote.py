from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('repositories', '0005_aiusagelog_latency_ms_aiusagelog_model_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='repository',
            name='remote_provider',
            field=models.CharField(blank=True, choices=[('github', 'GitHub')], max_length=20),
        ),
        migrations.AddField(
            model_name='repository',
            name='remote_id',
            field=models.PositiveBigIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='repository',
            name='remote_node_id',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='repository',
            name='remote_owner',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='repository',
            name='remote_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='repository',
            name='remote_url',
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name='repository',
            name='clone_url',
            field=models.URLField(blank=True, max_length=500),
        ),
    ]

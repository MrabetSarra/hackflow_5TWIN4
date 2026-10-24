from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0006_promote_existing_superusers'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='preferred_roles',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='user',
            name='preferred_categories',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='user',
            name='availability_windows',
            field=models.JSONField(blank=True, default=list),
        ),
    ]

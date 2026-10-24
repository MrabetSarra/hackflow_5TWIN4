from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0004_user_profile_photo_cv'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('student', 'Étudiant'),
                    ('mentor', 'Mentor'),
                    ('admin', 'Administrateur'),
                    ('organization', 'Organization'),
                ],
                default='student',
                max_length=20,
            ),
        ),
    ]

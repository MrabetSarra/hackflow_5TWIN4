import accounts.models
import accounts.storage
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_passwordresetcode'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='profile_photo',
            field=models.ImageField(blank=True, null=True, upload_to='profile_photos/', validators=[django.core.validators.FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp']), accounts.models.validate_profile_photo_size]),
        ),
        migrations.AddField(
            model_name='user',
            name='cv',
            field=models.FileField(blank=True, null=True, storage=accounts.storage.PrivateCVStorage(), upload_to='resumes/', validators=[django.core.validators.FileExtensionValidator(['pdf']), accounts.models.validate_cv_size]),
        ),
    ]

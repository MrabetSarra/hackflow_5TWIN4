from django.db import migrations


def promote_superusers(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(is_superuser=True, role='student').update(role='admin')


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0005_user_organization_role'),
    ]

    operations = [
        migrations.RunPython(promote_superusers, migrations.RunPython.noop),
    ]

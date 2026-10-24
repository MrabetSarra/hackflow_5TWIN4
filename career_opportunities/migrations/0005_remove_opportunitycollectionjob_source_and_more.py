from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('career_opportunities', '0004_alter_opportunity_opportunity_type'),
    ]

    operations = [
        # Drop the child table first so SQLite can safely rebuild its source table.
        migrations.DeleteModel(name='OpportunityCollectionJob'),
        migrations.RemoveConstraint(
            model_name='opportunity',
            name='career_unique_source_external',
        ),
        migrations.RemoveConstraint(
            model_name='opportunity',
            name='career_unique_source_url',
        ),
        migrations.RemoveField(model_name='opportunity', name='source'),
        migrations.RemoveField(model_name='opportunity', name='collected_at'),
        migrations.RemoveField(model_name='opportunity', name='external_id'),
        migrations.RemoveField(model_name='opportunity', name='extraction_data'),
        migrations.RemoveField(model_name='opportunity', name='last_verified_at'),
        migrations.RemoveField(model_name='opportunity', name='source_url'),
        migrations.DeleteModel(name='OpportunitySource'),
    ]

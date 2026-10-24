import django.core.validators
import django.db.models.deletion
import django.utils.timezone
import accounts.storage
from django.conf import settings
from django.db import migrations, models
import accounts.models
import career_opportunities.models


class Migration(migrations.Migration):
    initial = True
    dependencies = [('accounts', '0006_promote_existing_superusers')]
    operations = [
        migrations.CreateModel(name='OpportunitySource', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('name', models.CharField(max_length=160)), ('base_url', models.URLField(max_length=500)), ('feed_url', models.URLField(blank=True, max_length=500)),
            ('format', models.CharField(choices=[('manual', 'Manual'), ('rss', 'RSS'), ('json', 'JSON API/feed')], default='manual', max_length=10)),
            ('enabled', models.BooleanField(default=False)), ('terms_reviewed', models.BooleanField(default=False)), ('rate_limit_seconds', models.PositiveSmallIntegerField(default=60)),
            ('last_checked_at', models.DateTimeField(blank=True, null=True)), ('last_error', models.TextField(blank=True)), ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'ordering': ['name']}),
        migrations.CreateModel(name='Opportunity', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('title', models.CharField(max_length=240)), ('company', models.CharField(max_length=180)), ('description', models.TextField()),
            ('opportunity_type', models.CharField(choices=[('internship', 'Internship'), ('apprenticeship', 'Apprenticeship / work-study'), ('entry_level', 'Entry-level'), ('graduate', 'Graduate'), ('other', 'Other')], default='other', max_length=20)),
            ('education', models.CharField(blank=True, max_length=180)), ('experience', models.CharField(blank=True, max_length=180)), ('location', models.CharField(blank=True, max_length=180)),
            ('work_mode', models.CharField(choices=[('onsite', 'On-site'), ('hybrid', 'Hybrid'), ('remote', 'Remote'), ('unspecified', 'Not specified')], default='unspecified', max_length=15)),
            ('languages', models.JSONField(blank=True, default=list)), ('publication_date', models.DateField(blank=True, null=True)), ('deadline', models.DateField(blank=True, null=True)), ('salary', models.CharField(blank=True, max_length=120)),
            ('source_url', models.URLField(blank=True, max_length=1000)), ('application_url', models.URLField(blank=True, max_length=1000)), ('external_id', models.CharField(blank=True, max_length=240)),
            ('collected_at', models.DateTimeField(default=django.utils.timezone.now)), ('last_verified_at', models.DateTimeField(blank=True, null=True)),
            ('status', models.CharField(choices=[('review', 'Pending review'), ('published', 'Published'), ('rejected', 'Rejected'), ('archived', 'Archived')], default='review', max_length=12)),
            ('internal_application', models.BooleanField(default=False)), ('extraction_data', models.JSONField(blank=True, default=dict)), ('moderation_note', models.TextField(blank=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)), ('updated_at', models.DateTimeField(auto_now=True)),
            ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_opportunities', to=settings.AUTH_USER_MODEL)),
            ('source', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='opportunities', to='career_opportunities.opportunitysource')),
        ], options={'ordering': ['-publication_date', '-created_at']}),
        migrations.AddConstraint(model_name='opportunity', constraint=models.UniqueConstraint(condition=models.Q(('external_id', ''), _negated=True), fields=('source', 'external_id'), name='career_unique_source_external')),
        migrations.AddConstraint(model_name='opportunity', constraint=models.UniqueConstraint(condition=models.Q(('source_url', ''), _negated=True), fields=('source_url',), name='career_unique_source_url')),
        migrations.CreateModel(name='OpportunitySkill', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('name', models.CharField(max_length=100)),
            ('kind', models.CharField(choices=[('required', 'Required'), ('preferred', 'Preferred')], default='required', max_length=10)), ('evidence', models.CharField(blank=True, max_length=300)), ('verified', models.BooleanField(default=False)),
            ('opportunity', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='skills', to='career_opportunities.opportunity')),
        ], options={'ordering': ['kind', 'name']}),
        migrations.AddConstraint(model_name='opportunityskill', constraint=models.UniqueConstraint(fields=('opportunity', 'name', 'kind'), name='career_skill_uniq')),
        migrations.CreateModel(name='SavedOpportunity', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('created_at', models.DateTimeField(auto_now_add=True)),
            ('opportunity', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saves', to='career_opportunities.opportunity')),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saved_career_opportunities', to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.AddConstraint(model_name='savedopportunity', constraint=models.UniqueConstraint(fields=('user', 'opportunity'), name='career_saved_uniq')),
        migrations.CreateModel(name='CareerApplication', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('status', models.CharField(choices=[('draft', 'Draft'), ('intended', 'Intention to apply'), ('submitted', 'Submitted'), ('review', 'Under review'), ('interview', 'Interview'), ('accepted', 'Accepted'), ('rejected', 'Rejected'), ('withdrawn', 'Withdrawn')], default='intended', max_length=12)),
            ('cv', models.FileField(blank=True, storage=accounts.storage.PrivateCVStorage(), upload_to='career_applications/', validators=[django.core.validators.FileExtensionValidator(['pdf']), accounts.models.validate_cv_size, career_opportunities.models.validate_application_cv])),
            ('portfolio_url', models.URLField(blank=True)), ('note', models.CharField(blank=True, max_length=500)), ('created_at', models.DateTimeField(auto_now_add=True)), ('updated_at', models.DateTimeField(auto_now=True)),
            ('opportunity', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='applications', to='career_opportunities.opportunity')),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='career_applications', to=settings.AUTH_USER_MODEL)),
        ], options={'ordering': ['-updated_at']}),
        migrations.AddConstraint(model_name='careerapplication', constraint=models.UniqueConstraint(fields=('user', 'opportunity'), name='career_unique_user_application')),
        migrations.CreateModel(name='ApplicationHistory', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('old_status', models.CharField(blank=True, choices=[('draft', 'Draft'), ('intended', 'Intention to apply'), ('submitted', 'Submitted'), ('review', 'Under review'), ('interview', 'Interview'), ('accepted', 'Accepted'), ('rejected', 'Rejected'), ('withdrawn', 'Withdrawn')], max_length=12)),
            ('new_status', models.CharField(choices=[('draft', 'Draft'), ('intended', 'Intention to apply'), ('submitted', 'Submitted'), ('review', 'Under review'), ('interview', 'Interview'), ('accepted', 'Accepted'), ('rejected', 'Rejected'), ('withdrawn', 'Withdrawn')], max_length=12)), ('note', models.CharField(blank=True, max_length=500)), ('created_at', models.DateTimeField(auto_now_add=True)),
            ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ('application', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='history', to='career_opportunities.careerapplication')),
        ], options={'ordering': ['created_at']}),
        migrations.CreateModel(name='OpportunityCollectionJob', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('started_at', models.DateTimeField(auto_now_add=True)), ('finished_at', models.DateTimeField(blank=True, null=True)),
            ('imported_count', models.PositiveIntegerField(default=0)), ('duplicate_count', models.PositiveIntegerField(default=0)), ('error_count', models.PositiveIntegerField(default=0)), ('status', models.CharField(default='running', max_length=12)), ('log', models.TextField(blank=True)),
            ('source', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='jobs', to='career_opportunities.opportunitysource')),
        ]),
    ]

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('hackathons', '0005_remove_online_category_challenge_deadline'),
    ]

    operations = [
        migrations.DeleteModel(name='Sponsor'),
        migrations.DeleteModel(name='EvaluationCriterion'),
    ]

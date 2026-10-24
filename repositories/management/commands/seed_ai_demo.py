from django.core.management.base import BaseCommand, CommandError

from repositories.management.commands.seed_repositories import Command as RepositorySeedCommand
from repositories.models import Repository
from repositories.services import git_service


class Command(BaseCommand):
    help = 'Adds a sample AI-summary feature branch to the EcoTrack demo repository.'

    branch = 'feature/ai-summary-demo'

    def handle(self, *args, **options):
        repository = Repository.objects.filter(slug='ecotrack', team__name__iexact='EcoTrack').select_related(
            'team__captain'
        ).first()
        if not repository:
            raise CommandError('EcoTrack repository was not found. Run seed_repositories first.')
        if self.branch in git_service.branch_names(repository):
            self.stdout.write(self.style.WARNING(
                f'Skipped: {self.branch} already exists; no data was changed.'
            ))
            return

        author = repository.team.captain
        if not author:
            raise CommandError('EcoTrack needs a team captain before a demo branch can be created.')

        try:
            git_service.create_branch(repository, self.branch, repository.default_branch)
            RepositorySeedCommand._commit_files(repository, self.branch, author,
                'Add impact dashboard and CSV export', {
                    'README.md': (
                        '# EcoTrack\n\n'
                        'A sample project for tracking campus sustainability improvements.\n\n'
                        'The impact dashboard now shows total, average, and latest readings. '
                        'It can also export readings as CSV for campus reports.\n'
                    ),
                    'src/impact_dashboard.py': (
                        'import csv\n'
                        'from io import StringIO\n\n\n'
                        'def summarize_readings(readings):\n'
                        '    values = [float(value) for value in readings]\n'
                        '    if not values:\n'
                        '        return {"total": 0, "average": 0, "latest": None}\n'
                        '    return {"total": sum(values), "average": sum(values) / len(values), "latest": values[-1]}\n\n\n'
                        'def export_readings_csv(readings):\n'
                        '    output = StringIO()\n'
                        '    writer = csv.writer(output)\n'
                        '    writer.writerow(["reading"])\n'
                        '    writer.writerows([[value] for value in readings])\n'
                        '    return output.getvalue()\n'
                    ),
                    'tests/test_impact_dashboard.py': (
                        'from src.impact_dashboard import export_readings_csv, summarize_readings\n\n\n'
                        'def test_summarize_readings_returns_dashboard_metrics():\n'
                        '    assert summarize_readings([2, 4, 6]) == {"total": 12, "average": 4, "latest": 6}\n\n\n'
                        'def test_summarize_readings_handles_empty_input():\n'
                        '    assert summarize_readings([]) == {"total": 0, "average": 0, "latest": None}\n\n\n'
                        'def test_export_readings_csv_includes_header_and_values():\n'
                        '    assert export_readings_csv([2, 4]) == "reading\\r\\n2\\r\\n4\\r\\n"\n'
                    ),
                })
        except Exception as exc:
            raise CommandError(f'The AI demo branch could not be created: {exc}') from exc

        self.stdout.write(self.style.SUCCESS(
            f'Created {self.branch} in {repository.name}. Select it as the source and '
            f'{repository.default_branch} as the target when generating a merge request summary.'
        ))

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from student.models import Team

from repositories.models import Repository
from repositories.services import git_service
from repositories.services.security import remove_stage, stage_uploads


class Command(BaseCommand):
    help = 'Creates a demo Git repository for the existing EcoTrack team without changing existing repository data.'

    def handle(self, *args, **options):
        team = Team.objects.filter(name__iexact='EcoTrack').select_related('captain').first()
        if not team:
            raise CommandError('EcoTrack was not found. Create the demo team first, then run this command again.')
        existing = Repository.objects.filter(team=team).first()
        if existing:
            self.stdout.write(self.style.WARNING(f'Skipped: {existing.name} already exists for {team.name}; no data was changed.'))
            return
        if not team.captain_id or team.captain.role != 'student':
            raise CommandError('EcoTrack needs a student captain before a demo repository can be created.')

        repository = Repository.objects.create(
            team=team,
            name='EcoTrack',
            slug='ecotrack',
            description='A sample project repository for the EcoTrack team.',
            created_by=team.captain,
            default_branch='main',
            protected_branches=['main'],
        )
        try:
            git_service.initialize_repository(repository, team.captain)
            self._commit_files(repository, 'main', team.captain, 'Add EcoTrack starter project', {
                'README.md': (
                    '# EcoTrack\n\n'
                    'A sample project for tracking campus sustainability improvements.\n\n'
                    'The current impact score is 0.\n'
                ),
                'src/main.py': (
                    'def campus_impact(readings):\n'
                    '    """Return the total measured campus impact."""\n'
                    '    return sum(readings)\n'
                ),
            })
            git_service.create_branch(repository, 'feature/impact-dashboard', 'main')
            git_service.create_branch(repository, 'feature/accessibility', 'main')
            self._commit_files(repository, 'feature/impact-dashboard', team.captain, 'Add impact dashboard sample', {
                'README.md': (
                    '# EcoTrack\n\n'
                    'A sample project for tracking campus sustainability improvements.\n\n'
                    'The current impact score is 7.\n'
                ),
                'src/dashboard.py': 'def format_score(score):\n    return f"Impact: {score}"\n',
            })
            self._commit_files(repository, 'feature/accessibility', team.captain, 'Add accessibility sample', {
                'README.md': (
                    '# EcoTrack\n\n'
                    'A sample project for tracking campus sustainability improvements.\n\n'
                    'The current impact score is 12.\n'
                ),
                'src/accessibility.py': 'def accessible_label(name):\n    return f"Campus impact for {name}"\n',
            })
        except Exception as exc:
            # Keep a failed repository record visible for diagnosis; rerunning never overwrites it.
            raise CommandError(f'The demo repository could not be completed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(
            f'Created {repository.name} for {team.name} with main, two feature branches, and a README conflict between the feature branches.'
        ))

    @staticmethod
    def _commit_files(repository, branch, author, message, files):
        uploads = [SimpleUploadedFile(name, contents.encode('utf-8'), content_type='text/plain') for name, contents in files.items()]
        _token, stage_dir, _ignored, _file_count = stage_uploads(uploads, author.pk)
        try:
            git_service.commit_upload(repository, branch, stage_dir, 'keep', message, author, allow_protected=True)
        finally:
            remove_stage(stage_dir)

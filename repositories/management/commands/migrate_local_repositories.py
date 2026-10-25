from pathlib import Path
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from repositories.models import Repository
from repositories.services import git_service
from repositories.services import github


class Command(BaseCommand):
    help = 'Import recoverable local Git histories to GitHub without deleting or force-updating remote refs.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report what would be imported without contacting GitHub.')
        parser.add_argument('--source-root', help='Root containing team-id/repository-slug.git directories; defaults to REPOS_ROOT.')

    def handle(self, *args, **options):
        source_root = Path(options['source_root'] or settings.REPOS_ROOT).expanduser().resolve()
        dry_run = options['dry_run']
        repositories = Repository.objects.select_related('team').order_by('pk')
        for repository in repositories:
            if repository.remote_provider == 'github' and repository.remote_id:
                if dry_run:
                    self.stdout.write(f'Already linked: #{repository.pk} {repository.remote_owner}/{repository.remote_name}')
                    continue
                self._push_existing(repository, source_root)
                continue

            local_path = (source_root / str(repository.team_id) / f'{repository.slug}.git').resolve()
            if local_path.parent.parent != source_root or not local_path.exists():
                self.stdout.write(self.style.WARNING(
                    f'Unrecoverable from this source: #{repository.pk} {repository.slug}; '
                    'no local Git repository was found. Metadata alone cannot restore commits or branches.'
                ))
                continue
            if not self._is_bare_repository(local_path):
                self.stdout.write(self.style.WARNING(
                    f'Skipped #{repository.pk} {repository.slug}: the local path is not a valid bare Git repository.'
                ))
                continue

            branches = self._git(['for-each-ref', '--format=%(refname:short)', 'refs/heads'], local_path)
            branches = [line for line in branches.splitlines() if line]
            tags = self._git(['for-each-ref', '--format=%(refname:short)', 'refs/tags'], local_path)
            tag_count = len([line for line in tags.splitlines() if line])
            commit_count = self._git(['rev-list', '--all', '--count'], local_path).strip() or '0'
            action = 'Would import' if dry_run else 'Importing'
            self.stdout.write(
                f'{action} #{repository.pk} {repository.slug}: '
                f'{commit_count} commit(s), {len(branches)} branch(es), {tag_count} tag(s)'
            )
            if dry_run:
                continue
            self._import(repository, local_path, branches)

    def _import(self, repository, local_path, branches):
        if not branches:
            raise CommandError(
                f'{repository.slug} has no branch refs. Nothing was imported; it was not initialized automatically.'
            )
        try:
            github.create_repository(repository, auto_init=False)
            self._set_origin(local_path, repository.clone_url)
            for branch in branches:
                git_service._run([
                    '--git-dir', local_path, 'push', 'origin',
                    f'refs/heads/{branch}:refs/heads/{branch}',
                ], env=git_service.git_env())
            git_service._run(['--git-dir', local_path, 'push', 'origin', '--tags'], env=git_service.git_env())
            github.refresh_repository(repository)
        except (github.GitHubError, git_service.GitError) as error:
            raise CommandError(
                f'Import stopped for {repository.slug}: {error}. The HackFlow record and any created GitHub repository were retained; rerun only after checking remote refs.'
            ) from None
        self.stdout.write(self.style.SUCCESS(f'Imported #{repository.pk} to {repository.remote_url}'))

    def _push_existing(self, repository, source_root):
        local_path = (source_root / str(repository.team_id) / f'{repository.slug}.git').resolve()
        if not local_path.exists() or not self._is_bare_repository(local_path):
            self.stdout.write(self.style.WARNING(
                f'Already linked: #{repository.pk} {repository.remote_owner}/{repository.remote_name}; '
                'no local source was available to import.'
            ))
            return
        try:
            self._set_origin(local_path, repository.clone_url)
            branches = self._git(['for-each-ref', '--format=%(refname:short)', 'refs/heads'], local_path)
            for branch in filter(None, branches.splitlines()):
                git_service._run([
                    '--git-dir', local_path, 'push', 'origin',
                    f'refs/heads/{branch}:refs/heads/{branch}',
                ], env=git_service.git_env())
            git_service._run(['--git-dir', local_path, 'push', 'origin', '--tags'], env=git_service.git_env())
        except git_service.GitError as error:
            raise CommandError(f'Could not safely update {repository.remote_owner}/{repository.remote_name}: {error}') from None

    @staticmethod
    def _set_origin(path, clone_url):
        existing = git_service._run(['--git-dir', path, 'remote', 'get-url', 'origin'], check=False)
        if existing.returncode:
            git_service._run(['--git-dir', path, 'remote', 'add', 'origin', clone_url])
        else:
            git_service._run(['--git-dir', path, 'remote', 'set-url', 'origin', clone_url])

    @staticmethod
    def _is_bare_repository(path):
        result = git_service._run(['--git-dir', path, 'rev-parse', '--is-bare-repository'], check=False)
        return result.returncode == 0 and result.stdout.strip() == 'true'

    @staticmethod
    def _git(args, path):
        try:
            result = subprocess.run(
                ['git', '--git-dir', str(path), *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                check=False,
                shell=False,
                timeout=60,
                env=git_service.git_env(),
            )
        except OSError:
            raise CommandError('Git could not be started. Check that Git is installed.') from None
        except subprocess.TimeoutExpired:
            raise CommandError('Reading local Git history timed out; no source data was changed.') from None
        if result.returncode:
            raise CommandError('The local Git history could not be read; no source data was changed.')
        return result.stdout

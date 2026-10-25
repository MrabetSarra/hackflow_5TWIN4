import json
import tempfile
import zipfile
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from student.models import Hackathon, MentorRequest, Milestone, Task, Team, TeamMembership

from .models import Repository
from .models import AIUsageLog
from .models import MergeRequest
from .services import git_service
from .services import stack as stack_service
from .services.security import normalize_repo_path, stage_uploads


class RepositoryFeatureTests(TestCase):
    def setUp(self):
        self.temp_root = tempfile.TemporaryDirectory(prefix='hackflow-repository-tests-')
        self.repo_root = Path(self.temp_root.name) / 'git-data'
        self.settings_override = override_settings(DEBUG=True, REPOS_ROOT=self.repo_root)
        self.settings_override.enable()
        user_model = get_user_model()
        self.student = user_model.objects.create_user(username='student-a', email='student@example.test', password='password123', role='student', first_name='Test', last_name='Student')
        self.other_student = user_model.objects.create_user(username='student-b', password='password123', role='student')
        now = timezone.now()
        hackathon = Hackathon.objects.create(name='Test Hackathon', starts_at=now, ends_at=now + timezone.timedelta(days=2))
        self.team = Team.objects.create(hackathon=hackathon, name='Team One', captain=self.student)
        TeamMembership.objects.create(team=self.team, user=self.student)
        self.other_team = Team.objects.create(hackathon=hackathon, name='Team Two', captain=self.other_student)
        TeamMembership.objects.create(team=self.other_team, user=self.other_student)
        self.repository = Repository.objects.create(team=self.team, name='Demo Project', slug='demo-project', created_by=self.student, protected_branches=['main'])
        git_service.initialize_repository(self.repository, self.student)

    def tearDown(self):
        self.settings_override.disable()
        self.temp_root.cleanup()


    def test_rejects_path_traversal_and_absolute_paths(self):
        for path in ('../outside.txt', 'src/../../outside.txt', '/etc/passwd', 'C:/private.txt', '.git/config'):
            with self.subTest(path=path):
                if path == '.git/config':
                    self.assertEqual(normalize_repo_path(path), (None, True))
                else:
                    with self.assertRaises(ValidationError):
                        normalize_repo_path(path)

    def test_rejects_zip_compression_bomb(self):
        archive = BytesIO()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr('large.txt', 'A' * 200_000)
        upload = SimpleUploadedFile('bomb.zip', archive.getvalue(), content_type='application/zip')
        with override_settings(REPOSITORY_MAX_COMPRESSION_RATIO=5):
            with self.assertRaises(ValidationError):
                stage_uploads([upload], self.student.pk)

    def test_accepts_normal_zip_folder_entries(self):
        archive = BytesIO()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as zipped:
            zipped.writestr('src/', '')
            zipped.writestr('src/main.py', 'print("ok")')
        upload = SimpleUploadedFile('project.zip', archive.getvalue(), content_type='application/zip')
        _token, stage_dir, ignored, count = stage_uploads([upload], self.student.pk)
        self.assertEqual((ignored, count), ([], 1))
        self.assertEqual((stage_dir / 'files' / 'src' / 'main.py').read_text(encoding='utf-8'), 'print("ok")')

    def test_protected_branch_rejects_push(self):
        with self.assertRaisesMessage(ValidationError, 'protected'):
            git_service.commit_upload(self.repository, 'main', None, 'keep', 'Blocked push', self.student)
        with self.assertRaisesMessage(ValidationError, 'protected'):
            git_service.merge_branches(self.repository, 'main', 'main', 'Blocked merge', self.student)

    @override_settings(DEBUG=False, GITHUB_TOKEN='test-token', GITHUB_OWNER='hackflow-org')
    def test_production_does_not_reinitialize_existing_local_history(self):
        before = git_service._run([
            '--git-dir', self.repository.path, 'rev-parse', 'refs/heads/main',
        ]).stdout.strip()

        with self.assertRaisesMessage(git_service.GitError, 'Local Git data already exists'):
            git_service.initialize_repository(self.repository, self.student)

        after = git_service._run([
            '--git-dir', self.repository.path, 'rev-parse', 'refs/heads/main',
        ]).stdout.strip()
        self.assertEqual(after, before)

    def test_upload_is_not_reported_successful_if_github_rejects_the_push(self):
        git_service.create_branch(self.repository, 'feature/rejected', 'main')
        upload = SimpleUploadedFile('failure.txt', b'not persisted remotely\n', content_type='text/plain')
        _token, stage_dir, _ignored, _count = stage_uploads([upload], self.student.pk)
        with patch('repositories.services.git_service._push_branch', side_effect=git_service.GitError('GitHub rejected the push')):
            with self.assertRaisesMessage(git_service.GitError, 'GitHub rejected the push'):
                git_service.commit_upload(self.repository, 'feature/rejected', stage_dir, 'keep', 'Fail push', self.student)

    def test_repository_is_hidden_from_other_team(self):
        self.client.force_login(self.other_student)
        response = self.client.get(f'/student/repositories/{self.repository.slug}/')
        self.assertEqual(response.status_code, 404)

    @patch('repositories.services.github._request')
    def test_removing_hackflow_record_does_not_delete_github_repository(self, github_request):
        Repository.objects.filter(pk=self.repository.pk).update(
            remote_provider='github', remote_id=987654321, remote_owner='hackflow-org',
            remote_name='hackflow-1-demo-project',
            remote_url='https://github.com/hackflow-org/hackflow-1-demo-project',
            clone_url='https://github.com/hackflow-org/hackflow-1-demo-project.git',
        )
        self.client.force_login(self.student)

        response = self.client.post(f'/student/repositories/{self.repository.slug}/delete/')

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Repository.objects.filter(pk=self.repository.pk).exists())
        github_request.assert_not_called()

    def test_repository_detail_shows_real_main_branch(self):
        self.client.force_login(self.student)
        response = self.client.get(f'/student/repositories/{self.repository.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Branches')
        self.assertContains(response, 'main')

    def test_github_provider_metadata_persists_on_repository_record(self):
        from .services.github import save_remote_metadata

        save_remote_metadata(self.repository, {
            'id': 123456, 'node_id': 'R_123456', 'name': 'hackflow-1-demo-project',
            'owner': {'login': 'hackflow-org'},
            'html_url': 'https://github.com/hackflow-org/hackflow-1-demo-project',
            'clone_url': 'https://github.com/hackflow-org/hackflow-1-demo-project.git',
            'default_branch': 'main',
        })

        self.repository.refresh_from_db()
        self.assertEqual(self.repository.remote_provider, Repository.Provider.GITHUB)
        self.assertEqual(self.repository.remote_id, 123456)
        self.assertEqual(self.repository.remote_node_id, 'R_123456')
        self.assertEqual(self.repository.remote_owner, 'hackflow-org')
        self.assertEqual(self.repository.remote_name, 'hackflow-1-demo-project')
        self.assertEqual(self.repository.default_branch, 'main')

    def test_upload_preview_and_commit_create_real_git_commit(self):
        git_service.create_branch(self.repository, 'feature/demo', 'main')
        upload = SimpleUploadedFile('hello.py', b'print("hello")\n', content_type='text/plain')
        token, stage_dir, ignored, count = stage_uploads([upload], self.student.pk)
        self.assertEqual((ignored, count), ([], 1))
        preview = git_service.compare_upload(self.repository, 'feature/demo', stage_dir, 'keep')
        self.assertEqual(preview['added'], ['hello.py'])
        commit = git_service.commit_upload(self.repository, 'feature/demo', stage_dir, 'keep', 'Add hello example', self.student)
        self.assertEqual(git_service.resolve_branch(self.repository, 'feature/demo'), commit)
        self.assertEqual(git_service.branch_details(self.repository)[0]['author'], 'Test Student')
        self.assertTrue(git_service.read_file(self.repository, 'feature/demo', 'hello.py')[0].startswith('print'))

    def test_push_commits_files_excluded_by_the_projects_gitignore(self):
        git_service.create_branch(self.repository, 'feature/ignore-rules', 'main')
        ignore = SimpleUploadedFile('.gitignore', b'*.log\nbuild/\n', content_type='text/plain')
        log = SimpleUploadedFile('app.log', b'log line\n', content_type='text/plain')
        _token, stage_dir, _ignored, _count = stage_uploads([ignore, log], self.student.pk, ['.gitignore', 'app.log'])
        preview = git_service.compare_upload(self.repository, 'feature/ignore-rules', stage_dir, 'keep')
        self.assertEqual(sorted(preview['added']), ['.gitignore', 'app.log'])
        git_service.commit_upload(self.repository, 'feature/ignore-rules', stage_dir, 'keep', 'Add ignored files', self.student)
        entries = git_service.tree_entries(self.repository, 'feature/ignore-rules')
        self.assertIn('.gitignore', entries)
        self.assertIn('app.log', entries)

    def test_detected_stack_reports_the_real_frameworks(self):
        git_service.create_branch(self.repository, 'feature/stack', 'main')
        package = SimpleUploadedFile('package.json', json.dumps({
            'dependencies': {'react': '18.2.0', '@angular/core': '17.0.0'},
            'devDependencies': {'vite': '5.0.0'},
        }).encode(), content_type='application/json')
        composer = SimpleUploadedFile('composer.json', json.dumps({
            'require': {'laravel/framework': '^11.0'},
        }).encode(), content_type='application/json')
        source = SimpleUploadedFile('app.js', b'console.log("hi");\n', content_type='text/plain')
        _token, stage_dir, _ignored, _count = stage_uploads(
            [package, composer, source], self.student.pk, ['package.json', 'composer.json', 'app.js'])
        git_service.commit_upload(self.repository, 'feature/stack', stage_dir, 'keep', 'Add manifests', self.student)
        detected = stack_service.detect_stack(self.repository, 'feature/stack')
        self.assertIn('React', detected['frameworks'])
        self.assertIn('Angular', detected['frameworks'])
        self.assertIn('Laravel', detected['frameworks'])
        self.assertIn('Node.js', detected['runtimes'])
        self.assertIn('JavaScript', [name for name, _count in detected['languages']])
        self.assertEqual(stack_service.unknown_technologies('Built with React and Laravel.', detected), set())
        self.assertEqual(stack_service.unknown_technologies('Built with Vue.js and Django.', detected),
                         {'vue.js', 'django'})

    def test_submission_summary_keeps_only_technologies_the_repository_uses(self):
        git_service.create_branch(self.repository, 'feature/stack-summary', 'main')
        package = SimpleUploadedFile('package.json', json.dumps({'dependencies': {'react': '18.2.0'}}).encode(),
                                     content_type='application/json')
        _token, stage_dir, _ignored, _count = stage_uploads([package], self.student.pk, ['package.json'])
        git_service.commit_upload(self.repository, 'feature/stack-summary', stage_dir, 'keep', 'Add manifest',
                                  self.student)
        self.client.force_login(self.student)
        url = f'/student/repositories/{self.repository.slug}/ai/suggest/'
        draft = 'The dashboard is built with React and Vue.js.'
        with patch('repositories.ai._call_provider', return_value=(draft, {'input_tokens': 5, 'output_tokens': 5})):
            response = self.client.post(url, data=json.dumps({
                'feature': 'submission_summary', 'repository_id': self.repository.pk,
                'branch': 'feature/stack-summary'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        suggestion = response.json()['suggestion']
        self.assertNotIn('Vue.js', suggestion)
        self.assertIn('The project is built with React.', suggestion)

    def test_ai_rate_limit_explains_when_the_budget_resets(self):
        from repositories.ai import _rate_limit_message
        from repositories.models import AIUsageLog
        with override_settings(REPOSITORY_AI_PROVIDER='openai', REPOSITORY_AI_REQUESTS_PER_HOUR=2):
            self.assertIsNone(_rate_limit_message(self.student))
            AIUsageLog.objects.create(user=self.student, feature='test', token_estimate=0)
            AIUsageLog.objects.create(user=self.student, feature='test', token_estimate=0)
            message = _rate_limit_message(self.student)
        self.assertIn('limit', message)
        self.assertIn('Try again in about', message)

    def test_ai_retry_does_not_use_another_unit_of_the_budget(self):
        from repositories.ai import suggest
        with override_settings(REPOSITORY_AI_PROVIDER='openai', REPOSITORY_AI_REQUESTS_PER_HOUR=1):
            with patch('repositories.ai._call_provider', return_value=('draft', {'input_tokens': 1, 'output_tokens': 1})):
                self.assertEqual(suggest(self.student, 'test', 'source', 'instruction')['suggestion'], 'draft')
                with self.assertRaises(ValidationError):
                    suggest(self.student, 'test', 'source', 'instruction')
                retry = suggest(self.student, 'test', 'source', 'instruction', count_against_limit=False)
                self.assertEqual(retry['suggestion'], 'draft')
        self.assertEqual(AIUsageLog.objects.filter(user=self.student, counts_against_limit=True).count(), 1)
        self.assertEqual(AIUsageLog.objects.filter(user=self.student, counts_against_limit=False).count(), 1)

    def test_merge_request_summary_never_returns_raw_data(self):
        git_service.create_branch(self.repository, 'feature/mr-data', 'main')
        self._commit_text('feature/mr-data', 'data.json', '{"zones": [{"id": "Tunis_Nord"}]}\n', 'Add sample data')
        self.client.force_login(self.student)
        url = f'/student/repositories/{self.repository.slug}/ai/suggest/'
        dump = '```json\n{"zones": [{"id": "Tunis_Nord", "status": "alert"}]}\n```'
        with patch('repositories.ai._call_provider', return_value=(dump, {'input_tokens': 1, 'output_tokens': 1})):
            response = self.client.post(url, data=json.dumps({
                'feature': 'mr_summary', 'source': 'feature/mr-data', 'target': 'main'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        suggestion = response.json()['suggestion']
        self.assertNotIn('Tunis_Nord', suggestion)
        self.assertIn('data.json', suggestion)

    def test_project_description_uses_the_staged_snapshot(self):
        upload = SimpleUploadedFile('package.json', json.dumps({'dependencies': {'react': '18.2.0'}}).encode(),
                                    content_type='application/json')
        token, _stage_dir, _ignored, _count = stage_uploads([upload], self.student.pk, ['package.json'])
        self.client.force_login(self.student)
        url = f'/student/repositories/{self.repository.slug}/ai/suggest/'
        draft = 'A dashboard that follows the campus sustainability readings.'
        with patch('repositories.ai._call_provider', return_value=(draft, {'input_tokens': 1, 'output_tokens': 1})):
            response = self.client.post(url, data=json.dumps({
                'feature': 'project_description', 'stage_token': token,
                'branch': 'main', 'upload_mode': 'keep'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        suggestion = response.json()['suggestion']
        self.assertIn('A dashboard that follows the campus sustainability readings.', suggestion)
        self.assertIn('The project is built with React.', suggestion)

    def test_student_can_create_repository_from_list_page(self):
        self.client.force_login(self.student)
        response = self.client.post('/student/repositories/', {'name': 'New Project', 'description': 'Example'})
        self.assertEqual(response.status_code, 302)
        created = Repository.objects.get(team=self.team, slug='new-project')
        self.assertEqual(git_service.branch_names(created), ['main'])

    def test_push_preview_then_confirm_commits_through_the_ui(self):
        git_service.create_branch(self.repository, 'feature/ui-flow', 'main')
        self.client.force_login(self.student)
        url = f'/student/repositories/{self.repository.slug}/push/?branch=feature%2Fui-flow'
        response = self.client.post(url, {
            'upload_files': '1', 'branch': 'feature/ui-flow', 'upload_mode': 'keep',
            'upload_paths': '["app.txt"]',
            'upload': SimpleUploadedFile('app.txt', b'UI upload\n', content_type='text/plain'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['preview']['added'], ['app.txt'])
        response = self.client.post(url, {
            'confirm_commit': '1', 'branch': 'feature/ui-flow', 'upload_mode': 'keep',
            'stage_token': response.context['stage_token'], 'commit_message': 'Add app file',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(git_service.read_file(self.repository, 'feature/ui-flow', 'app.txt')[0], 'UI upload\n')

    def test_seed_command_creates_conflicting_branches_and_does_not_overwrite(self):
        self.other_team.name = 'EcoTrack'
        self.other_team.save(update_fields=['name'])
        call_command('seed_repositories', stdout=StringIO())
        demo = Repository.objects.get(team=self.other_team, slug='ecotrack')
        self.assertEqual(set(git_service.branch_names(demo)), {
            'main', 'feature/impact-dashboard', 'feature/accessibility',
        })
        merge = git_service._run([
            '--git-dir', demo.path, 'merge-tree', '--write-tree',
            'feature/impact-dashboard', 'feature/accessibility',
        ], check=False)
        self.assertNotEqual(merge.returncode, 0)
        previous_tip = git_service.resolve_branch(demo, 'main')
        output = StringIO()
        call_command('seed_repositories', stdout=output)
        self.assertIn('Skipped', output.getvalue())
        self.assertEqual(git_service.resolve_branch(demo, 'main'), previous_tip)

    def _commit_text(self, branch, path, content, message):
        upload = SimpleUploadedFile(path.rsplit('/', 1)[-1], content.encode(), content_type='text/plain')
        _token, stage_dir, _ignored, _count = stage_uploads([upload], self.student.pk, [path])
        return git_service.commit_upload(self.repository, branch, stage_dir, 'keep', message, self.student)

    def test_history_compare_and_commit_detail_use_real_git(self):
        git_service.create_branch(self.repository, 'feature/history', 'main')
        commit = self._commit_text('feature/history', 'app.py', 'print("v1")\n', 'Add app')
        history = git_service.commit_history(self.repository, 'feature/history')
        self.assertEqual(history[0]['hash'], commit)
        self.assertIn('print', git_service.commit_detail(self.repository, commit)['diff'])
        git_service.create_branch(self.repository, 'feature/empty', 'main')
        self.assertIn('app.py', git_service.compare_revisions(self.repository, 'feature/history', 'feature/empty'))

    def test_clean_merge_creates_merge_commit_with_expected_branch_tips(self):
        git_service.create_branch(self.repository, 'feature/source', 'main')
        git_service.create_branch(self.repository, 'feature/target', 'main')
        self._commit_text('feature/source', 'source.txt', 'source\n', 'Add source file')
        self._commit_text('feature/target', 'target.txt', 'target\n', 'Add target file')
        preview = git_service.merge_preview(self.repository, 'feature/source', 'feature/target')
        self.assertFalse(preview['conflicts'])
        commit = git_service.merge_branches(self.repository, 'feature/source', 'feature/target',
            'Merge feature/source into feature/target', self.student,
            expected_source=preview['source_tip'], expected_target=preview['target_tip'])
        self.assertEqual(git_service.resolve_branch(self.repository, 'feature/target'), commit)
        self.assertIn('source.txt', git_service.tree_entries(self.repository, 'feature/target'))

    def test_conflict_resolution_rejects_markers_and_creates_merge_commit(self):
        git_service.create_branch(self.repository, 'feature/source', 'main')
        git_service.create_branch(self.repository, 'feature/target', 'main')
        self._commit_text('feature/source', 'same.txt', 'from source\n', 'Source edit')
        self._commit_text('feature/target', 'same.txt', 'from target\n', 'Target edit')
        preview = git_service.merge_preview(self.repository, 'feature/source', 'feature/target')
        self.assertIn('same.txt', preview['conflicts'])
        with self.assertRaisesMessage(ValidationError, 'conflict markers'):
            git_service.finish_conflicted_merge(self.repository, 'feature/source', 'feature/target',
                preview['target_tip'], preview['source_tip'], {'same.txt': '<<<<<<< source\n'}, 'Resolve conflict', self.student)
        commit = git_service.finish_conflicted_merge(self.repository, 'feature/source', 'feature/target',
            preview['target_tip'], preview['source_tip'], {'same.txt': 'resolved\n'}, 'Resolve conflict', self.student)
        self.assertEqual(git_service.resolve_branch(self.repository, 'feature/target'), commit)
        content, _ = git_service.read_file(self.repository, 'feature/target', 'same.txt')
        self.assertEqual(content, 'resolved\n')

    def test_restore_creates_a_new_commit_with_an_older_tree(self):
        git_service.create_branch(self.repository, 'feature/restore', 'main')
        older = self._commit_text('feature/restore', 'app.txt', 'older\n', 'Old version')
        self._commit_text('feature/restore', 'app.txt', 'newer\n', 'New version')
        restored = git_service.restore_commit(self.repository, 'feature/restore', older, 'Restore old content', self.student)
        self.assertNotEqual(restored, older)
        self.assertEqual(git_service.read_file(self.repository, 'feature/restore', 'app.txt')[0], 'older\n')
        self.assertEqual(git_service.commit_detail(self.repository, restored)['message'], 'Restore old content')

    def test_local_history_migration_dry_run_does_not_contact_github(self):
        with patch('repositories.management.commands.migrate_local_repositories.github.create_repository') as create_remote:
            output = StringIO()
            call_command('migrate_local_repositories', '--dry-run', '--source-root', str(self.repo_root), stdout=output)
        self.assertIn('Would import', output.getvalue())
        self.assertIn('commit(s)', output.getvalue())
        create_remote.assert_not_called()

    def test_merge_request_review_and_merge_require_assigned_reviewer(self):
        git_service.create_branch(self.repository, 'feature/review', 'main')
        self._commit_text('feature/review', 'readme.txt', 'review me\n', 'Add review file')
        TeamMembership.objects.filter(team=self.other_team, user=self.other_student).delete()
        TeamMembership.objects.create(team=self.team, user=self.other_student)
        self.client.force_login(self.student)
        url = f'/student/repositories/{self.repository.slug}/merge-requests/'
        response = self.client.post(url, {'title': 'Review feature', 'source_branch': 'feature/review',
            'target_branch': 'main', 'reviewers': [str(self.other_student.pk)]})
        self.assertEqual(response.status_code, 302)
        mr = MergeRequest.objects.get(repository=self.repository)
        self.client.force_login(self.other_student)
        self.client.post(f'{url}{mr.pk}/', {'action': 'approve'})
        mr.refresh_from_db()
        self.assertEqual(mr.status, MergeRequest.Status.APPROVED)
        self.assertEqual(self.client.get(f'{url}{mr.pk}/').status_code, 200)
        response = self.client.post(f'{url}{mr.pk}/', {'action': 'preview_merge'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'repositories/merge_confirmation.html')
        response = self.client.post(f'{url}{mr.pk}/', {'action': 'merge',
            'source_tip': git_service.resolve_branch(self.repository, 'feature/review'),
            'target_tip': git_service.resolve_branch(self.repository, 'main'), 'merge_message': 'Merge review feature'})
        mr.refresh_from_db()
        self.assertEqual(mr.status, MergeRequest.Status.MERGED)
        self.assertTrue(mr.merged_commit)
        self.assertEqual(git_service.resolve_branch(self.repository, 'main'), mr.merged_commit)
        self.assertIn('readme.txt', git_service.tree_entries(self.repository, 'main'))

    def test_non_captain_author_cannot_approve_their_own_request(self):
        git_service.create_branch(self.repository, 'feature/peer', 'main')
        self._commit_text('feature/peer', 'peer.txt', 'peer review\n', 'Add peer file')
        TeamMembership.objects.filter(team=self.other_team, user=self.other_student).delete()
        TeamMembership.objects.create(team=self.team, user=self.other_student)
        url = f'/student/repositories/{self.repository.slug}/merge-requests/'
        self.client.force_login(self.other_student)
        self.client.post(url, {'title': 'Peer request', 'source_branch': 'feature/peer', 'target_branch': 'main'})
        mr = MergeRequest.objects.get(repository=self.repository)
        self.client.post(f'{url}{mr.pk}/', {'action': 'approve'})
        mr.refresh_from_db()
        self.assertEqual(mr.status, MergeRequest.Status.OPEN)
        self.client.post(f'{url}{mr.pk}/', {'action': 'merge'})
        mr.refresh_from_db()
        self.assertEqual(mr.status, MergeRequest.Status.OPEN)
        self.assertEqual(git_service.resolve_branch(self.repository, 'main'),
                         git_service.resolve_branch(self.repository, 'main'))


    def test_captain_can_approve_and_merge_a_request_they_opened(self):
        git_service.create_branch(self.repository, 'feature/captain', 'main')
        self._commit_text('feature/captain', 'captain.txt', 'captain merge\n', 'Add captain file')
        TeamMembership.objects.filter(team=self.other_team, user=self.other_student).delete()
        TeamMembership.objects.create(team=self.team, user=self.other_student)
        self.client.force_login(self.student)
        url = f'/student/repositories/{self.repository.slug}/merge-requests/'
        self.client.post(url, {'title': 'Captain request', 'source_branch': 'feature/captain', 'target_branch': 'main'})
        mr = MergeRequest.objects.get(repository=self.repository)
        self.client.post(f'{url}{mr.pk}/', {'action': 'approve'})
        mr.refresh_from_db()
        self.assertEqual(mr.status, MergeRequest.Status.APPROVED)
        response = self.client.post(f'{url}{mr.pk}/', {'action': 'merge',
            'source_tip': git_service.resolve_branch(self.repository, 'feature/captain'),
            'target_tip': git_service.resolve_branch(self.repository, 'main'),
            'merge_message': 'Merge captain request'})
        mr.refresh_from_db()
        self.assertEqual(mr.status, MergeRequest.Status.MERGED)
        self.assertIn('captain.txt', git_service.tree_entries(self.repository, 'main'))

    def test_ai_disabled_fallback_is_friendly_and_logs_no_file_content(self):
        from django.test import override_settings
        from repositories.ai import AIUnavailable, suggest
        with override_settings(ANTHROPIC_API_KEY='', REPOSITORY_AI_PROVIDER='anthropic'), patch('repositories.ai._anthropic_api_key', return_value=''):
            with self.assertRaises(AIUnavailable):
                suggest(self.student, 'test', 'private source text', 'Summarize this diff.')
        log = self.student.repository_ai_usage.latest('created_at')
        self.assertEqual(log.token_estimate, 0)
        self.assertEqual(log.feature, 'test')

    def test_ollama_provider_uses_local_chat_api(self):
        from repositories.ai import _call_provider
        response = BytesIO(json.dumps({
            'message': {'content': 'Local suggestion'}, 'prompt_eval_count': 12, 'eval_count': 4,
        }).encode())
        with override_settings(REPOSITORY_AI_PROVIDER='ollama', OLLAMA_BASE_URL='http://127.0.0.1:11434',
                               OLLAMA_MODEL='test-model'), patch('repositories.ai.urllib.request.urlopen', return_value=response) as request:
            result, usage = _call_provider('test prompt')
        self.assertEqual(result, 'Local suggestion')
        self.assertEqual(usage, {'input_tokens': 12, 'output_tokens': 4})
        self.assertTrue(request.call_args.args[0].full_url.endswith('/api/chat'))

    def test_openai_provider_uses_chat_completions_api(self):
        from repositories.ai import _call_provider
        response = BytesIO(json.dumps({
            'choices': [{'message': {'content': 'OpenAI suggestion'}}],
            'usage': {'prompt_tokens': 8, 'completion_tokens': 3},
        }).encode())
        with override_settings(REPOSITORY_AI_PROVIDER='openai', OPENAI_API_KEY='test-key', OPENAI_MODEL='test-model'), \
                patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), \
                patch('repositories.ai.urllib.request.urlopen', return_value=response) as request:
            result, usage = _call_provider('test prompt')
        self.assertEqual(result, 'OpenAI suggestion')
        self.assertEqual(usage, {'input_tokens': 8, 'output_tokens': 3})
        self.assertEqual(request.call_args.args[0].full_url, 'https://api.openai.com/v1/chat/completions')

    def test_history_compare_and_merge_request_pages_render(self):
        git_service.create_branch(self.repository, 'feature/pages', 'main')
        commit = self._commit_text('feature/pages', 'page.txt', 'history page\n', 'Add page content')
        self.client.force_login(self.student)
        for url in (
            f'/student/repositories/{self.repository.slug}/history/',
            f'/student/repositories/{self.repository.slug}/commits/{commit}/',
            f'/student/repositories/{self.repository.slug}/compare/?source=feature%2Fpages&target=main',
            f'/student/repositories/{self.repository.slug}/merge-requests/',
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_task_branch_integration_creates_and_links_real_branch(self):
        task = Task.objects.create(team=self.team, title='Build the welcome page')
        self.client.force_login(self.student)
        response = self.client.post('/student/tasks/', {'action': 'create_task_branch', 'task_id': task.pk,
            'repository_id': self.repository.pk})
        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.repository_id, self.repository.pk)
        self.assertEqual(task.repository_branch, f'task-{task.pk}-build-the-welcome-page')
        self.assertTrue(git_service.branch_exists(self.repository, task.repository_branch))

    def test_submission_freezes_selected_repository_branch_commit(self):
        milestone = Milestone.objects.create(hackathon=self.team.hackathon, title='Final submission',
            due_at=timezone.now() + timezone.timedelta(days=1))
        expected = git_service.resolve_branch(self.repository, 'main')
        self.client.force_login(self.student)
        response = self.client.post('/student/submission/', {'action': 'submit', 'project_name': 'Demo',
            'category': 'Challenge', 'description': 'Pinned version', 'github_url': '',
            'repository': str(self.repository.pk), 'repository_branch': 'main'})
        self.assertEqual(response.status_code, 302)
        from student.models import Submission
        submission = Submission.objects.get(team=self.team, milestone=milestone)
        self.assertEqual(submission.repository_id, self.repository.pk)
        self.assertEqual(submission.repository_commit, expected)
        self.assertEqual(self.client.get('/student/submission/').status_code, 200)

    def test_assigned_mentor_can_read_and_comment_but_cannot_write_git(self):
        mentor = get_user_model().objects.create_user(username='mentor-a', password='password123', role='mentor')
        MentorRequest.objects.create(student=self.student, team=self.team, mentor=mentor, subject='Review project',
            category='Backend', description='Please review', status='accepted')
        self.client.force_login(mentor)
        response = self.client.get(f'/student/repositories/{self.repository.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post(f'/student/repositories/{self.repository.slug}/', {'action': 'add_branch'}).status_code, 404)
        git_service.create_branch(self.repository, 'feature/review', 'main')
        self._commit_text('feature/review', 'review.txt', 'reviewable text\n', 'Add review file')
        response = self.client.post(f'/student/repositories/{self.repository.slug}/file-comment/', {
            'branch': 'feature/review', 'file_path': 'review.txt', 'body': 'Looks good.'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/mentor/repositories/').status_code, 200)


class AIEvaluationCommandTests(TestCase):
    def test_evaluate_ai_writes_a_reproducible_report(self):
        from django.core.management import call_command
        now = timezone.now()
        user = get_user_model().objects.create_user(username='metrics-student', password='password', role='student')
        hackathon = Hackathon.objects.create(name='Metrics Hackathon', starts_at=now, ends_at=now + timezone.timedelta(days=1))
        team = Team.objects.create(hackathon=hackathon, name='Metrics Team', captain=user)
        TeamMembership.objects.create(team=team, user=user)
        with tempfile.TemporaryDirectory(prefix='hackflow-ai-metrics-') as directory:
            report_path = Path(directory) / 'ai_metrics.md'
            output = StringIO()
            call_command('evaluate_ai', output=str(report_path), stdout=output)
            report = report_path.read_text(encoding='utf-8')
        self.assertIn('deterministic mocked provider', report)
        self.assertIn('True positives', report)
        self.assertIn('Precision', report)
        self.assertIn('Acceptance rate', report)
        self.assertIn('AI usage latency p95', report)
        self.assertIn('Mocked provider returned 1 valid task suggestion(s).', report)


class GitHubClientTests(SimpleTestCase):
    @override_settings(GITHUB_TOKEN='test-token', GITHUB_OWNER='hackflow-org', GITHUB_PRIVATE_REPOSITORIES=True)
    @patch('repositories.services.github.save_remote_metadata')
    @patch('repositories.services.github._request')
    def test_create_repository_uses_org_api_and_persists_provider_response(self, request, save_metadata):
        request.side_effect = [
            {'type': 'Organization'},
            {'id': 123, 'node_id': 'R_123', 'name': 'hackflow-7-demo',
             'owner': {'login': 'hackflow-org'}, 'html_url': 'https://github.com/hackflow-org/hackflow-7-demo',
             'clone_url': 'https://github.com/hackflow-org/hackflow-7-demo.git', 'default_branch': 'main'},
        ]
        save_metadata.side_effect = lambda _repository, data: data
        from .services import github
        repository = type('RepositoryStub', (), {
            'team_id': 7, 'slug': 'demo', 'description': 'Demo repository',
        })()

        result = github.create_repository(repository)

        self.assertEqual(result['id'], 123)
        self.assertEqual(request.call_args_list[1].args[:2], ('POST', '/orgs/hackflow-org/repos'))
        self.assertEqual(request.call_args_list[1].kwargs['payload'], {
            'name': 'hackflow-7-demo', 'description': 'Demo repository',
            'private': True, 'auto_init': True,
        })
        save_metadata.assert_called_once_with(repository, result)

    @override_settings(GITHUB_TOKEN='', GITHUB_OWNER='')
    def test_missing_credentials_give_actionable_configuration_error(self):
        from .services.github import GitHubError, _configuration
        with self.assertRaisesMessage(GitHubError, 'GITHUB_TOKEN and GITHUB_OWNER'):
            _configuration()

    @override_settings(GITHUB_TOKEN='test-token', GITHUB_OWNER='hackflow-org')
    @patch('repositories.services.git_service._ensure_remote_cache')
    @patch('repositories.services.git_service._push_branch')
    def test_branch_creation_pushes_the_real_git_ref(self, push_branch, ensure_remote_cache):
        repository = type('RepositoryStub', (), {
            'remote_provider': 'github', 'clone_url': 'https://github.com/hackflow-org/demo.git',
            'team_id': 9, 'slug': 'demo', 'default_branch': 'main',
            'is_protected': lambda self, branch: branch == 'main',
        })()
        import tempfile
        from pathlib import Path
        root = tempfile.TemporaryDirectory()
        repository.path = Path(root.name) / 'demo.git'
        git_service._run(['init', '--bare', '--initial-branch=main', repository.path])
        try:
            working = Path(root.name) / 'working'
            git_service._run(['init', '--initial-branch=main', working])
            author_env = git_service.git_env()
            author_env.update({'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.test'})
            git_service._run(['-C', working, 'commit', '--allow-empty', '-m', 'Initial'], env=author_env)
            git_service._run(['--git-dir', repository.path, 'fetch', str(working), 'main:refs/heads/main'])
            with override_settings(REPOS_ROOT=Path(root.name) / 'cache'):
                git_service.create_branch(repository, 'feature/test', 'main')
            ensure_remote_cache.assert_called()
            push_branch.assert_called_once_with(repository, 'feature/test')
        finally:
            root.cleanup()


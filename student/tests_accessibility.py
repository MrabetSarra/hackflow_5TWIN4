from html.parser import HTMLParser
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from repositories.models import Repository
from repositories.services.git_service import initialize_repository
from student.models import Hackathon, Team, TeamMembership


class AccessibilityHTMLParser(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__()
        self.h1_count = 0
        self.has_main = False
        self.html_lang = None
        self.skip_link = False
        self.images_without_alt = []
        self.unnamed_controls = []
        self._controls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'html':
            self.html_lang = attrs.get('lang')
        elif tag == 'h1':
            self.h1_count += 1
        elif tag == 'main':
            self.has_main = True
        elif tag == 'a' and attrs.get('href') == '#main-content':
            self.skip_link = True
        elif tag == 'img' and 'alt' not in attrs:
            self.images_without_alt.append(attrs.get('src', ''))
        if tag in {'a', 'button'}:
            self._controls.append({'tag': tag, 'attrs': attrs, 'text': ''})
        elif tag not in self.VOID:
            self._controls.append(None)

    def handle_data(self, data):
        for control in reversed(self._controls):
            if control is not None:
                control['text'] += data.strip() + ' '
                break

    def handle_endtag(self, tag):
        if tag in {'a', 'button'}:
            control = next((item for item in reversed(self._controls) if item and item['tag'] == tag), None)
            if control:
                attrs = control['attrs']
                name = attrs.get('aria-label') or attrs.get('aria-labelledby') or attrs.get('title') or control['text'].strip()
                if not name:
                    self.unnamed_controls.append((tag, attrs))
                self._controls.remove(control)
        elif self._controls:
            self._controls.pop()


class StudentPageAccessibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(username='accessibility-student', password='test-pass', role='student', first_name='Alex')
        now = timezone.now()
        hackathon = Hackathon.objects.create(name='Accessibility Hackathon', starts_at=now, ends_at=now + timezone.timedelta(days=3))
        cls.team = Team.objects.create(hackathon=hackathon, name='Access Team', captain=cls.student)
        TeamMembership.objects.create(team=cls.team, user=cls.student, role='Captain')

    def setUp(self):
        self.temp_root = tempfile.TemporaryDirectory(prefix='hackflow-accessibility-')
        self.override = override_settings(REPOS_ROOT=Path(self.temp_root.name) / 'repos')
        self.override.enable()
        self.repository = Repository.objects.create(team=self.team, name='Accessible Repository', slug='accessible-repo', created_by=self.student)
        initialize_repository(self.repository, self.student)
        self.client.force_login(self.student)

    def tearDown(self):
        self.override.disable()
        self.temp_root.cleanup()

    def test_student_pages_have_accessible_document_structure(self):
        pages = [
            ('dashboard', reverse('student:dashboard')),
            ('team', reverse('student:team_detail')),
            ('matching', reverse('student:skills_matching')),
            ('tasks', reverse('student:tasks_kanban')),
            ('mentor request', reverse('student:mentor_request')),
            ('submission', reverse('student:project_submission')),
            ('messages', reverse('student:messages')),
            ('repository list', reverse('repositories:list')),
            ('repository detail', reverse('repositories:detail', args=[self.repository.slug])),
        ]
        for label, url in pages:
            with self.subTest(page=label):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                parser = AccessibilityHTMLParser()
                parser.feed(response.content.decode(response.charset or 'utf-8'))
                self.assertEqual(parser.h1_count, 1, f'{label} has {parser.h1_count} h1 elements')
                self.assertTrue(parser.has_main, f'{label} has no main landmark')
                self.assertEqual(parser.html_lang, 'en', f'{label} has the wrong document language')
                self.assertTrue(parser.skip_link, f'{label} has no skip link')
                self.assertFalse(parser.images_without_alt, f'{label} has images without alt text: {parser.images_without_alt}')
                self.assertFalse(parser.unnamed_controls, f'{label} has unnamed links/buttons: {parser.unnamed_controls}')

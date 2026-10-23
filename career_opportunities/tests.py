from datetime import timedelta
from django.test import TestCase, Client
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from unittest.mock import patch
from django.contrib.auth import get_user_model
from .models import CareerApplication, CareerMatchCache, CareerRequirement, Opportunity, OpportunitySkill, SavedOpportunity, StudentCVAnalysis
from .services.matching import calculate_match
from .services.cv_analysis import analyze_student_cv

User = get_user_model()


class CareerFeatureTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(username='student-one', password='test-pass-12345', role='student', skills=['Python', 'Django'], study_level='Master 2', specialty='Computer Science')
        self.organizer = User.objects.create_user(username='org-one', password='test-pass-12345', role='organization')
        self.opportunity = Opportunity.objects.create(title='Backend intern', company='Example', description='Python and Django internship', status='published', deadline=timezone.localdate() + timedelta(days=20))
        OpportunitySkill.objects.create(opportunity=self.opportunity, name='Python', kind='required', evidence='Python is required')
        OpportunitySkill.objects.create(opportunity=self.opportunity, name='Docker', kind='required', evidence='Docker is required', verified=True)

    def tearDown(self):
        if self.student.cv:
            self.student.cv.delete(save=False)

    def test_manual_opportunity_is_draft_by_default(self):
        item = Opportunity.objects.create(title='Graduate role', company='Firm', description='Role')
        self.assertEqual(item.status, Opportunity.Status.DRAFT)

    def test_expired_opportunities_are_detected(self):
        self.opportunity.deadline = timezone.localdate() - timedelta(days=1)
        self.opportunity.save()
        self.assertTrue(self.opportunity.is_expired)
        self.assertFalse(self.opportunity.is_open)

    def test_matching_is_deterministic_and_explains_missing_requirements(self):
        analysis = {'status': 'ready', 'cv_digest': 'a' * 64, 'data': {'skills': [
            {'name': 'Python', 'evidence': 'Built services with Python.'}], 'education': [], 'experience': [], 'languages': [], 'projects': []}}
        result = calculate_match(self.student, self.opportunity, cv_analysis=analysis, use_cache=False)
        self.assertEqual(result['matched_skills'], ['Python'])
        self.assertEqual(result['missing_required_skills'], ['Docker'])
        self.assertEqual(result['mandatory'], 'unverified')
        self.assertEqual(result, calculate_match(self.student, self.opportunity, cv_analysis=analysis, use_cache=False))

    def test_missing_profile_data_reduces_coverage_without_fake_match(self):
        sparse = User.objects.create_user(username='sparse', password='test-pass-12345')
        result = calculate_match(sparse, self.opportunity)
        self.assertIsNone(result['score'])
        self.assertEqual(result['coverage'], 0)
        self.assertEqual(result['mandatory'], 'unverified')

    def test_student_scores_are_personal_and_cached_per_user(self):
        self.opportunity.education = 'Master'
        self.opportunity.save()
        first = {'status': 'ready', 'cv_digest': '1' * 64, 'data': {
            'skills': [{'name': 'Python', 'evidence': 'Python'}, {'name': 'Docker', 'evidence': 'Docker'}],
            'education': [{'text': 'Master degree'}], 'experience': [], 'languages': [], 'projects': []}}
        second_user = User.objects.create_user(username='student-two', role='student', study_level='Licence 3 / BUT')
        second = {'status': 'ready', 'cv_digest': '2' * 64, 'data': {
            'skills': [{'name': 'Python', 'evidence': 'Python'}, {'name': 'Docker', 'evidence': 'Docker'}],
            'education': [{'text': 'Bachelor degree'}], 'experience': [], 'languages': [], 'projects': []}}
        first_result = calculate_match(self.student, self.opportunity, cv_analysis=first)
        second_result = calculate_match(second_user, self.opportunity, cv_analysis=second)
        self.assertGreater(first_result['score'], second_result['score'])
        self.assertEqual(CareerMatchCache.objects.count(), 2)
        self.assertNotEqual(CareerMatchCache.objects.get(user=self.student).result,
                            CareerMatchCache.objects.get(user=second_user).result)

    def test_cv_analysis_is_local_structured_and_cached_until_file_changes(self):
        self.student.cv = SimpleUploadedFile('resume.pdf', b'%PDF-1.4 fake bytes')
        self.student.save()
        with patch('career_opportunities.services.cv_analysis.extract_text', return_value=(
            'Skills\nPython and JavaScript\nEducation\nMaster degree\nLanguages\nEnglish B2\nProjects\nHackathon API built with Django')) as parser:
            result = analyze_student_cv(self.student)
            again = analyze_student_cv(self.student)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(again['data']['skills'][0]['name'], 'Python')
        self.assertTrue(any(row['name'] == 'JavaScript' for row in result['data']['skills']))
        self.assertEqual(parser.call_count, 1)
        self.assertEqual(StudentCVAnalysis.objects.count(), 1)

    def test_unreadable_cv_produces_no_score(self):
        self.student.cv = SimpleUploadedFile('broken.pdf', b'%PDF-1.4 broken')
        self.student.save()
        with patch('career_opportunities.services.cv_analysis.extract_text', side_effect=ValueError('bad pdf')):
            analysis = analyze_student_cv(self.student)
        result = calculate_match(self.student, self.opportunity, cv_analysis=analysis)
        self.assertEqual(analysis['status'], 'unreadable')
        self.assertIsNone(result['score'])

    def test_mandatory_education_failure_is_visible_and_zero_weights_are_safe(self):
        student = User.objects.create_user(username='bachelor', role='student', study_level='Licence 3 / BUT')
        mandatory = CareerRequirement.objects.create(opportunity=self.opportunity, kind=CareerRequirement.Kind.EDUCATION,
            name='Master degree', description='Completed Master degree', weight=100, mandatory=True)
        analysis = {'status': 'ready', 'cv_digest': '3' * 64, 'data': {
            'skills': [], 'education': [{'text': 'Bachelor degree'}], 'experience': [], 'languages': [], 'projects': []}}
        result = calculate_match(student, self.opportunity, cv_analysis=analysis)
        self.assertEqual(result['mandatory_status'], 'failed')
        education_result = next(row for row in result['breakdown'] if row['requirement'] == 'Master degree')
        self.assertEqual(education_result['status'], 'mandatory_not_met')
        mandatory.weight = 0
        mandatory.save()
        for skill in self.opportunity.skills.all():
            skill.weight = 0
            skill.save()
        zero_result = calculate_match(student, self.opportunity, cv_analysis=analysis, use_cache=False)
        self.assertIsNone(zero_result['score'])
        self.assertEqual(zero_result['coverage'], 0)

    def test_student_and_organizer_permissions(self):
        client = Client()
        self.assertEqual(client.get('/careers/').status_code, 302)
        client.force_login(self.organizer)
        response = client.get('/careers/')
        self.assertRedirects(response, '/cockpit/careers/')
        self.assertEqual(client.get('/cockpit/careers/').status_code, 200)
        client.force_login(self.student)
        self.assertEqual(client.get('/careers/').status_code, 200)
        self.assertEqual(client.get('/cockpit/careers/').status_code, 403)

    def test_organizer_can_save_weighted_offer_as_private_draft(self):
        client = Client()
        client.force_login(self.organizer)
        data = {
            'title': 'Junior Data Intern', 'company': 'Data Co', 'description': 'Build with Python.',
            'opportunity_type': 'internship', 'education': 'Master', 'education_weight': '40',
            'education_mandatory': 'on', 'experience': '', 'experience_weight': '0',
            'location': 'Remote', 'work_mode': 'remote', 'location_weight': '20',
            'languages': 'English, French', 'language_weight': '20', 'required_skills': 'Python=10, SQL=10',
            'preferred_skills': '', 'publication_date': '', 'deadline': '', 'salary': '',
            'application_url': '', 'status': 'draft', 'moderation_note': '',
            'requirements-TOTAL_FORMS': '3', 'requirements-INITIAL_FORMS': '0',
            'requirements-MIN_NUM_FORMS': '0', 'requirements-MAX_NUM_FORMS': '30',
        }
        for index in range(3):
            for field in ('kind', 'name', 'description', 'weight', 'opportunity'):
                data[f'requirements-{index}-{field}'] = ''
            data[f'requirements-{index}-weight'] = '0'
        response = client.post('/cockpit/careers/new/', data)
        if response.status_code != 302:
            self.fail(f'Organizer form invalid: {response.context[0]["requirement_formset"].errors}')
        offer = Opportunity.objects.get(title='Junior Data Intern')
        self.assertEqual(offer.status, Opportunity.Status.DRAFT)
        total_weight = sum((row.weight for row in offer.skills.all()), 0) + sum((row.weight for row in offer.requirements.all()), 0)
        self.assertEqual(total_weight, 100)
        data['status'] = 'published'
        response = client.post(f'/cockpit/careers/{offer.pk}/edit/', data)
        self.assertEqual(response.status_code, 302)
        offer.refresh_from_db()
        self.assertEqual(offer.status, Opportunity.Status.PUBLISHED)

    def test_students_only_see_published_current_offers(self):
        Opportunity.objects.create(title='Draft role', company='Hidden', description='draft', status=Opportunity.Status.DRAFT)
        Opportunity.objects.create(title='Closed role', company='Closed', description='expired', status=Opportunity.Status.PUBLISHED,
                                   deadline=timezone.localdate() - timedelta(days=1))
        client = Client()
        client.force_login(self.student)
        response = client.get('/careers/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.opportunity.title)
        self.assertNotContains(response, 'Draft role')
        self.assertNotContains(response, 'Closed role')

    def test_application_is_owned_by_student(self):
        app = CareerApplication.objects.create(user=self.student, opportunity=self.opportunity)
        other = User.objects.create_user(username='other', password='test-pass-12345')
        client = Client()
        client.force_login(other)
        response = client.post(f'/careers/applications/{app.pk}/status/', {'status': 'withdrawn'})
        self.assertEqual(response.status_code, 404)
        app.refresh_from_db()
        self.assertEqual(app.status, 'intended')
        self.assertEqual(client.get(f'/cockpit/careers/applications/{app.pk}/cv/').status_code, 403)

    def test_private_cv_pdf_validator_rejects_non_pdf(self):
        app = CareerApplication(user=self.student, opportunity=self.opportunity, cv=SimpleUploadedFile('virus.exe', b'bad'))
        with self.assertRaises(ValidationError):
            app.full_clean()
        invalid_pdf = CareerApplication(user=self.student, opportunity=self.opportunity, cv=SimpleUploadedFile('fake.pdf', b'not a pdf'))
        with self.assertRaises(ValidationError):
            invalid_pdf.full_clean()

    def test_saved_opportunity_is_unique(self):
        SavedOpportunity.objects.create(user=self.student, opportunity=self.opportunity)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SavedOpportunity.objects.create(user=self.student, opportunity=self.opportunity)

    def test_external_application_records_intention_not_submission(self):
        self.student.skills = ['Python', 'Docker']
        self.student.save()
        client = Client()
        client.force_login(self.student)
        response = client.post(f'/careers/{self.opportunity.pk}/', {'apply': '1', 'note': 'Will apply'}, follow=True)
        self.assertEqual(response.status_code, 200)
        application = CareerApplication.objects.get(user=self.student, opportunity=self.opportunity)
        self.assertEqual(application.status, CareerApplication.Status.INTENDED)

    def test_internal_application_can_store_valid_pdf(self):
        self.opportunity.internal_application = True
        self.opportunity.save()
        self.student.cv = SimpleUploadedFile('profile-resume.pdf', b'%PDF-1.4 profile CV')
        self.student.save()
        client = Client()
        client.force_login(self.student)
        response = client.post(f'/careers/{self.opportunity.pk}/', {'apply': '1', 'note': 'Ready'}, follow=True)
        self.assertEqual(response.status_code, 200)
        application = CareerApplication.objects.get(user=self.student, opportunity=self.opportunity)
        self.assertEqual(application.status, CareerApplication.Status.SUBMITTED)
        self.assertEqual(application.cv.name, self.student.cv.name)


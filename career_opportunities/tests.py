from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from career_opportunities.models import (
    ApplicationHistory, CareerApplication, CareerRequirement, Opportunity, OpportunitySkill, SavedOpportunity,
)
from career_opportunities.services.cv_analysis import _extract_profile, _language_level, _ocr_sparse_pages, _text_density, analyze_student_cv
from career_opportunities.services.matching import calculate_match, calculate_matches
from career_opportunities.forms import CareerRequirementFormSet, OpportunityForm
from student.models import Notification
from career_opportunities.services.eligibility import evaluate_eligibility


class EligibilityEvaluationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='eligibility-student', role='student')
        self.opportunity = Opportunity.objects.create(
            title='Backend trainee', company='Example', description='Build services',
            status=Opportunity.Status.PUBLISHED,
        )

    def add_skill(self, name, verified):
        return OpportunitySkill.objects.create(
            opportunity=self.opportunity, name=name,
            kind=OpportunitySkill.Kind.REQUIRED, verified=verified,
        )

    def test_verified_missing_skill_fails_eligibility(self):
        self.user.skills = ['Python']
        self.user.save(update_fields=['skills'])
        self.add_skill('Kubernetes', verified=True)
        self.add_skill('Linux', verified=False)

        result = evaluate_eligibility(self.user, self.opportunity, ['Kubernetes'])

        self.assertEqual(result, {
            'status': 'failed', 'verified_missing': ['Kubernetes'], 'unverified': ['Linux'],
        })

    def test_missing_profile_evidence_and_language_requirements_remain_unverified(self):
        self.add_skill('Python', verified=True)
        result = evaluate_eligibility(self.user, self.opportunity, ['Python'])
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['unverified'], ['Python'])

        self.opportunity.skills.all().delete()
        self.opportunity.languages = ['French']
        self.opportunity.save(update_fields=['languages'])
        result = evaluate_eligibility(self.user, self.opportunity, [])
        self.assertEqual(result, {'status': 'unverified', 'verified_missing': [], 'unverified': []})

    def test_complete_evidence_satisfies_eligibility(self):
        self.user.skills = ['python', 'django']
        self.user.save(update_fields=['skills'])
        self.add_skill('Python', verified=True)

        result = evaluate_eligibility(self.user, self.opportunity, [])

        self.assertEqual(result, {'status': 'satisfied', 'verified_missing': [], 'unverified': []})


class MatchingServiceCoverageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='matching-student', role='student', skills=['React / TypeScript'],
            study_level='Master 1', bio='Built web platforms', school='Example University',
        )
        self.opportunity = Opportunity.objects.create(
            title='Full stack role', company='Example', description='Build a product',
            status=Opportunity.Status.PUBLISHED, education='Master', experience='2 years',
            location='Tunis', work_mode=Opportunity.WorkMode.HYBRID, languages=['English'],
        )

    def test_calculate_match_evaluates_typed_and_legacy_requirements_and_cache(self):
        OpportunitySkill.objects.create(
            opportunity=self.opportunity, name='React', kind=OpportunitySkill.Kind.REQUIRED,
            verified=True, weight=30,
        )
        OpportunitySkill.objects.create(
            opportunity=self.opportunity, name='Kubernetes', kind=OpportunitySkill.Kind.PREFERRED,
            verified=False, weight=10,
        )
        for kind, name, weight, mandatory in (
            (CareerRequirement.Kind.EDUCATION, 'Master degree', 15, True),
            (CareerRequirement.Kind.EXPERIENCE, '2 years experience', 10, True),
            (CareerRequirement.Kind.LANGUAGE, 'English B1', 10, False),
            (CareerRequirement.Kind.PROJECT, 'Climate platform', 5, False),
            (CareerRequirement.Kind.LOCATION, 'Tunis', 5, False),
            (CareerRequirement.Kind.OTHER, 'Python backend', 5, False),
        ):
            CareerRequirement.objects.create(
                opportunity=self.opportunity, kind=kind, name=name,
                weight=weight, mandatory=mandatory,
            )
        analysis = {
            'status': 'ready', 'cv_digest': 'digest-1',
            'data': {
                'skills': [{'name': 'React', 'evidence': 'React application'}],
                'education': [{'text': 'Master degree in computing'}],
                'experience': [{'evidence': '3 years experience building backend'}],
                'languages': [{'name': 'English', 'proficiency': 'B2', 'evidence': 'English B2'}],
                'projects': [{'name': 'Climate platform', 'evidence': 'Built climate platform'}],
            },
        }

        result = calculate_match(self.user, self.opportunity, cv_analysis=analysis)
        cached = calculate_match(self.user, self.opportunity, cv_analysis=analysis)
        self.assertEqual(result['score_state'], 'scored')
        self.assertEqual(result['mandatory_status'], 'satisfied')
        self.assertEqual(result, cached)
        self.assertTrue(result['matched_skills'])
        self.assertEqual(calculate_matches(self.user, [], cv_analysis=analysis), {})
        self.assertEqual(calculate_matches(self.user, [self.opportunity], cv_analysis=analysis)[self.opportunity.pk], result)

    def test_unreadable_cv_produces_no_score_and_profile_only_evidence_is_retained(self):
        result = calculate_match(self.user, self.opportunity, cv_analysis={
            'status': 'empty', 'cv_digest': '', 'data': {},
        }, use_cache=False)
        self.assertIsNone(result['score'])
        self.assertEqual(result['score_state'], 'empty')
        self.assertEqual(result['mandatory_status'], 'unknown')


class CVAnalysisHelperCoverageTests(TestCase):
    def test_profile_extraction_and_language_levels(self):
        profile = _extract_profile(
            'Python and Django backend engineer\nMaster degree in computer science\n'
            'English C1 certified\n3 years experience\nProjects:\n'
            'Climate Platform\nBuilt a climate platform using Python and React.'
        )
        self.assertIn('Python', [item['name'] for item in profile['skills']])
        self.assertTrue(profile['education'])
        self.assertEqual(profile['languages'][0]['proficiency'], 'C1')
        self.assertTrue(profile['experience'])
        self.assertTrue(profile['projects'])
        self.assertEqual(_language_level('French A2', 'French'), 'A2')
        self.assertEqual(_language_level('English', 'English'), '')
        self.assertGreater(_text_density('React & UX'), 0)

    def test_ocr_uses_recognized_text_only_when_page_text_is_sparse(self):
        import pymupdf
        from types import SimpleNamespace
        from unittest.mock import patch

        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((20, 30), 'CV')
        content = document.tobytes()
        document.close()
        engine = lambda _image: SimpleNamespace(txts=['Scanned Python engineer profile with many useful details'])
        with patch('career_opportunities.services.cv_analysis._ocr_engine', return_value=engine):
            text, attempted = _ocr_sparse_pages(content)
        self.assertTrue(attempted)
        self.assertIn('Scanned Python', text)

    def test_missing_cv_returns_missing_analysis(self):
        user = get_user_model().objects.create_user(username='no-cv-student', role='student')
        self.assertEqual(analyze_student_cv(user)['status'], 'missing')

    def test_analysis_parses_cv_and_reuses_current_cached_result(self):
        from unittest.mock import MagicMock
        user = get_user_model().objects.create_user(username='cv-readable', role='student')
        user.cv = MagicMock()
        user.cv.open.return_value.__enter__.return_value.read.return_value = b'%PDF-test'
        parsed_text = ('Python developer with Django experience and English C1. ' * 4)
        with patch('career_opportunities.services.cv_analysis.extract_text', return_value=parsed_text), \
                patch('career_opportunities.services.cv_analysis._ocr_sparse_pages') as ocr:
            result = analyze_student_cv(user)
            cached = analyze_student_cv(user)
        self.assertEqual(result['status'], 'ready')
        self.assertIn('Python', [row['name'] for row in result['data']['skills']])
        self.assertEqual(cached['cv_digest'], result['cv_digest'])
        ocr.assert_not_called()

    def test_analysis_handles_unreadable_upload_and_ocr_fallback(self):
        from unittest.mock import MagicMock
        user = get_user_model().objects.create_user(username='cv-ocr-fallback', role='student')
        user.cv = MagicMock()
        user.cv.open.return_value.__enter__.return_value.read.return_value = b'%PDF-scan'
        with patch('career_opportunities.services.cv_analysis.extract_text', side_effect=ValueError), \
                patch('career_opportunities.services.cv_analysis._ocr_sparse_pages', return_value=('Scanned Python developer profile', True)):
            result = analyze_student_cv(user)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['ocr_status'], 'used')

        user.cv.open.return_value.__enter__.return_value.read.return_value = b'not a pdf'
        unreadable = analyze_student_cv(user, force=True)
        self.assertEqual(unreadable['status'], 'unreadable')

    def test_analysis_returns_empty_when_pdf_and_ocr_have_no_text(self):
        from unittest.mock import MagicMock
        user = get_user_model().objects.create_user(username='cv-empty-scan', role='student')
        user.cv = MagicMock()
        user.cv.open.return_value.__enter__.return_value.read.return_value = b'%PDF-empty'
        with patch('career_opportunities.services.cv_analysis.extract_text', return_value=''), \
                patch('career_opportunities.services.cv_analysis._ocr_sparse_pages', return_value=('', True)):
            result = analyze_student_cv(user)
        self.assertEqual(result['status'], 'empty')
        self.assertEqual(result['ocr_status'], 'no_text')


class CareerViewCoverageTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.student = User.objects.create_user(
            username='career-view-student', email='career-student@example.test', role='student',
            skills=['Python'], study_level='Master 1',
        )
        self.organizer = User.objects.create_user(username='career-view-organizer', role='organization')
        self.mentor = User.objects.create_user(username='career-view-mentor', role='mentor')
        self.offer = Opportunity.objects.create(
            title='Backend internship', company='Example Co', description='Build APIs',
            status=Opportunity.Status.PUBLISHED, internal_application=True,
        )
        self.application = CareerApplication.objects.create(
            user=self.student, opportunity=self.offer, status=CareerApplication.Status.SUBMITTED,
        )
        self.analysis = {'status': 'empty', 'data': {}, 'cv_digest': ''}
        self.match = {
            'score': 72, 'mandatory_status': 'satisfied', 'coverage': 100,
            'requirements': [], 'recommendations': [],
        }

    @patch('career_opportunities.views.analyze_student_cv')
    @patch('career_opportunities.views.calculate_match')
    @patch('career_opportunities.views.calculate_matches')
    def test_student_listing_detail_and_role_redirects(self, matches_mock, match_mock, analysis_mock):
        analysis_mock.return_value = self.analysis
        match_mock.return_value = self.match
        matches_mock.return_value = {self.offer.pk: self.match}
        self.client.force_login(self.student)
        listing = self.client.get(reverse('career_opportunities:list') + '?q=backend&type=internship&location=remote&work_mode=remote&saved=1')
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.context['cards'], [])

        detail = self.client.get(reverse('career_opportunities:detail', args=[self.offer.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context['match']['score'], 72)
        self.assertEqual(self.client.get(reverse('career_opportunities:list')).status_code, 200)

        self.client.force_login(self.mentor)
        self.assertRedirects(self.client.get(reverse('career_opportunities:list')), reverse('mentor:dashboard'))
        self.assertEqual(self.client.get(reverse('career_opportunities:detail', args=[self.offer.pk])).status_code, 403)

    @patch('career_opportunities.views.analyze_student_cv')
    @patch('career_opportunities.views.calculate_match')
    @patch('career_opportunities.views.calculate_matches')
    def test_student_apply_save_withdraw_and_application_filter(self, matches_mock, match_mock, analysis_mock):
        analysis_mock.return_value = self.analysis
        match_mock.return_value = self.match
        matches_mock.return_value = {self.offer.pk: self.match}
        self.student.cv.name = 'resumes/coverage-student.pdf'
        self.student.save(update_fields=['cv'])
        self.client.force_login(self.student)
        detail_url = reverse('career_opportunities:detail', args=[self.offer.pk])
        application = CareerApplication.objects.get(user=self.student, opportunity=self.offer)
        application.delete()
        posted = self.client.post(detail_url, {'apply': '1', 'portfolio_url': 'https://portfolio.example.test', 'note': 'Interested'})
        self.assertRedirects(posted, detail_url)
        application = CareerApplication.objects.get(user=self.student, opportunity=self.offer)
        self.assertEqual(application.status, CareerApplication.Status.SUBMITTED)
        self.assertTrue(ApplicationHistory.objects.filter(application=application).exists())

        save_url = reverse('career_opportunities:save', args=[self.offer.pk])
        self.assertRedirects(self.client.post(save_url, {'next': '/careers/'}), '/careers/')
        self.assertTrue(SavedOpportunity.objects.filter(user=self.student, opportunity=self.offer).exists())
        self.client.post(save_url, {})
        self.assertFalse(SavedOpportunity.objects.exists())

        applications_url = reverse('career_opportunities:applications') + '?q=backend&status=submitted'
        page = self.client.get(applications_url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.context['applications']), 1)
        self.client.post(reverse('career_opportunities:application_status', args=[application.pk]),
                         {'status': CareerApplication.Status.WITHDRAWN})
        application.refresh_from_db()
        self.assertEqual(application.status, CareerApplication.Status.WITHDRAWN)

    @patch('career_opportunities.views.calculate_match')
    @patch('career_opportunities.views.calculate_matches')
    @patch('career_opportunities.views.analyze_student_cv')
    def test_organizer_dashboard_application_updates_and_notifications(self, analysis_mock, matches_mock, match_mock):
        analysis_mock.return_value = self.analysis
        matches_mock.return_value = {self.offer.pk: self.match}
        match_mock.return_value = self.match
        self.client.force_login(self.organizer)
        self.assertEqual(self.client.get(reverse('dashboard_admin:career_dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('dashboard_admin:career_applications')).status_code, 200)
        update_url = reverse('dashboard_admin:career_application_status', args=[self.application.pk])
        prefix = f'application-{self.application.pk}-'
        response = self.client.post(update_url, {
            prefix + 'status': CareerApplication.Status.INTERVIEW,
            prefix + 'interview_at': '2026-11-01T10:30',
            prefix + 'organizer_update': 'Please confirm the meeting.',
        })
        self.assertRedirects(response, reverse('dashboard_admin:career_applications'))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, CareerApplication.Status.INTERVIEW)
        self.assertTrue(Notification.objects.filter(user=self.student, title='Application update').exists())
        self.assertTrue(ApplicationHistory.objects.filter(application=self.application, new_status='interview').exists())

    @patch('career_opportunities.views.calculate_match', return_value={'score': 42})
    @patch('career_opportunities.views.analyze_student_cv')
    def test_organizer_cannot_schedule_ineligible_interview(self, analysis_mock, _match_mock):
        analysis_mock.return_value = self.analysis
        self.client.force_login(self.organizer)
        prefix = f'application-{self.application.pk}-'
        self.client.post(reverse('dashboard_admin:career_application_status', args=[self.application.pk]), {
            prefix + 'status': CareerApplication.Status.INTERVIEW,
            prefix + 'interview_at': '2026-11-01T10:30',
        })
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, CareerApplication.Status.SUBMITTED)
        self.assertFalse(Notification.objects.exists())

    def test_organizer_forms_and_cv_missing_responses(self):
        self.client.force_login(self.organizer)
        self.assertEqual(self.client.get(reverse('dashboard_admin:career_create')).status_code, 200)
        self.assertEqual(self.client.get(reverse('dashboard_admin:career_edit', args=[self.offer.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('dashboard_admin:career_application_cv', args=[self.application.pk])).status_code, 404)

        self.client.force_login(self.mentor)
        self.assertEqual(self.client.get(reverse('dashboard_admin:career_dashboard')).status_code, 403)


class OpportunityFormCoverageTests(TestCase):
    def valid_data(self, **overrides):
        data = {
            'title': 'Backend intern', 'company': 'Example Co', 'description': 'Build APIs',
            'opportunity_type': Opportunity.Type.INTERNSHIP, 'education': 'Master',
            'experience': '', 'location': 'Tunis', 'work_mode': Opportunity.WorkMode.HYBRID,
            'languages': 'French, English', 'publication_date': '', 'deadline': '',
            'salary': '', 'application_url': '', 'internal_application': 'on',
            'status': Opportunity.Status.DRAFT, 'moderation_note': '',
            'required_skills': 'Python=30', 'preferred_skills': 'Docker=10',
            'education_weight': '20', 'experience_weight': '0', 'language_weight': '20',
            'location_weight': '20', 'education_mandatory': 'on',
            'experience_mandatory': '', 'language_mandatory': '', 'location_mandatory': '',
        }
        data.update(overrides)
        return data

    def test_opportunity_form_normalizes_skill_and_profile_weights(self):
        form = OpportunityForm(self.valid_data())
        self.assertTrue(form.is_valid(), form.errors)
        formset = CareerRequirementFormSet(instance=Opportunity(), queryset=CareerRequirement.objects.none())
        self.assertTrue(form.validate_weights(formset), form.errors)
        opportunity = form.save(commit=False)
        opportunity.save()
        form.save_requirements(opportunity, formset)
        weights = [row.weight for row in opportunity.skills.all()]
        weights += [row.weight for row in opportunity.requirements.all()]
        self.assertEqual(sum(weights), 100)
        self.assertEqual(list(opportunity.languages), ['French', 'English'])

    def test_opportunity_form_rejects_bad_duplicate_and_zero_weight_skills(self):
        duplicate = OpportunityForm(self.valid_data(required_skills='Python=20, python=30'))
        self.assertFalse(duplicate.is_valid())
        self.assertIn('required_skills', duplicate.errors)

        bad_weight = OpportunityForm(self.valid_data(required_skills='Python=not-a-number'))
        self.assertFalse(bad_weight.is_valid())
        self.assertIn('required_skills', bad_weight.errors)

        zero = OpportunityForm(self.valid_data(
            required_skills='Python=0', preferred_skills='', education='', languages='',
            location='', education_weight='0', language_weight='0', location_weight='0',
        ))
        self.assertTrue(zero.is_valid(), zero.errors)
        empty_formset = CareerRequirementFormSet(instance=Opportunity(), queryset=CareerRequirement.objects.none())
        self.assertFalse(zero.validate_weights(empty_formset))

    def test_custom_requirement_formset_is_normalized_and_deleted_rows_are_removed(self):
        form = OpportunityForm(self.valid_data())
        self.assertTrue(form.is_valid(), form.errors)
        formset = CareerRequirementFormSet(
            data={
                'requirements-TOTAL_FORMS': '3', 'requirements-INITIAL_FORMS': '0',
                'requirements-MIN_NUM_FORMS': '0', 'requirements-MAX_NUM_FORMS': '30',
                'requirements-0-kind': CareerRequirement.Kind.PROJECT,
                'requirements-0-name': 'Portfolio project', 'requirements-0-description': 'Demonstrate work',
                'requirements-0-weight': '10', 'requirements-0-mandatory': 'on',
                'requirements-1-kind': '', 'requirements-1-name': '', 'requirements-1-description': '',
                'requirements-1-weight': '', 'requirements-1-DELETE': 'on',
                'requirements-2-kind': '', 'requirements-2-name': '',
                'requirements-2-description': '', 'requirements-2-weight': '', 'requirements-2-DELETE': 'on',
            },
            instance=Opportunity(), queryset=CareerRequirement.objects.none(),
        )
        self.assertTrue(formset.is_valid(), formset.errors)
        self.assertTrue(form.validate_weights(formset), form.errors)
        opportunity = form.save(commit=False)
        opportunity.save()
        form.save_requirements(opportunity, formset)
        requirement = opportunity.requirements.get(name='Portfolio project')
        self.assertTrue(requirement.mandatory)
        self.assertGreater(requirement.weight, 0)

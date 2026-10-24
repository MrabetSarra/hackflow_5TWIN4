from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import DEFAULT_CRITERIA, Criterion


class CriterionGridTests(TestCase):
    def test_default_grid_is_created_by_migrations(self):
        codes = set(Criterion.objects.values_list('code', flat=True))
        self.assertEqual(codes, {c['code'] for c in DEFAULT_CRITERIA})

    def test_default_grid_totals_100_percent(self):
        self.assertEqual(Criterion.total_weight(Criterion.Scope.JURY), 100)
        self.assertEqual(Criterion.total_weight(Criterion.Scope.MENTOR), 100)

    def test_ensure_default_grid_restores_missing_criteria(self):
        Criterion.objects.filter(code='innovation').delete()
        Criterion.ensure_default_grid()
        self.assertTrue(Criterion.objects.filter(code='innovation').exists())

    def test_ensure_default_grid_keeps_admin_changes(self):
        Criterion.objects.filter(code='technique').update(weight=40)
        Criterion.ensure_default_grid()
        self.assertEqual(Criterion.objects.get(code='technique').weight, 40)

    def test_for_scope_excludes_inactive_and_other_scope(self):
        Criterion.objects.create(code='jury_only', name='Jury', weight=10, scope=Criterion.Scope.JURY)
        Criterion.objects.filter(code='design_ux').update(is_active=False)
        mentor_codes = set(Criterion.for_scope(Criterion.Scope.MENTOR).values_list('code', flat=True))
        self.assertNotIn('jury_only', mentor_codes)
        self.assertNotIn('design_ux', mentor_codes)

    def test_weight_must_be_between_1_and_100(self):
        criterion = Criterion(code='bad', name='Bad', weight=0)
        with self.assertRaises(ValidationError):
            criterion.full_clean()

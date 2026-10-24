from django.test import SimpleTestCase

from repositories.templatetags.repo_tags import get_item, split


class RepositoryTemplateTagTests(SimpleTestCase):
    def test_get_item_only_reads_dictionary_values(self):
        self.assertEqual(get_item({'name': 'API'}, 'name'), 'API')
        self.assertEqual(get_item({}, 'missing'), '')
        self.assertEqual(get_item(['API'], 0), '')

    def test_split_accepts_lists_tuples_and_strings(self):
        self.assertEqual(split(['a', 'b']), ['a', 'b'])
        self.assertEqual(split(('a', 'b')), ['a', 'b'])
        self.assertEqual(split('a, b'), ['a', ' b'])
        self.assertEqual(split('abc', ''), ['a', 'b', 'c'])
        self.assertEqual(split(None), [])

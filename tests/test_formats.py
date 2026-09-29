import unittest
from usaddress_dataset.formats import FormatDefinition
from usaddress_dataset.models import AddressFamily, NumberDomain
from test_core import family


def definition(variants=None, **extra):
    return FormatDefinition.from_dict(dict(id='two_lines', version=1, description='Test', case='upper', variants=variants or [
        {'lines': ['{number} {street}', '{city}, {state} {zip}']},
        {'lines': ['{number} {street}', '{city} {state} {zip}']},
    ], **extra))


class FormatTests(unittest.TestCase):
    def test_reserved_and_actual_lengths_are_distinct(self):
        fmt = definition()
        self.assertEqual(fmt.bounds(family()), ((10, 10), (15, 16)))
        lines = fmt.render(family(), 0, '42')
        self.assertEqual(lines, ['42 OAK DR', 'BOSTON, MA 02108'])
        self.assertEqual(fmt.reserved_lengths(family(), 0), [10, 16])

    def test_missing_unit_excludes_unit_format(self):
        fmt = definition([{'lines': ['{number} {street}', '{unit_type} {unit}', '{city} {state} {zip}']}])
        self.assertIsNone(fmt.bounds(family()))
        self.assertEqual(fmt.render(family(unit_type='APT', unit='2B'), 0, '42')[1], 'APT 2B')

    def test_no_attributes_conversions_or_unknown_fields(self):
        for template in ['{number.__class__}', '{number!r}', '{number:10}', '{unknown}', '{street}\n{city}', '']:
            with self.subTest(template=template), self.assertRaises(ValueError):
                definition([{'lines': [template]}])
        with self.assertRaises(ValueError):
            definition([{'lines': ['{street}']}, {'lines': ['{street}', '{city}']}])

    def test_explicit_unicode_number_width_after_case(self):
        f = family(numbers=NumberDomain(values=('1ß', '2')))
        fmt = definition([{'lines': ['{number} {street}']}])
        self.assertEqual(fmt.bounds(f), ((10, 10),))
        self.assertEqual(fmt.render(f, 0, '1ß'), ['1SS OAK DR'])

    def test_explicit_suffix_replacements(self):
        fmt = definition([
            {'lines': ['{number} {street}']},
            {'lines': ['{number} {street}'], 'replacements': {'street_suffix': {'DR': 'DRIVE'}}},
        ])
        self.assertEqual(fmt.bounds(family()), ((10, 13),))
        self.assertEqual(fmt.render(family(), 1, '42'), ['42 OAK DRIVE'])

    def test_describe_exposes_lines_and_required_fields(self):
        result = definition().describe()
        self.assertEqual(result['line_count'], 2)
        self.assertEqual(result['match_rule'], 'contains_entire_indexed_range')
        self.assertIn('number', result['variants'][0]['fields'])

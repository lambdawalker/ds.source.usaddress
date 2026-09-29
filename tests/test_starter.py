import csv
import importlib.util
import json
import lzma
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/prepare_starter.py'


class StarterTests(unittest.TestCase):
    def test_preparation_keeps_complete_rows_and_records_rejections(self):
        self.assertTrue(SCRIPT.exists(), 'starter preparation script is missing')
        spec = importlib.util.spec_from_file_location('prepare_starter', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / '01001.csv.xz'
            with lzma.open(data, 'wt') as f:
                writer = csv.writer(f)
                writer.writerow(['address'])
                writer.writerows([['10 oak dr, boston, ma, 02108'], ['90 oak dr, boston, ma, 02108'],
                                 ['12 oak dr, , ma, 02108'], ['14 oak dr, boston, ma, 2108'],
                                 ['16 oak dr apt 2, boston, ma, 02108'], ['']])
            result = module.prepare([data], root / 'output', limit=10)
            self.assertEqual(result['selected_point_count'], 2)
            self.assertEqual(result['address_family_count'], 1)
            self.assertEqual(result['files'][0]['rejected_rows'], 4)
            row = json.loads((root / 'output/starter.addresses.jsonl').read_text())
            self.assertEqual(row['numbers']['values'], ['10', '90'])
            self.assertEqual(row['components']['zip'], '02108')
            self.assertEqual(row['components']['street_name'], 'OAK DR')

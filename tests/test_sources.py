import csv
import io
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from usaddress_dataset.sources import import_jsonl, import_points_csv, import_tiger, dbf_rows
from usaddress_dataset.store import RawStore
from test_core import SOURCE, family


def write_csv(path, headers, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def dbf_fixture(fields, rows):
    sizes = [max(1, max((len(str(row.get(k, ''))) for row in rows), default=1)) for k in fields]
    head = bytearray(32)
    head[0] = 3
    struct.pack_into('<IHH', head, 4, len(rows), 33 + 32 * len(fields), 1 + sum(sizes))
    output = bytes(head)
    for key, size in zip(fields, sizes):
        field = bytearray(32)
        field[:len(key)] = key.encode('ascii')
        field[11] = ord('C')
        field[16] = size
        output += field
    output += b'\r'
    for row in rows:
        output += b' ' + b''.join(str(row.get(k, '')).encode('ascii').ljust(n) for k, n in zip(fields, sizes))
    return output + b'\x1a'


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = self.root / 'raw.sqlite'
        RawStore.create(self.raw).close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_jsonl_bad_row_rolls_back_all_records(self):
        path = self.root / 'input.jsonl'
        path.write_text(json.dumps(family().to_dict()) + '\n{bad\n')
        with self.assertRaises(ValueError):
            import_jsonl(self.raw, path, SOURCE)
        with RawStore(self.raw) as raw:
            self.assertEqual(list(raw.families()), [])

    def test_points_group_explicit_values_without_inferring_ranges(self):
        path = self.root / 'points.csv'
        rows = [dict(NUMBER=n, STREET='OAK DR', CITY='BOSTON', REGION='MA', POSTCODE='02108', UNIT='') for n in ['10', '90', '10']]
        rows.append(dict(rows[0], NUMBER='12', UNIT='2B'))
        rows.append(dict(rows[0], POSTCODE=''))
        write_csv(path, list(rows[0]), rows)
        report = import_points_csv(self.raw, path, SOURCE)
        self.assertEqual(report['accepted_rows'], 4)
        self.assertEqual(report['rejected_rows'], 1)
        with RawStore(self.raw) as raw:
            families = list(raw.families())
        self.assertEqual(len(families), 2)
        base = next(f for f in families if not f.components.get('unit'))
        self.assertEqual(base.numbers.values, ('10', '90'))
        self.assertEqual(base.numbers.ranges, ())
        self.assertEqual(base.components['zip'], '02108')

    def tiger_fixture(self, zip_mode=False):
        rows = [dict(TLID='1', LINEARID='street1', FULLNAME='OAK DR',
                     LFROMHN='100', LTOHN='10', PARITYL='E', ZIPL='02108',
                     RFROMHN='11', RTOHN='99', PARITYR='O', ZIPR='02109')]
        mapping = self.root / 'localities.csv'
        write_csv(mapping, ['ZIP', 'CITY', 'STATE'], [dict(ZIP='02108', CITY='BOSTON', STATE='MA'), dict(ZIP='02109', CITY='BOSTON', STATE='MA')])
        source = dict(SOURCE, locality_source='local test mapping')
        if zip_mode:
            path = self.root / 'tiger.zip'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('tl_test_addrfeat.dbf', dbf_fixture(list(rows[0]), rows))
        else:
            path = self.root / 'tiger.csv'
            write_csv(path, list(rows[0]), rows)
        return rows, mapping, source, path

    def test_tiger_preserves_sides_zip_and_parity(self):
        _, mapping, source, path = self.tiger_fixture()
        report = import_tiger(self.raw, path, mapping, source)
        self.assertEqual(report['accepted_rows'], 2)
        with RawStore(self.raw) as raw:
            sides = list(raw.families())
        self.assertEqual({f.components['zip'] for f in sides}, {'02108', '02109'})
        left = next(f for f in sides if f.source_record.endswith(':L'))
        self.assertEqual(left.numbers.to_dict()['ranges'], [{'start': 10, 'end': 100, 'step': 2}])

    def test_tiger_zip_uses_dbf_without_extracting(self):
        _, mapping, source, path = self.tiger_fixture(zip_mode=True)
        report = import_tiger(self.raw, path, mapping, source)
        self.assertEqual(report['accepted_rows'], 2)
        self.assertFalse((self.root / 'tl_test_addrfeat.dbf').exists())

    def test_tiger_missing_mapping_and_non_numeric_ranges_are_reported(self):
        rows, mapping, source, path = self.tiger_fixture()
        rows[0].update(LFROMHN='12A', LTOHN='20A', ZIPR='99999')
        write_csv(path, list(rows[0]), rows)
        report = import_tiger(self.raw, path, mapping, source)
        self.assertEqual(report['accepted_rows'], 0)
        self.assertEqual(report['rejected_rows'], 2)
        self.assertEqual(report['rejected_by_reason'], {'unsupported_number_range': 1, 'missing_locality_mapping': 1})

    def test_tiger_leading_zero_endpoint_not_silently_changed(self):
        rows, mapping, source, path = self.tiger_fixture()
        rows[0].update(LFROMHN='0010', LTOHN='0100')
        write_csv(path, list(rows[0]), rows)
        report = import_tiger(self.raw, path, mapping, source)
        self.assertEqual(report['rejected_by_reason'], {'unsupported_number_range': 1})

    def test_tiger_equal_numeric_endpoints_still_require_consistent_parity(self):
        rows, mapping, source, path = self.tiger_fixture()
        rows[0].update(LFROMHN='11', LTOHN='11', PARITYL='E', RFROMHN='10', RTOHN='10', PARITYR='X')
        write_csv(path, list(rows[0]), rows)
        report = import_tiger(self.raw, path, mapping, source)
        self.assertEqual(report['accepted_rows'], 0)
        self.assertEqual(report['rejected_by_reason'], {'parity_mismatch': 1, 'unsupported_parity': 1})

    def test_conflicting_zip_mapping_is_rejected(self):
        _, mapping, source, path = self.tiger_fixture()
        write_csv(mapping, ['ZIP', 'CITY', 'STATE'], [dict(ZIP='02108', CITY='BOSTON', STATE='MA'), dict(ZIP='02108', CITY='OTHER', STATE='MA')])
        with self.assertRaises(ValueError):
            import_tiger(self.raw, path, mapping, source)

    def test_dbf_truncated_file_is_rejected(self):
        raw = dbf_fixture(['NAME'], [{'NAME': 'OAK'}])
        self.assertEqual(list(dbf_rows(io.BytesIO(raw))), [{'NAME': 'OAK'}])
        with self.assertRaises(ValueError):
            list(dbf_rows(io.BytesIO(raw[:-3])))

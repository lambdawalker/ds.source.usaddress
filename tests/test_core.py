import random
from unittest.mock import patch
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from usaddress_dataset.models import AddressFamily, NumberDomain, NumberRange
from usaddress_dataset.store import RawStore

SOURCE = {'id': 'test', 'name': 'Test fixtures', 'url': 'https://example.com', 'license': 'test', 'retrieved_at': '2026-09-29'}


def family(key='a', numbers=None, **components):
    return AddressFamily(key, dict(street_name='OAK', street_suffix='DR', city='BOSTON', state='MA', zip='02108', **components),
                         numbers or NumberDomain(ranges=(NumberRange(10, 100),)), 'test', key)


class NumberTests(unittest.TestCase):
    def test_maximum_width_and_natural_output(self):
        domain = NumberDomain(ranges=(NumberRange(10, 100),))
        self.assertEqual(domain.reserved_width, 3)
        values = {domain.sample(random.Random(i)) for i in range(500)}
        self.assertIn('10', values)
        self.assertIn('100', values)
        self.assertNotIn('010', values)

    def test_parity_and_reachable_endpoint(self):
        domain = NumberDomain(ranges=(NumberRange(90, 100, 3),))
        self.assertEqual(domain.reserved_width, 2)
        self.assertEqual({domain.sample(random.Random(i)) for i in range(100)}, {'90', '93', '96', '99'})

    def test_explicit_numbers_are_strings_and_normalized(self):
        domain = NumberDomain(values=('0012', '16 1/2', '12A', '12A'))
        self.assertEqual(domain.reserved_width, 6)
        self.assertEqual(len(domain.values), 3)
        self.assertIn('0012', {domain.sample(random.Random(i)) for i in range(100)})

    def test_invalid_domains(self):
        for args in [(3, 2, 1), (1, 2, 0), (-1, 4, 1), (True, 5, 1), (1.0, 5, 1)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                NumberRange(*args)
        for kw in [{}, {'values': ('',)}, {'values': ('12\n34',)}, {'values': (12,)}]:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                NumberDomain(**kw)

    def test_number_containers_do_not_split_strings_into_invented_values(self):
        for value in ['123', {'12': True}, None, 123]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                NumberDomain.from_dict({'values': value})
        with self.assertRaises(ValueError):
            NumberDomain(values='123')
        for ranges in ['123', {}, None]:
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                NumberDomain.from_dict({'ranges': ranges, 'values': ['12']})

    def test_large_ranges_sample_without_expanding(self):
        domain = NumberDomain(ranges=(NumberRange(1, 10**12, 2),))
        value = int(domain.sample(random.Random(3)))
        self.assertTrue(1 <= value < 10**12)
        self.assertEqual(value % 2, 1)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'raw.sqlite'
        self.store = RawStore.create(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_components_preserve_zip_and_share_storage(self):
        self.store.import_families([family('a'), family('b')], SOURCE)
        self.assertEqual(self.store.get('a').components['zip'], '02108')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('select count(*) from component_groups').fetchone()[0], 3)
        self.assertEqual(len(list(self.store.families())), 2)

    def test_repeated_import_is_idempotent(self):
        self.store.import_families([family()], SOURCE)
        before = self.store.snapshot
        self.store.import_families([family()], SOURCE)
        self.assertEqual(self.store.snapshot, before)
        changed = family(numbers=NumberDomain(values=('42',)))
        self.store.import_families([changed], SOURCE)
        self.assertEqual(self.store.snapshot['revision'], before['revision'] + 1)

    def test_failed_import_rolls_back(self):
        self.store.import_families([family()], SOURCE)
        before = self.store.snapshot
        def broken():
            yield family('b')
            raise ValueError('bad source row')
        with self.assertRaises(ValueError):
            self.store.import_families(broken(), SOURCE)
        self.assertEqual([f.id for f in self.store.families()], ['a'])
        self.assertEqual(before, self.store.snapshot)

    def test_read_only_and_no_overwrite(self):
        with self.assertRaises(FileExistsError):
            RawStore.create(self.path)
        with RawStore(self.path) as reader:
            with self.assertRaises(PermissionError):
                reader.import_families([family()], SOURCE)

    def test_creation_closes_all_sqlite_connections(self):
        connections = []
        connect = sqlite3.connect
        def capture(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connections.append(connection)
            return connection
        try:
            with patch('usaddress_dataset.store.sqlite3.connect', side_effect=capture):
                created = RawStore.create(Path(self.tmp.name) / 'created.sqlite')
                created.close()
            for connection in connections:
                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute('SELECT 1')
        finally:
            for connection in connections:
                connection.close()

    def test_missing_path_is_not_created(self):
        missing = Path(self.tmp.name) / 'missing.sqlite'
        with self.assertRaises((FileNotFoundError, sqlite3.OperationalError)):
            RawStore(missing)
        self.assertFalse(missing.exists())

    def test_family_input_is_copied_and_rejects_bad_components(self):
        data = {'street_name': 'OAK', 'city': 'BOSTON', 'state': 'MA', 'zip': '02108'}
        f = AddressFamily('a', data, NumberDomain(values=('1',)), 'test')
        data['zip'] = '99999'
        self.assertEqual(f.components['zip'], '02108')
        for bad in [{'zip': 2108}, {'street_name': 'A\nB'}, {'state': 'Massachusetts'}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                AddressFamily('a', bad, NumberDomain(values=('1',)), 'test')

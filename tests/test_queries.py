import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from usaddress_dataset.formats import FormatDefinition
from usaddress_dataset.indexer import FormatIndexer
from usaddress_dataset.query import FormatQuery, StaleIndexError
from usaddress_dataset.store import RawStore
from test_core import family, SOURCE
from test_formats import definition


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name) / 'raw.sqlite'
        self.index = Path(self.tmp.name) / 'format.sqlite'
        with RawStore.create(self.raw) as store:
            store.import_families([family('a'), family('b')], SOURCE)
        FormatIndexer.build(self.raw, self.index, definition())

    def tearDown(self):
        self.tmp.cleanup()

    def test_containment_inclusive_on_every_line(self):
        with FormatQuery(self.raw, self.index) as q:
            for bounds, expected in [([(0, 20), (10, 22)], 2), ([(10, 10), (15, 16)], 2),
                                     ([(0, 9), (10, 22)], 0), ([(10, 10), (16, 22)], 0),
                                     ([(10, 10), (10, 15)], 0)]:
                with self.subTest(bounds=bounds):
                    self.assertEqual(q.count(bounds), expected)

    def test_metadata_counts_families_not_variants(self):
        with FormatQuery(self.raw, self.index) as q:
            meta = q.metadata()
        self.assertEqual(meta['address_count'], 2)
        self.assertEqual(meta['consolidated_ranges'], [[10, 10], [15, 16]])
        self.assertEqual(meta['range_distribution'], [{'ranges': [[10, 10], [15, 16]], 'address_count': 2}])

    def test_correlation_is_preserved_in_histogram(self):
        with RawStore(self.raw, writable=True) as store:
            store.import_families([family('c', street_prefix='N')], SOURCE)
        FormatIndexer.build(self.raw, self.index, definition())
        with FormatQuery(self.raw, self.index) as q:
            meta = q.metadata()
        self.assertEqual(meta['consolidated_ranges'], [[10, 12], [15, 16]])
        self.assertEqual(meta['range_distribution'], [
            {'ranges': [[10, 10], [15, 16]], 'address_count': 2},
            {'ranges': [[12, 12], [15, 16]], 'address_count': 1}])

    def test_natural_short_number_is_not_rejected(self):
        with FormatQuery(self.raw, self.index) as q:
            result = q.query([(10, 10), (15, 16)], count=100, seed=7)
        self.assertEqual(len(result['results']), 100)
        self.assertTrue(any(r['actual_lengths'][0] == 9 for r in result['results']))
        for row in result['results']:
            self.assertEqual(row['reserved_lengths'][0], 10)
            self.assertEqual(row['actual_lengths'], [len(v) for v in row['lines']])

    def test_seed_and_every_eligible_family(self):
        with FormatQuery(self.raw, self.index) as q:
            a = q.query([(0, 50), (0, 50)], count=50, seed=1)
            b = q.query([(0, 50), (0, 50)], count=50, seed=1)
        self.assertEqual(a, b)
        self.assertEqual({v['address_id'] for v in a['results']}, {'a', 'b'})

    def test_unique_family_exhaustion_and_empty_results(self):
        with FormatQuery(self.raw, self.index) as q:
            result = q.query([(0, 50), (0, 50)], count=5, seed=1, unique_families=True)
            empty = q.query([(0, 1), (0, 1)], count=5)
        self.assertEqual(len(result['results']), 2)
        self.assertEqual(result['status'], 'insufficient_unique_families')
        self.assertEqual(empty['status'], 'no_matches')
        self.assertEqual(empty['results'], [])

    def test_bad_query_shapes_and_bounds(self):
        with FormatQuery(self.raw, self.index) as q:
            for bounds in [[], [(0, 10)], [(-1, 10), (0, 20)], [(10, 5), (0, 20)], [(True, 5), (0, 20)]]:
                with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                    q.count(bounds)
            with self.assertRaises(ValueError):
                q.query([(0, 20), (0, 20)], count=-1)

    def test_indexing_does_not_modify_raw_or_copy_components(self):
        before = self.raw.read_bytes()
        FormatIndexer.build(self.raw, self.index, definition())
        self.assertEqual(before, self.raw.read_bytes())
        with closing(sqlite3.connect(self.index)) as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            self.assertNotIn('component_groups', tables)
            self.assertNotIn('sources', tables)
        self.assertNotIn(b'OAK', self.index.read_bytes())

    def test_stale_revision_and_wrong_database_are_rejected(self):
        with RawStore(self.raw, writable=True) as store:
            store.import_families([family('new')], SOURCE)
        with self.assertRaises(StaleIndexError):
            FormatQuery(self.raw, self.index)
        other = Path(self.tmp.name) / 'other.sqlite'
        with RawStore.create(other) as store:
            store.import_families([family('a'), family('b')], SOURCE)
        with self.assertRaises(StaleIndexError):
            FormatQuery(other, self.index)

    def test_failed_rebuild_preserves_old_index(self):
        before = self.index.read_bytes()
        with patch.object(FormatDefinition, 'bounds', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                FormatIndexer.build(self.raw, self.index, definition())
        self.assertEqual(before, self.index.read_bytes())

    def test_cannot_overwrite_raw_with_index(self):
        before = self.raw.read_bytes()
        with self.assertRaises(ValueError):
            FormatIndexer.build(self.raw, self.raw, definition())
        self.assertEqual(before, self.raw.read_bytes())

    def test_empty_index_reports_skips(self):
        fmt = definition([{'lines': ['{unit_type} {unit}']}])
        FormatIndexer.build(self.raw, self.index, fmt)
        with FormatQuery(self.raw, self.index) as q:
            meta = q.metadata()
        self.assertEqual(meta['address_count'], 0)
        self.assertEqual(meta['skipped_address_count'], 2)
        self.assertIsNone(meta['consolidated_ranges'])
        self.assertEqual(meta['range_distribution'], [])

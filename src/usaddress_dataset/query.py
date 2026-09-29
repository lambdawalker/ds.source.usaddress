"""Whole-interval containment queries and reproducible uniform family sampling."""
from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

from .formats import FormatDefinition
from .indexer import INDEX_VERSION
from .store import RawStore


class StaleIndexError(ValueError):
    """The index was built from another raw snapshot or unsupported format engine."""


class FormatQuery:
    def __init__(self, raw_path, index_path):
        self.raw = RawStore(raw_path)
        self.db = None
        try:
            self.db = sqlite3.connect(Path(index_path).resolve().as_uri() + '?mode=ro', uri=True)
            self.db.execute('BEGIN')
            self.manifest = {k: json.loads(v) for k, v in self.db.execute('SELECT key,value FROM manifest')}
            if self.manifest['source_snapshot'] != self.raw.snapshot:
                raise StaleIndexError('raw dataset snapshot changed; rebuild this format index')
            if self.manifest['index_version'] != INDEX_VERSION:
                raise StaleIndexError('unsupported index engine version; rebuild the index')
            self.definition = FormatDefinition.from_dict(self.manifest['format'])
            if self.definition.fingerprint != self.manifest['format_fingerprint']:
                raise StaleIndexError('format definition does not match its fingerprint')
        except Exception:
            self.close()
            raise

    def describe(self) -> dict:
        return self.definition.describe()

    def metadata(self) -> dict:
        return json.loads(json.dumps({**self.manifest['metadata'], 'format_id': self.definition.id,
            'format_version': self.definition.version, 'source_snapshot': self.manifest['source_snapshot']}))

    def _selection(self, line_ranges):
        if not isinstance(line_ranges, (list, tuple)) or len(line_ranges) != self.definition.line_count:
            raise ValueError(f'expected {self.definition.line_count} line ranges')
        predicates, values = [], []
        for i, bounds in enumerate(line_ranges):
            if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                raise ValueError('each range must contain exactly two integers')
            low, high = bounds
            if type(low) is not int or type(high) is not int or not 0 <= low <= high:
                raise ValueError('require integer 0 <= min <= max')
            predicates.append('(line=? AND min_length>=? AND max_length<=?)')
            values.extend([i, low, high])
        # One row per family/line, so HAVING count=N enforces every line.
        return ('SELECT address_id FROM line_ranges WHERE ' + ' OR '.join(predicates) +
                ' GROUP BY address_id HAVING COUNT(*)=?'), [*values, self.definition.line_count]

    def count(self, line_ranges) -> int:
        sql, args = self._selection(line_ranges)
        return self.db.execute('SELECT COUNT(*) FROM (' + sql + ')', args).fetchone()[0]

    def query(self, line_ranges, *, count=1, seed=None, unique_families=False) -> dict:
        if type(count) is not int or count < 0:
            raise ValueError('count must be a nonnegative integer')
        if type(unique_families) is not bool:
            raise ValueError('unique_families must be a boolean')
        sql, args = self._selection(line_ranges)
        # Entire eligible population, never LIMIT before sampling. v0.1 holds IDs in memory.
        eligible = [row[0] for row in self.db.execute(sql + ' ORDER BY address_id', args)]
        rng = random.Random(seed)
        status = 'ok'
        if not eligible and count:
            selected = []
            status = 'no_matches'
        elif unique_families:
            selected = rng.sample(eligible, min(count, len(eligible)))
            if count > len(eligible):
                status = 'insufficient_unique_families'
        else:
            selected = [rng.choice(eligible) for _ in range(count)]
        results = []
        for address_id in selected:
            address = self.raw.get(address_id)
            variant = rng.choice(self.definition.variants_for(address))
            number = address.numbers.sample(rng)
            lines = self.definition.render(address, variant, number)
            reserved = self.definition.reserved_lengths(address, variant)
            actual = [len(line) for line in lines]
            if any(a > r for a, r in zip(actual, reserved)):
                raise RuntimeError('rendered output exceeded indexed budget; rebuild after fixing format')
            bounds = json.loads(self.db.execute('SELECT ranges_json FROM addresses WHERE address_id=?', (address_id,)).fetchone()[0])
            results.append(dict(address_id=address_id, format_id=self.definition.id, format_version=self.definition.version,
                variant=variant, number=number, lines=lines, actual_lengths=actual, reserved_lengths=reserved,
                indexed_ranges=bounds, components=dict(address.components), source_id=address.source_id,
                source_record=address.source_record))
        return dict(status=status, requested_count=count, returned_count=len(results), eligible_address_count=len(eligible),
            source_snapshot=self.manifest['source_snapshot'], format_fingerprint=self.definition.fingerprint,
            sampler_version=1, seed=seed, results=results)

    def close(self):
        if self.db is not None:
            self.db.close()
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

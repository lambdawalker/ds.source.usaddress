"""Atomically rebuilt format-only SQLite indexes with consolidated range metadata."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from .formats import FormatDefinition
from .store import RawStore, encoded

INDEX_VERSION = 1


class FormatIndexer:
    @staticmethod
    def build(raw_path, index_path, definition: FormatDefinition) -> dict:
        raw_path, index_path = Path(raw_path).resolve(), Path(index_path).resolve()
        if raw_path == index_path or (index_path.exists() and os.path.samefile(raw_path, index_path)):
            raise ValueError('format index cannot replace the raw database')
        index_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=index_path.name + '.', suffix='.tmp', dir=index_path.parent)
        os.close(fd)
        db = None
        try:
            with RawStore(raw_path) as raw:
                snapshot = raw.snapshot
                db = sqlite3.connect(temporary)
                db.executescript('''
                    CREATE TABLE manifest(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE addresses(address_id TEXT PRIMARY KEY, ranges_json TEXT NOT NULL);
                    CREATE TABLE line_ranges(address_id TEXT NOT NULL REFERENCES addresses(address_id),
                        line INTEGER NOT NULL, min_length INTEGER NOT NULL, max_length INTEGER NOT NULL,
                        PRIMARY KEY(address_id,line));
                    CREATE INDEX range_lookup ON line_ranges(line,min_length,max_length,address_id);
                    CREATE INDEX range_groups ON addresses(ranges_json);
                ''')
                skipped = 0
                total = 0
                with db:
                    for address in raw.families():
                        total += 1
                        bounds = definition.bounds(address)
                        if bounds is None:
                            skipped += 1
                            continue
                        db.execute('INSERT INTO addresses VALUES (?,?)', (address.id, encoded(bounds)))
                        db.executemany('INSERT INTO line_ranges VALUES (?,?,?,?)',
                                       [(address.id, i, low, high) for i, (low, high) in enumerate(bounds)])
                    distribution = [dict(ranges=json.loads(row[0]), address_count=row[1]) for row in db.execute(
                        'SELECT ranges_json,COUNT(*) FROM addresses GROUP BY ranges_json')]
                    distribution.sort(key=lambda item: item['ranges'])
                    consolidated = [[r[0], r[1]] for r in db.execute(
                        'SELECT MIN(min_length),MAX(max_length) FROM line_ranges GROUP BY line ORDER BY line')]
                    metadata = dict(address_count=total-skipped, raw_address_count=total,
                        skipped_address_count=skipped, skip_reason='missing_required_components' if skipped else None,
                        consolidated_ranges=consolidated or None, range_distribution=distribution)
                    values = dict(index_version=INDEX_VERSION, source_snapshot=snapshot, format=definition.to_dict(),
                                  format_fingerprint=definition.fingerprint, metadata=metadata)
                    db.executemany('INSERT INTO manifest VALUES (?,?)', [(k, encoded(v)) for k, v in values.items()])
                db.close()
                db = None
            os.replace(temporary, index_path)
            return metadata
        finally:
            if db is not None:
                db.close()
            Path(temporary).unlink(missing_ok=True)

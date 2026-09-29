"""Normalized raw SQLite storage. Import transactions increment one snapshot revision."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Iterable

from .models import AddressFamily, NumberDomain, STREET_FIELDS, LOCALITY_FIELDS, UNIT_FIELDS


def encoded(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


class RawStore:
    def __init__(self, path, *, writable=False):
        self.path = Path(path).resolve()
        self.writable = writable
        self.db = sqlite3.connect(self.path.as_uri() + ('?mode=rw' if writable else '?mode=ro'), uri=True)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        if not writable:
            self.db.execute('BEGIN')  # Pin a consistent raw snapshot for this reader.
        try:
            if self.snapshot['schema_version'] != 1:
                raise ValueError('unsupported raw schema version')
        except Exception:
            self.db.close()
            raise

    @classmethod
    def create(cls, path) -> RawStore:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb'):
            pass
        try:
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('''
                    CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE sources(id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
                    CREATE TABLE component_groups(id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
                        content TEXT NOT NULL, UNIQUE(kind, content));
                    CREATE TABLE families(id TEXT PRIMARY KEY,
                        street_id INTEGER NOT NULL REFERENCES component_groups(id),
                        locality_id INTEGER NOT NULL REFERENCES component_groups(id),
                        unit_id INTEGER NOT NULL REFERENCES component_groups(id),
                        numbers TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id),
                        source_record TEXT NOT NULL);
                ''')
                db.executemany('INSERT INTO metadata VALUES (?,?)', [('schema_version', '1'), ('dataset_id', str(uuid.uuid4())), ('revision', '0')])
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return cls(path, writable=True)

    @property
    def snapshot(self) -> dict:
        values = dict(self.db.execute('SELECT key, value FROM metadata'))
        return dict(schema_version=int(values['schema_version']), dataset_id=values['dataset_id'], revision=int(values['revision']))

    def import_families(self, families: Iterable[AddressFamily], source: dict) -> dict:
        if not self.writable:
            raise PermissionError('raw store was opened read-only')
        if not all(isinstance(source.get(k), str) and source[k] for k in ('id', 'name', 'url', 'license', 'retrieved_at')):
            raise ValueError('source requires id, name, url, license and retrieved_at strings')
        changed = 0
        seen = 0
        with self.db:
            before = self.db.total_changes
            self.db.execute('''INSERT INTO sources VALUES (?,?) ON CONFLICT(id) DO UPDATE
                SET metadata=excluded.metadata WHERE metadata != excluded.metadata''', (source['id'], encoded(source)))
            for family in families:
                seen += 1
                if family.source_id != source['id']:
                    raise ValueError('family source_id does not match import source')
                previous = self.db.execute('SELECT source_id FROM families WHERE id=?', (family.id,)).fetchone()
                if previous and previous[0] != source['id']:
                    raise ValueError('address ID already belongs to another source')
                refs = []
                for kind, fields in [('street', STREET_FIELDS), ('locality', LOCALITY_FIELDS), ('unit', UNIT_FIELDS)]:
                    content = encoded({k: family.components[k] for k in fields if family.components.get(k)})
                    self.db.execute('INSERT OR IGNORE INTO component_groups(kind,content) VALUES (?,?)', (kind, content))
                    refs.append(self.db.execute('SELECT id FROM component_groups WHERE kind=? AND content=?', (kind, content)).fetchone()[0])
                cursor = self.db.execute('''INSERT INTO families VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    street_id=excluded.street_id, locality_id=excluded.locality_id, unit_id=excluded.unit_id,
                    numbers=excluded.numbers, source_id=excluded.source_id, source_record=excluded.source_record
                    WHERE street_id!=excluded.street_id OR locality_id!=excluded.locality_id OR unit_id!=excluded.unit_id
                    OR numbers!=excluded.numbers OR source_id!=excluded.source_id OR source_record!=excluded.source_record''',
                    (family.id, *refs, encoded(family.numbers.to_dict()), family.source_id, family.source_record))
                changed += cursor.rowcount
            if self.db.total_changes != before:
                self.db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
        return dict(seen=seen, changed=changed, snapshot=self.snapshot)

    _SELECT = '''SELECT f.*, s.content AS street, l.content AS locality, u.content AS unit
        FROM families f JOIN component_groups s ON f.street_id=s.id
        JOIN component_groups l ON f.locality_id=l.id JOIN component_groups u ON f.unit_id=u.id'''

    @staticmethod
    def _family(row) -> AddressFamily:
        components = {**json.loads(row['street']), **json.loads(row['locality']), **json.loads(row['unit'])}
        return AddressFamily(row['id'], components, NumberDomain.from_dict(json.loads(row['numbers'])), row['source_id'], row['source_record'])

    def families(self):
        for row in self.db.execute(self._SELECT + ' ORDER BY f.id'):
            yield self._family(row)

    def get(self, address_id: str) -> AddressFamily:
        row = self.db.execute(self._SELECT + ' WHERE f.id=?', (address_id,)).fetchone()
        if row is None:
            raise KeyError(address_id)
        return self._family(row)

    def sources(self) -> list[dict]:
        return [json.loads(row[0]) for row in self.db.execute('SELECT metadata FROM sources ORDER BY id')]

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

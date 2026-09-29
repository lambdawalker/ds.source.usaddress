"""Declarative complete presentation variants, shared by measurement and rendering."""
from __future__ import annotations

import hashlib
import json
import re
import string
import unicodedata
from pathlib import Path

from .models import AddressFamily, COMPONENT_FIELDS, STREET_FIELDS, text_value
from .store import encoded

FIELDS = set(COMPONENT_FIELDS) | {'number', 'street'}


class FormatDefinition:
    def __init__(self, data: dict):
        data = json.loads(encoded(data))  # Isolate caller mutation.
        if set(data) - {'id', 'version', 'description', 'case', 'variants'}:
            raise ValueError('unknown format properties')
        if not isinstance(data.get('id'), str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', data['id']):
            raise ValueError('format id must contain letters, digits, underscores or hyphens')
        if type(data.get('version')) is not int or data['version'] < 1:
            raise ValueError('format version must be a positive integer')
        if data.get('case', 'upper') not in ('upper', 'source'):
            raise ValueError('case must be upper or source')
        variants = data.get('variants')
        if not isinstance(variants, list) or not variants:
            raise ValueError('at least one variant is required')
        fields = []
        line_count = None
        for variant in variants:
            if not isinstance(variant, dict) or set(variant) - {'lines', 'replacements'}:
                raise ValueError('variant supports lines and replacements only')
            lines = variant.get('lines')
            if not isinstance(lines, list) or not lines:
                raise ValueError('variant must contain lines')
            if line_count is not None and len(lines) != line_count:
                raise ValueError('every variant must have the same line count')
            line_count = len(lines)
            names = set()
            for line in lines:
                if not isinstance(line, str) or not text_value(line) or line != line.strip():
                    raise ValueError('line templates must be nonblank with no surrounding whitespace')
                for _, field, spec, conversion in string.Formatter().parse(line):
                    if field is not None:
                        if field not in FIELDS or spec or conversion:
                            raise ValueError('only plain named address placeholders are supported')
                        names.add(field)
            replacements = variant.get('replacements', {})
            if not isinstance(replacements, dict):
                raise ValueError('replacements must map component names to lookup tables')
            for field, mapping in replacements.items():
                if field not in COMPONENT_FIELDS or not isinstance(mapping, dict):
                    raise ValueError('replacements apply only to raw components')
                for key, value in mapping.items():
                    if not text_value(key) or not text_value(value):
                        raise ValueError('replacement keys and values must be nonblank strings')
            fields.append(frozenset(names))
        data.setdefault('case', 'upper')
        data.setdefault('description', '')
        self._json = encoded(data)
        self._fields = tuple(fields)
        self.id = data['id']
        self.version = data['version']
        self.line_count = line_count

    @classmethod
    def from_dict(cls, data: dict) -> FormatDefinition:
        return cls(data)

    @classmethod
    def load(cls, path) -> FormatDefinition:
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    def to_dict(self) -> dict:
        return json.loads(self._json)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self._json.encode('utf-8')).hexdigest()

    def _transform(self, value: str) -> str:
        if self.to_dict()['case'] == 'upper':
            value = value.upper()
        return unicodedata.normalize('NFC', value)

    def _values(self, address: AddressFamily, variant: int, number: str) -> dict:
        values = {k: address.components.get(k, '') for k in COMPONENT_FIELDS}
        for field, replacements in self.to_dict()['variants'][variant].get('replacements', {}).items():
            values[field] = replacements.get(values[field], values[field])
        values['street'] = ' '.join(values[k] for k in STREET_FIELDS if values[k])
        # A direction/suffix alone is not a street name.
        if not values['street_name']:
            values['street'] = ''
        values['number'] = number
        return values

    def variants_for(self, address: AddressFamily) -> list[int]:
        return [i for i, fields in enumerate(self._fields)
                if all(self._values(address, i, '0')[field] for field in fields)]

    def render(self, address: AddressFamily, variant: int, number: str) -> list[str]:
        if variant not in self.variants_for(address):
            raise ValueError('address is missing components required by this variant')
        values = self._values(address, variant, text_value(number))
        return [self._transform(line.format_map(values)) for line in self.to_dict()['variants'][variant]['lines']]

    def reserved_lengths(self, address: AddressFamily, variant: int) -> list[int]:
        width = max([len(str(r.last)) for r in address.numbers.ranges] +
                    [len(self._transform(v)) for v in address.numbers.values])
        return [len(line) for line in self.render(address, variant, '0' * width)]

    def bounds(self, address: AddressFamily):
        vectors = [self.reserved_lengths(address, i) for i in self.variants_for(address)]
        if not vectors:
            return None
        return tuple((min(column), max(column)) for column in zip(*vectors))

    def describe(self) -> dict:
        data = self.to_dict()
        return {**data, 'fingerprint': self.fingerprint, 'line_count': self.line_count,
                'match_rule': 'contains_entire_indexed_range',
                'length_unit': 'NFC Unicode code points; maximum number width reserved',
                'variants': [{**v, 'fields': sorted(fields)} for v, fields in zip(data['variants'], self._fields)]}

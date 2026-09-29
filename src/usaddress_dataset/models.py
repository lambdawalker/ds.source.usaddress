"""Immutable address components and compact, unexpanded number domains."""
from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

STREET_FIELDS = ('street_prefix', 'street_name', 'street_suffix', 'street_postdirection')
LOCALITY_FIELDS = ('city', 'state', 'zip', 'zip4')
UNIT_FIELDS = ('unit_type', 'unit')
COMPONENT_FIELDS = STREET_FIELDS + LOCALITY_FIELDS + UNIT_FIELDS


def text_value(value: str) -> str:
    if not isinstance(value, str) or any(unicodedata.category(c).startswith('C') for c in value):
        raise ValueError('components must be strings without control characters')
    return unicodedata.normalize('NFC', value.strip())


@dataclass(frozen=True)
class NumberRange:
    """Inclusive bounds; step is relative to start, not an inferred street rule."""
    start: int
    end: int
    step: int = 1

    def __post_init__(self):
        if any(type(v) is not int for v in (self.start, self.end, self.step)):
            raise ValueError('range values must be integers')
        if self.start < 0 or self.end < self.start or self.step < 1:
            raise ValueError('require 0 <= start <= end and step >= 1')

    @property
    def count(self) -> int:
        return (self.end - self.start) // self.step + 1

    @property
    def last(self) -> int:
        return self.start + (self.count - 1) * self.step


@dataclass(frozen=True)
class NumberDomain:
    """Ranges and/or explicit strings. Overlaps retain support but add sampling weight."""
    ranges: tuple[NumberRange, ...] = ()
    values: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.ranges, (list, tuple)) or not isinstance(self.values, (list, tuple)):
            raise ValueError('ranges and values must be arrays, not strings or objects')
        ranges = tuple(self.ranges)
        if not all(isinstance(r, NumberRange) for r in ranges):
            raise ValueError('ranges must contain NumberRange objects')
        values = tuple(sorted(set(text_value(v) for v in self.values)))
        if not (ranges or values) or any(not v for v in values):
            raise ValueError('number domain must be nonempty, with no blank values')
        object.__setattr__(self, 'ranges', ranges)
        object.__setattr__(self, 'values', values)

    @property
    def reserved_width(self) -> int:
        return max([len(str(r.last)) for r in self.ranges] + [len(v) for v in self.values])

    def sample(self, rng: random.Random) -> str:
        ticket = rng.randrange(sum(r.count for r in self.ranges) + len(self.values))
        for r in self.ranges:
            if ticket < r.count:
                return str(r.start + ticket * r.step)
            ticket -= r.count
        return self.values[ticket]

    def to_dict(self) -> dict:
        return {'ranges': [dict(start=r.start, end=r.end, step=r.step) for r in self.ranges], 'values': list(self.values)}

    @classmethod
    def from_dict(cls, data: dict) -> NumberDomain:
        if not isinstance(data, dict):
            raise ValueError('number domain must be an object')
        if set(data) - {'ranges', 'values'}:
            raise ValueError('unknown number domain fields')
        ranges, values = data.get('ranges', []), data.get('values', [])
        if not isinstance(ranges, (list, tuple)) or not isinstance(values, (list, tuple)):
            raise ValueError('ranges and values must be arrays, not strings or objects')
        if not all(isinstance(r, dict) for r in ranges):
            raise ValueError('each range must be an object')
        return cls(tuple(NumberRange(**r) for r in ranges), tuple(values))


@dataclass(frozen=True)
class AddressFamily:
    id: str
    components: Mapping[str, str]
    numbers: NumberDomain
    source_id: str
    source_record: str = ''

    def __post_init__(self):
        for name in ('id', 'source_id', 'source_record'):
            object.__setattr__(self, name, text_value(getattr(self, name)))
        if not self.id or not self.source_id:
            raise ValueError('id and source_id are required')
        if not isinstance(self.numbers, NumberDomain):
            raise ValueError('numbers must be a NumberDomain')
        if set(self.components) - set(COMPONENT_FIELDS):
            raise ValueError('unknown address component')
        components = {k: text_value(v) for k, v in self.components.items()}
        if components.get('state') and not re.fullmatch('[A-Z]{2}', components['state']):
            raise ValueError('state must be a two-letter uppercase code')
        if components.get('zip') and not re.fullmatch('[0-9]{5}', components['zip']):
            raise ValueError('ZIP must be five digits stored as a string')
        if components.get('zip4') and not re.fullmatch('[0-9]{4}', components['zip4']):
            raise ValueError('ZIP+4 extension must be four digits')
        object.__setattr__(self, 'components', MappingProxyType(components))

    def to_dict(self) -> dict:
        return dict(id=self.id, components=dict(self.components), numbers=self.numbers.to_dict(),
                    source_id=self.source_id, source_record=self.source_record)

    @classmethod
    def from_dict(cls, data: dict) -> AddressFamily:
        return cls(data['id'], data['components'], NumberDomain.from_dict(data['numbers']),
                   data['source_id'], data.get('source_record', ''))

"""Local, auditable source adapters. No network calls or inferred postal localities."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import struct
import zipfile
from collections import Counter
from pathlib import Path

from .models import AddressFamily, NumberDomain, NumberRange, text_value
from .store import RawStore, encoded


def import_jsonl(raw_path, input_path, source: dict) -> dict:
    def records():
        with Path(input_path).open(encoding='utf-8-sig') as stream:
            for line_number, line in enumerate(stream, 1):
                if line.strip():
                    try:
                        yield AddressFamily.from_dict(json.loads(line))
                    except (ValueError, KeyError, TypeError) as exc:
                        raise ValueError(f'JSONL line {line_number}: {exc}') from exc
    with RawStore(raw_path, writable=True) as raw:
        return raw.import_families(records(), source)


def _csv_rows(path, required):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError('missing CSV columns: ' + ', '.join(sorted(required - set(reader.fieldnames or []))))
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError('CSV row has the wrong number of columns')
            yield {k: v.strip() for k, v in row.items()}


def _report(result, accepted, reasons):
    return {**result, 'accepted_rows': accepted, 'rejected_rows': sum(reasons.values()),
            'rejected_by_reason': dict(sorted(reasons.items()))}


def import_points_csv(raw_path, input_path, source: dict) -> dict:
    """OpenAddresses-style columns; numbers are grouped as observed strings, never ranges.

    Required: NUMBER, STREET, CITY, REGION, POSTCODE. Optional: UNIT, UNIT_TYPE.
    Missing unit type remains missing; the adapter does not invent APT versus STE.
    """
    groups = {}
    reasons = Counter()
    accepted = 0
    for row in _csv_rows(input_path, {'NUMBER', 'STREET', 'CITY', 'REGION', 'POSTCODE'}):
        if not all(row[k] for k in ('NUMBER', 'STREET', 'CITY', 'REGION', 'POSTCODE')):
            reasons['missing_required_components'] += 1
            continue
        postcode = row['POSTCODE']
        if not re.fullmatch(r'[0-9]{5}(?:-[0-9]{4})?', postcode):
            reasons['invalid_postcode'] += 1
            continue
        components = dict(street_name=row['STREET'], city=row['CITY'], state=row['REGION'].upper(), zip=postcode[:5])
        if len(postcode) == 10:
            components['zip4'] = postcode[6:]
        for key, header in [('unit', 'UNIT'), ('unit_type', 'UNIT_TYPE')]:
            if row.get(header):
                components[key] = row[header]
        try:
            candidate = AddressFamily('validate', components, NumberDomain(values=(row['NUMBER'],)), source['id'])
        except ValueError:
            reasons['invalid_components'] += 1
            continue
        key = encoded(dict(candidate.components))
        groups.setdefault(key, set()).update(candidate.numbers.values)
        accepted += 1
    def families():
        for key in sorted(groups):
            address_id = source['id'] + ':' + hashlib.sha256(key.encode('utf-8')).hexdigest()
            yield AddressFamily(address_id, json.loads(key), NumberDomain(values=tuple(groups[key])), source['id'],
                                'component-group:' + address_id.split(':')[-1])
    with RawStore(raw_path, writable=True) as raw:
        result = raw.import_families(families(), source)
    return _report(result, accepted, reasons)


def dbf_rows(stream, encoding='utf-8'):
    """Read the character/numeric attribute fields used by Census ADDRFEAT DBFs.

    Geometry is unnecessary. Deleted records are skipped. Truncated or unsupported
    DBFs fail rather than silently creating an incomplete import.
    """
    header = stream.read(32)
    if len(header) != 32:
        raise ValueError('truncated DBF header')
    count, header_size, record_size = struct.unpack_from('<IHH', header, 4)
    if header_size < 33 or record_size < 2:
        raise ValueError('invalid DBF layout')
    descriptors = stream.read(header_size - 32)
    if len(descriptors) != header_size - 32:
        raise ValueError('truncated DBF field descriptors')
    fields = []
    offset = 0
    while offset < len(descriptors) and descriptors[offset] != 13:
        field = descriptors[offset:offset + 32]
        if len(field) != 32 or field[16] == 0:
            raise ValueError('invalid DBF field descriptor')
        name = field[:11].split(b'\0', 1)[0].decode('ascii')
        if not name or name in {f[0] for f in fields} or chr(field[11]) not in 'CNFDL':
            raise ValueError('unsupported or duplicate DBF field')
        fields.append((name, field[16]))
        offset += 32
    if offset >= len(descriptors) or descriptors[offset] != 13 or 1 + sum(n for _, n in fields) > record_size:
        raise ValueError('invalid DBF field layout')
    for _ in range(count):
        data = stream.read(record_size)
        if len(data) != record_size:
            raise ValueError('truncated DBF record')
        if data[:1] == b'*':
            continue
        if data[:1] != b' ':
            raise ValueError('invalid DBF deletion marker')
        row, offset = {}, 1
        for name, size in fields:
            row[name] = data[offset:offset + size].decode(encoding).strip(' \0')
            offset += size
        yield row


def _tiger_rows(path):
    path = Path(path)
    if path.suffix.lower() != '.zip':
        yield from _csv_rows(path, {'TLID', 'FULLNAME', 'LFROMHN', 'LTOHN', 'RFROMHN', 'RTOHN', 'ZIPL', 'ZIPR', 'PARITYL', 'PARITYR'})
        return
    with zipfile.ZipFile(path) as archive:
        candidates = [name for name in archive.namelist() if name.lower().endswith('_addrfeat.dbf')]
        if len(candidates) != 1:
            raise ValueError('ZIP must contain exactly one *_addrfeat.dbf file')
        encoding = 'utf-8'
        cpg = candidates[0][:-4] + '.cpg'
        if cpg in archive.namelist():
            encoding = archive.read(cpg).decode('ascii').strip()
            if encoding == '65001':
                encoding = 'utf-8'
            elif encoding.isdigit():
                encoding = 'cp' + encoding
        with archive.open(candidates[0]) as stream:
            yield from dbf_rows(stream, encoding)


def _number_domain(first, last, parity):
    if parity not in ('E', 'O', 'B'):
        raise ValueError('unsupported_parity')
    # Exact identical strings are safe, including fractions and leading zeros.
    if first == last and first:
        if re.fullmatch('[0-9]+', first) and parity != 'B' and int(first) % 2 != int(parity == 'O'):
            raise ValueError('parity_mismatch')
        return NumberDomain(values=(first,))
    if not all(re.fullmatch(r'0|[1-9][0-9]*', v) for v in (first, last)):
        raise ValueError('unsupported_number_range')
    low, high = sorted((int(first), int(last)))
    step = 1 if parity == 'B' else 2
    if step == 2:
        low += (int(parity == 'O') - low) % 2
    if low > high:
        raise ValueError('empty_number_range')
    return NumberDomain(ranges=(NumberRange(low, high, step),))


def import_tiger(raw_path, input_path, localities_path, source: dict) -> dict:
    """Import source ranges by side; localities CSV supplies explicit ZIP/CITY/STATE.

    Mapping is a deliberately separate input: ADDRFEAT does not provide a postal
    city. Ambiguous ZIP mappings are rejected, never resolved by arbitrary choice.
    """
    if not source.get('locality_source'):
        raise ValueError('source metadata must identify locality_source')
    localities = {}
    for row in _csv_rows(localities_path, {'ZIP', 'CITY', 'STATE'}):
        AddressFamily('validate', dict(city=row['CITY'], state=row['STATE'], zip=row['ZIP']), NumberDomain(values=('1',)), source['id'])
        if not row['ZIP'] or not row['CITY'] or not row['STATE']:
            raise ValueError('locality mapping must contain ZIP, CITY and STATE')
        value = dict(city=row['CITY'], state=row['STATE'], zip=row['ZIP'])
        if row['ZIP'] in localities and localities[row['ZIP']] != value:
            raise ValueError('conflicting locality mapping for ZIP ' + row['ZIP'])
        localities[row['ZIP']] = value
    reasons, accepted = Counter(), [0]
    def families():
        for row in _tiger_rows(input_path):
            for side in ('L', 'R'):
                first, last = row.get(side + 'FROMHN', ''), row.get(side + 'TOHN', '')
                if not first or not last or not row.get('FULLNAME'):
                    reasons['missing_number_or_street'] += 1
                    continue
                locality = localities.get(row.get('ZIP' + side, ''))
                if locality is None:
                    reasons['missing_locality_mapping'] += 1
                    continue
                try:
                    numbers = _number_domain(first, last, row.get('PARITY' + side, ''))
                except ValueError as exc:
                    reasons[str(exc)] += 1
                    continue
                if not row.get('TLID'):
                    raise ValueError('TIGER row lacks TLID')
                # Range and side stay together even for the same physical street.
                identity = [row['TLID'], row.get('LINEARID', ''), row.get('ARID' + side, ''),
                            side, first, last, row.get('PARITY' + side, ''), locality['zip']]
                address_id = source['id'] + ':' + hashlib.sha256(encoded(identity).encode('utf-8')).hexdigest()
                components = dict(locality, street_name=row['FULLNAME'])
                plus4 = row.get('PLUS4' + side, '')
                if re.fullmatch('[0-9]{4}', plus4):
                    components['zip4'] = plus4
                try:
                    family = AddressFamily(address_id, components, numbers, source['id'],
                                           f"{row['TLID']}:{row.get('LINEARID', '')}:{row.get('ARID' + side, '')}:{side}")
                except ValueError:
                    reasons['invalid_components'] += 1
                    continue
                accepted[0] += 1
                yield family
    with RawStore(raw_path, writable=True) as raw:
        result = raw.import_families(families(), source)
    return _report(result, accepted[0], reasons)

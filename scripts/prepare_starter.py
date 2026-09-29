"""Prepare a reproducible, conservative starter subset from pinned NAD-derived county files.

Usage: python scripts/prepare_starter.py --output data --limit 5000 county.csv.xz ...
Only address facts are retained. Rows without complete parseable fields are reported.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import lzma
import re
from collections import Counter
from pathlib import Path

from usaddress_dataset.models import AddressFamily, NumberDomain
from usaddress_dataset.store import encoded

UPSTREAM = 'https://github.com/uva-bi-sdad/national_address_database'
REVISION = '1dff543e9688552f3776799dde77ed60b171af06'
SOURCE_ID = 'nad_uva_starter_20260929'


def prepare(paths, output, *, limit=5000):
    if type(limit) is not int or limit < 1:
        raise ValueError('limit must be a positive per-file count')
    groups, files = {}, []
    selected_count = 0
    for path in sorted(map(Path, paths)):
        candidates = {}
        rejected = Counter()
        seen = 0
        with lzma.open(path, 'rt', encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            if 'address' not in (reader.fieldnames or []):
                raise ValueError('NAD-derived file requires address column')
            for line, row in enumerate(reader, 2):
                seen += 1
                address = (row.get('address') or '').strip()
                parts = [v.strip() for v in address.split(',')]
                if len(parts) != 4 or not all(parts):
                    rejected['missing_or_ambiguous_components'] += 1
                    continue
                street_line, city, state, zipcode = parts
                match = re.fullmatch(r'([0-9]+)\s+(.+)', street_line)
                if not match or re.search(r'\b(?:apt|apartment|suite|ste|unit|bldg|floor|fl|p\.?o\.?)\b|#', street_line, re.I):
                    rejected['unsupported_street_or_unit_syntax'] += 1
                    continue
                if not re.fullmatch('[0-9]{5}', zipcode):
                    rejected['invalid_zip'] += 1
                    continue
                number, street = match.groups()
                components = dict(street_name=street.upper(), city=city.upper(), state=state.upper(), zip=zipcode)
                try:
                    f = AddressFamily('validation', components, NumberDomain(values=(number,)), SOURCE_ID)
                except ValueError:
                    rejected['invalid_components'] += 1
                    continue
                key = encoded(dict(f.components))
                identity = encoded([key, number])
                candidates.setdefault(identity, (key, number, line))
        chosen = sorted(candidates, key=lambda s: hashlib.sha256(s.encode('utf-8')).digest())[:limit]
        for identity in chosen:
            key, number, line = candidates[identity]
            group = groups.setdefault(key, {'numbers': set(), 'references': []})
            group['numbers'].add(number)
            group['references'].append(f'{path.name}:{line}')
        selected_count += len(chosen)
        files.append(dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            url=f'{UPSTREAM}/blob/{REVISION}/data/address/{path.name}',
            input_rows=seen, unique_eligible_points=len(candidates), selected_points=len(chosen),
            rejected_rows=sum(rejected.values()), rejected_by_reason=dict(sorted(rejected.items())),
            duplicate_eligible_rows=seen-sum(rejected.values())-len(candidates)))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'starter.addresses.jsonl').open('w', encoding='utf-8', newline='\n') as stream:
        for key in sorted(groups):
            group = groups[key]
            identity = SOURCE_ID + ':' + hashlib.sha256(key.encode('utf-8')).hexdigest()
            family = AddressFamily(identity, json.loads(key), NumberDomain(values=tuple(group['numbers'])), SOURCE_ID,
                ';'.join(sorted(group['references'])))
            stream.write(encoded(family.to_dict()) + '\n')
    source = dict(id=SOURCE_ID, name='NAD-derived county extracts, UVA Biocomplexity Institute SDAD',
        url=UPSTREAM, upstream_revision=REVISION, retrieved_at='2026-09-29',
        license='NAD federal data reuse statement; upstream enrichment has no separate license declaration',
        terms_url='https://www.transportation.gov/mission/open/gis/national-address-database/national-address-database-nad-disclaimer',
        validity='source_observed_not_delivery_validated',
        notes='Third-party NAD-derived extract, including upstream gap filling. No claim of current deliverability, county completeness, national coverage, or demographic representativeness. Source release dates not verified. Missing or malformed fields are rejected; ZIP digits are not invented.')
    (output / 'starter.source.json').write_text(json.dumps(source, indent=2) + '\n', encoding='utf-8')
    manifest = dict(upstream_revision=REVISION, per_file_limit=limit, sampling='lowest SHA256 of normalized point identity per file',
                    selected_point_count=selected_count, address_family_count=len(groups), files=files,
                    output_sha256=hashlib.sha256((output / 'starter.addresses.jsonl').read_bytes()).hexdigest())
    (output / 'starter.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=5000)
    parser.add_argument('inputs', nargs='+', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.inputs, args.output, limit=args.limit), indent=2))

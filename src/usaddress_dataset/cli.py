"""JSON-output command line for creating, indexing and querying local datasets."""
import argparse
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

from .formats import FormatDefinition
from .indexer import FormatIndexer
from .query import FormatQuery
from .sources import import_jsonl, import_points_csv, import_tiger
from .store import RawStore


def _line_range(value):
    try:
        low, high = (int(v) for v in value.split(':'))
        if not 0 <= low <= high:
            raise ValueError()
        return low, high
    except ValueError as exc:
        raise argparse.ArgumentTypeError('expected inclusive MIN:MAX with 0 <= MIN <= MAX') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(prog='usaddress-dataset', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='Create a raw database; refuses to overwrite')
    init.add_argument('--raw', required=True)
    for name in ('import-jsonl', 'import-points', 'import-tiger'):
        sub = commands.add_parser(name)
        sub.add_argument('--raw', required=True)
        sub.add_argument('--input', required=True)
        sub.add_argument('--source', required=True, help='Provenance JSON file')
        if name == 'import-tiger':
            sub.add_argument('--localities', required=True, help='CSV with ZIP,CITY,STATE')
    index = commands.add_parser('index', help='Build or atomically replace a format index')
    index.add_argument('--raw', required=True)
    index.add_argument('--index', required=True)
    index.add_argument('--format', required=True, dest='format_path')
    for name in ('describe', 'metadata', 'count', 'query'):
        sub = commands.add_parser(name)
        sub.add_argument('--raw', required=True)
        sub.add_argument('--index', required=True)
        if name in ('count', 'query'):
            sub.add_argument('--line', action='append', type=_line_range, required=True, help='MIN:MAX for each line in order')
        if name == 'query':
            sub.add_argument('--count', type=int, default=1)
            sub.add_argument('--seed', type=int)
            sub.add_argument('--unique-families', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            with RawStore.create(args.raw) as raw:
                result = raw.snapshot
        elif args.command.startswith('import-'):
            source = json.loads(Path(args.source).read_text(encoding='utf-8'))
            if args.command == 'import-jsonl':
                result = import_jsonl(args.raw, args.input, source)
            elif args.command == 'import-points':
                result = import_points_csv(args.raw, args.input, source)
            else:
                result = import_tiger(args.raw, args.input, args.localities, source)
        elif args.command == 'index':
            result = FormatIndexer.build(args.raw, args.index, FormatDefinition.load(args.format_path))
        else:
            with FormatQuery(args.raw, args.index) as query:
                if args.command == 'query':
                    result = query.query(args.line, count=args.count, seed=args.seed, unique_families=args.unique_families)
                elif args.command == 'count':
                    result = {'eligible_address_count': query.count(args.line)}
                else:
                    result = getattr(query, args.command)()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, zipfile.BadZipFile, LookupError) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}), file=sys.stderr)
        return 2

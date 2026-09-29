"""Build all bundled demo formats and show their metadata and query output."""
import json
import tempfile
from pathlib import Path

from usaddress_dataset.formats import FormatDefinition
from usaddress_dataset.indexer import FormatIndexer
from usaddress_dataset.query import FormatQuery
from usaddress_dataset.sources import import_jsonl
from usaddress_dataset.store import RawStore

repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    raw = root / 'raw.sqlite'
    RawStore.create(raw).close()
    source = json.loads((repo / 'data/demo.source.json').read_text())
    import_jsonl(raw, repo / 'data/demo.addresses.jsonl', source)
    for path in sorted((repo / 'formats').glob('*.json')):
        definition = FormatDefinition.load(path)
        index = root / (definition.id + '.sqlite')
        FormatIndexer.build(raw, index, definition)
        with FormatQuery(raw, index) as query:
            print(json.dumps({'metadata': query.metadata(),
                'query': query.query([(0, 100)] * definition.line_count, count=3, seed=42)}, indent=2))

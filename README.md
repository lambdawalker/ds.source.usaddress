# US Address Dataset

Generate geographically plausible US address strings for synthetic ID-card training, with **whole-range containment constraints on every output line**.

Python 3.10+, SQLite, no third-party runtime dependencies. This repository includes the query library, CLI, source importers, four example formats, and an initial source-backed corpus.

## Starter corpus

The initial corpus contains **10,949 selected address points grouped into 5,160 address families**, drawn from NAD-derived extracts for Autauga County, AL; Pima County, AZ; and New York County, NY. It is a limited starter sample, not a complete national dataset or a representative population sample. Geographic plausibility is the goal; current delivery validity and building existence are not guaranteed.

- [Source-backed families](data/starter.addresses.jsonl)
- [Source attribution](data/starter.source.json)
- [Input hashes, selection counts, and rejected-record report](data/starter.manifest.json)
- [Source acquisition and expansion](docs/source-data.md)

The separate `data/demo.*` files are authored fixtures demonstrating numeric ranges, parity, units, and unusual numbers. Their combinations are **not geographically verified**. Do not mix them into a source-backed training corpus unintentionally.

## Quick start

From a checkout of this repository:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .

python -m usaddress_dataset init --raw work/raw.sqlite
python -m usaddress_dataset import-jsonl --raw work/raw.sqlite --input data/starter.addresses.jsonl --source data/starter.source.json
python -m usaddress_dataset index --raw work/raw.sqlite --index work/two_lines.sqlite --format formats/two_lines.json
python -m usaddress_dataset describe --raw work/raw.sqlite --index work/two_lines.sqlite
python -m usaddress_dataset metadata --raw work/raw.sqlite --index work/two_lines.sqlite
python -m usaddress_dataset query --raw work/raw.sqlite --index work/two_lines.sqlite --line 0:45 --line 0:40 --count 10 --seed 42
```

The installed `usaddress-dataset` command is equivalent to `python -m usaddress_dataset`. Successful commands emit JSON. Runtime data errors and stale indexes return a nonzero exit code with a JSON error on stderr; invalid command-line arguments use argparse usage/error text.

To count eligible families before sampling:

```bash
python -m usaddress_dataset count --raw work/raw.sqlite --index work/two_lines.sqlite --line 15:35 --line 12:30
```

## The matching rule

If an address has indexed range `(15,20)` and the query is `(10,22)`, it matches. A query of `(16,22)` or `(10,19)` does not match, even if one rendering could fit. Every line must match simultaneously:

```text
query_min <= indexed_min AND indexed_max <= query_max
```

There is **no overlap matching or final actual-length filtering**. Bounds are inclusive. Wrong line counts and reversed/negative bounds are errors.

A number domain such as `10–100` reserves **3 characters**, even when the generated number is `42`. It is never padded. Thus actual output may be shorter than the indexed minimum or query minimum, but cannot exceed the accepted reserved maximum. This is intentional: the query constrains reserved lengths. All lengths count NFC-normalized Unicode code points after formatting, including spaces/punctuation but excluding line separators. They are not pixel widths or UTF-8 byte counts.

The format index encloses every permitted presentation variant for the family. For example, `DR` and `DRIVE` can produce an interval; intermediate lengths need not exist. Number generation never changes ZIP/state associations or invents unit identifiers.

## Architecture

| Component | Responsibility |
|---|---|
| Raw SQLite store | Deduplicated street, locality and unit components; address families; compact number domains; provenance |
| Format definition | Versioned JSON line templates, case rules and explicit component replacement tables |
| Format indexer | Builds a separate SQLite file with address IDs and per-line length intervals |
| Format query module | Describes formats, reports metadata, counts eligible families and generates formatted results |

Each format uses its own `FormatDefinition`, `FormatIndexer` build and `FormatQuery` instance. They share implementation code. Adding a JSON format and building its index does not modify the raw database. Indexes contain no copied address components or formatted address text.

Raw dataset UUID/revision and a format fingerprint are stored in every index. Queries reject stale or unrelated raw datasets. Rebuild an affected index after changing raw data; build a new index after editing a format file. Index rebuilds use a temporary file and atomic replacement. Keep readers short-lived and close them before importing or replacing files, especially on Windows.

## Format metadata

`metadata()` returns consolidated bounds and a histogram of **complete range vectors**, counting each address family once:

```json
{
  "address_count": 2,
  "consolidated_ranges": [[12, 30]],
  "range_distribution": [
    {"ranges": [[12, 25]], "address_count": 1},
    {"ranges": [[15, 30]], "address_count": 1}
  ]
}
```

Consolidated bounds are the minimum lower bound and maximum upper bound per line. The consolidated vector is not inserted as an artificial histogram observation. For multiple lines, each histogram key contains all line ranges, preserving their association. Histogram counts sum to the indexed family count. Missing required components are reported as skipped families. An empty index returns `null` consolidated bounds and an empty distribution.

## Python API

```python
from usaddress_dataset.formats import FormatDefinition
from usaddress_dataset.indexer import FormatIndexer
from usaddress_dataset.query import FormatQuery

fmt = FormatDefinition.load("formats/two_lines.json")
FormatIndexer.build("work/raw.sqlite", "work/two_lines.sqlite", fmt)

with FormatQuery("work/raw.sqlite", "work/two_lines.sqlite") as query:
    capabilities = query.describe()
    available = query.metadata()
    count = query.count([(15, 35), (12, 30)])
    batch = query.query([(15, 35), (12, 30)], count=100, seed=42)
    for result in batch["results"]:
        print(result["lines"], result["actual_lengths"], result["reserved_lengths"])
```

Results contain family ID, source reference, raw components, chosen number, presentation variant, actual lengths, reserved lengths, and indexed intervals. Batch metadata records source snapshot, format fingerprint, seed and sampler version.

## Sampling and uniqueness

Every eligible indexed family has a nonzero chance of selection: the default is uniform family sampling **with replacement**, then uniform valid-variant selection, then sampling from its number domain. The sampler considers all eligible IDs; it does not take a database `LIMIT` first. Large number domains do not increase a family's selection probability.

Numeric ranges are stored as inclusive `start`, `end`, `step`. Explicit strings support leading zeros, hyphens, letters and fractions. Multiple ranges are allowed without expansion. Overlapping ranges add weight to shared numbers; support remains complete, but number probabilities are not uniform over the deduplicated union.

Use `--unique-families` or `unique_families=True` to select each family at most once. Requests larger than the eligible population return fewer results with status `insufficient_unique_families`. No matches returns `no_matches`. Constraints are never silently relaxed. Concrete-address/rendered-text uniqueness is not yet implemented. A seed reproduces output with the same raw snapshot, format, sampler and Python version.

## Sources and limitations

- Import canonical JSONL, OpenAddresses-style point CSV, or Census TIGER ADDRFEAT CSV/ZIP.
- Observed point numbers remain explicit sets; their extrema never become invented ranges.
- TIGER imports retain street-side ranges and parity and require a separately attributed ZIP/city/state mapping.
- Import is transactional and repeated identical records are idempotent. Upserts replace encountered family IDs; they do not delete IDs missing from a later file. Use a fresh raw database for complete source snapshot replacement.
- No live address validation, geographic interpolation, postal-city guessing, missing-ZIP guessing, demographic weighting, or name/person records.
- Specialized PO box, rural-route, military and Puerto Rico profiles are not supplied in v0.1.
- The starter source has full street text rather than parsed suffixes. It is preserved in `street_name`; component replacements only operate where a source supplies separated fields. The demo demonstrates those transformations.
- v0.1 uses full format rebuilds and holds eligible IDs in memory for sampling. Streaming/paged sampling and incremental indexing are future scale improvements.
- Base street formats omit units by definition. Use the explicit unit format when unit output is required; it indexes only records with both unit type and identifier.

Split training/evaluation data by family ID before rendering variants to avoid repeated-family leakage. Stronger geographical splits can be prepared using the source county references.

## Formats, tests and reproduction

See [format authoring](docs/formats.md), [source data](docs/source-data.md), and the [agreed specification](docs/superpowers/specs/2026-09-29-address-dataset-design.md).

```bash
python -m unittest discover -s tests -v
python examples/demo.py
```

CI runs the offline suite and demo on Linux and Windows with Python 3.10, 3.12 and 3.13. Source downloads are not required for tests. The repository does not yet declare a software license; source-data terms and attribution are recorded separately.

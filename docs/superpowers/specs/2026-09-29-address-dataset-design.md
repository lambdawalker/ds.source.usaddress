# US address dataset design

## Goal and agreed contract
Produce geographically plausible US addresses for synthetic ID training. A building or postal deliverability is not required. Use Python 3.10+ and SQLite with a standard-library-only runtime. Character counts use NFC-normalized Unicode code points, including punctuation and spaces, excluding line separators. No pixel metrics.

Raw data holds stable address-family IDs, separated components, provenance, and numeric ranges or explicit number strings. Number ranges are not expanded. A numeric range 10–100 reserves 3 characters for every number; generated numbers are not padded. Reserved and actual lengths are returned separately.

For each address and format, store only an address reference and inclusive minimum/maximum reserved length per line. Format variants are finite complete line-template vectors. Index bounds enclose all permitted variants. A query matches only when EVERY query line contains the ENTIRE stored interval: query_min <= stored_min AND stored_max <= query_max. No overlap matching, number-width exceptions, actual-length filtering, truncation, or silent relaxation. Actual strings may fall below query minimum because numbers use their natural widths.

Metadata includes consolidated bounds per line and a histogram of complete per-address range vectors counted by distinct family IDs. An empty index reports null consolidated bounds and an empty histogram. Histogram counts sum to indexed address count, not number-domain size or number of variants.

## Separation
- RawStore: normalized component records (street, locality, unit), family records, number domains, source attribution. SQLite transaction for each import; read-only query access. Dataset UUID plus monotonic revision identify a snapshot.
- FormatDefinition: JSON-compatible ID, version, description, variants, field placeholders and text case. Arbitrary Python execution and attribute access are not permitted in templates. Each variant has the same positive line count. Required fields are derived from placeholders; missing data excludes a family with a reported reason. Blank lines are not produced.
- FormatIndexer: build a separate SQLite file containing a format manifest, source snapshot, one range record per family/line, and grouped range metadata. Rebuild via temporary file and atomic replacement; failure leaves prior index intact. Format creation never writes raw data. Full rebuild in v0.1; incremental updates deferred.
- FormatQuery: describe supported queries, read metadata, count eligible families and sample uniformly among all eligible IDs. Seeded stable ordering. Sample numbers from ranges without enumeration. Default sampling is with replacement; unique-family mode returns fewer results when exhausted with explicit status. Concrete-address uniqueness deferred.

## Source import and coverage
Accept normalized JSONL, explicit address-point CSV, and Census TIGER ADDRFEAT CSV or ZIP/DBF. Preserve ZIP as string. TIGER sides remain separate families, ranges retain parity; descending source endpoints are normalized. Missing ZIP/locality, unsupported parity or nonnumeric intervals are rejected with counts. Caller supplies ZIP/city/state context from a documented source; no county-to-city guesses. Numeric leading-zero endpoints are not collapsed into integers. Equal textual endpoints can be explicit sets. Observed address-point numbers remain explicit sets; do not infer new ranges from their extrema.

Support normal street formats: one line, two lines, three lines, and unit-on-separate-line. PO boxes, rural routes, military and Puerto Rico specialized profiles are future formats, not inferred normal street addresses. README must distinguish demonstrative fixtures from source-backed data and not claim nationwide coverage.

## Correctness
Immutable models validate nonempty domains, inclusive length bounds, template fields and line counts. Range maximum length is the maximum actually generated integer's length. Overlapping ranges may bias a number's probability but never remove support; document this. Raw snapshots are pinned through query/index transactions. Index fingerprints include format definition and indexing algorithm version. Mismatched source UUID/revision is an explicit stale-index error.

## Acceptance
Containment examples (15,20) in (10,22) and (15,20) pass; (16,22) and (10,19) fail. Multi-line constraints intersect. Maximum-width reservation, source units, repeated imports, metadata exactness, deterministic sampling, stale-index refusal, interrupted rebuilding, CLI workflow and missing-source fields receive regression tests.

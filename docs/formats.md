# Format authoring

A format consists of a versioned definition, its separate SQLite index, and a configured query module. The common Python implementation avoids duplicating renderer logic across formats. A standalone JSON definition is sufficient; no Python code generation is needed.

```json
{
  "id": "custom_two_lines",
  "version": 1,
  "description": "Street then locality",
  "case": "upper",
  "variants": [
    {"lines": ["{number} {street}", "{city}, {state} {zip}"]},
    {"lines": ["{number} {street}", "{city} {state} {zip}"]}
  ]
}
```

Each variant is a complete presentation. All variants have the same nonzero number of lines. `case` is `upper` or `source`. Text is NFC normalized. Literal braces are escaped as `{{` and `}}`; plain named placeholders are allowed, but Python attribute access, conversions, width specifiers, and arbitrary code are not.

Supported placeholders:

| Placeholder | Meaning |
|---|---|
| `number` | Sampled number, measured at the maximum rendered width of the family domain |
| `street` | Nonempty prefix/name/suffix/postdirection joined by single spaces |
| `street_prefix`, `street_name`, `street_suffix`, `street_postdirection` | Source-supplied street components |
| `city`, `state`, `zip`, `zip4` | Source-supplied postal context |
| `unit_type`, `unit` | Source-supplied secondary components |

A variant is unavailable when any referenced field is missing. The family is skipped only if no variant is available. A missing `street_name` makes `street` unavailable; a suffix alone is not treated as a street. There is no optional-line collapse or automatic word wrapping.

Explicit per-variant component replacements are supported:

```json
{
  "lines": ["{number} {street}", "{city} {state} {zip}"],
  "replacements": {"street_suffix": {"DR": "DRIVE", "RD": "ROAD"}}
}
```

Replacement lookup is exact against source text, before case conversion. Unmapped values stay unchanged. Use replacements only for semantically equivalent presentations; the engine cannot establish whether arbitrary replacement text is a geographically valid alias. In particular, do not swap ZIPs or cities to make a line fit.

## Indexing and querying

`FormatIndexer.build(raw_path, index_path, definition)` returns metadata. It opens the raw database read-only, derives every available variant's reserved length vector using the same renderer as queries, and stores per-line minima/maxima for the family. Bounds enclose all variants and are deliberately conservative.

`FormatQuery(raw_path, index_path)` is a context manager:

- `describe()` returns the format schema, supported variants, required fields, line count and matching rule.
- `metadata()` returns available bounds, exact vector distribution, family counts, skipped count, format version and raw snapshot.
- `count(line_ranges)` counts families whose full intervals fit all requested ranges.
- `query(line_ranges, count=1, seed=None, unique_families=False)` produces a batch and explicit status.

`FormatDefinition.render(family, variant, number)` is a low-level renderer. The normal query path samples a number from the family's domain first; callers of the low-level method must supply a domain-valid number themselves.

A format's metadata distribution counts distinct family IDs, not concrete number combinations, rows per line or variants. Applying the metadata histogram to a query can estimate eligible counts exactly by summing groups whose complete vectors fit. The query engine independently uses the indexed per-line records.

## Rebuilds and snapshots

Editing a definition file does not mutate an already-built index. Its embedded definition is an immutable build snapshot. Increment the format version and build again. Raw database revisions invalidate every old index, even if a particular address's text did not change; this is a simple conservative v0.1 policy.

Separate files avoid touching raw data when adding formats. All index records can be regenerated from the source snapshot plus the definition. Failed rebuilds leave the old index available. Identical raw/index paths and filesystem aliases are rejected.

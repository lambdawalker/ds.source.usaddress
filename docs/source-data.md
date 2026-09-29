# Source data and provenance

## Included starter

`data/starter.addresses.jsonl` contains compact explicit-number families derived from county extracts in [UVA Biocomplexity Institute SDAD's NAD-derived repository](https://github.com/uva-bi-sdad/national_address_database), pinned to commit `1dff543e9688552f3776799dde77ed60b171af06`.

The upstream repository states that it extracts the [USDOT National Address Database](https://www.transportation.gov/gis/national-address-database) and fills gaps using other sources. This is a third-party derived dataset, not a direct current NAD release. Its README example counts differ from the retrieved files; our manifest reports actual input and selected counts. We have not independently validated every address or established the date of each underlying address observation.

The [USDOT NAD disclaimer](https://www.transportation.gov/mission/open/gis/national-address-database/national-address-database-nad-disclaimer) describes federal NAD reuse and its limitations, including incomplete coverage and mailing-list restrictions. The upstream enrichment repository has no separate license declaration. We preserve attribution and distinguish the NAD statement from upstream enrichment; this project does not relicense upstream data.

Selection is deterministic: up to 5,000 unique complete points per county file, ordered by SHA-256 of the normalized point identity. Then points sharing street/city/state/ZIP components are grouped into explicit number sets. The dataset stores no residents' names, property owners, parcel attributes or coordinates.

| County extract | Selected points |
|---|---:|
| Autauga County, AL (`01001`) | 949 |
| Pima County, AZ (`04019`) | 5,000 |
| New York County, NY (`36061`) | 5,000 |
| San Diego CA, Suffolk MA, Bexar TX, King WA | 0 |

The four zero-result extracts contained no records meeting all current conservative parser requirements. They are recorded in the manifest, not silently repaired. In particular, four-digit ZIPs are rejected; their leading digit is not guessed. This initial sample therefore covers three counties and has 10,949 selected points in 5,160 families. It is not nationally representative.

`starter.manifest.json` records URLs, compressed-file SHA-256 hashes, counts, rejection categories and the final JSONL hash. Each family retains the source file/CSV line references. Source publication dates and delivery status are unknown.

### Reproduce the included data

Obtain the pinned files with a filtered checkout (do not clone all historical data):

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/uva-bi-sdad/national_address_database.git nad-source
# Ensure the pinned commit is available if the upstream default branch has advanced:
git -C nad-source fetch --depth 1 origin 1dff543e9688552f3776799dde77ed60b171af06
mkdir -p downloads
for county in 01001 04019 06073 25025 36061 48029 53033; do
  git -C nad-source show 1dff543e9688552f3776799dde77ed60b171af06:data/address/$county.csv.xz > downloads/$county.csv.xz
done
python scripts/prepare_starter.py --output reproduced --limit 5000 downloads/*.csv.xz
```

Alternatively download each manifest URL through GitHub's Raw download. Compare both input and output checksums with the committed manifest. The script rejects uncertain number/unit syntax rather than attempting a general US address parser. The creation date and source pin in the script describe this starter release; update those constants when preparing another release.

## Canonical JSONL

Each line contains an address family:

```json
{"id":"source:segment:left","source_id":"source","source_record":"segment:left","components":{"street_name":"OAK","street_suffix":"DR","city":"BOSTON","state":"MA","zip":"02108"},"numbers":{"ranges":[{"start":10,"end":100,"step":2}],"values":[]}}
```

This is a schema example, not a verified street/number association. Raw component values and explicit number values are strings. Ranges use nonnegative integers and positive steps. Their endpoints are inclusive, and `end` need not be reachable by the step; maximum width uses the last reachable number. Multiple ranges preserve gaps. Do not turn a set of observed points into a continuous range unless the source supports that range.

Each import supplies source metadata with string fields `id`, `name`, `url`, `license`, `retrieved_at`; additional provenance fields are retained. Family IDs must be unique across sources. The same source may upsert an existing ID. Imports do not reconcile deleted source records: use a fresh raw database for full snapshot replacement.

## Address-point CSV

```bash
python -m usaddress_dataset import-points --raw work/raw.sqlite --input points.csv --source points.source.json
```

Required headers follow the OpenAddresses output convention: `NUMBER,STREET,CITY,REGION,POSTCODE`. Optional: `UNIT,UNIT_TYPE`. Read ZIPs as text before writing CSV. ZIP+4 is split into ZIP and extension. Unsupported or missing required components are counted and skipped. No apartment/suite type is guessed when `UNIT_TYPE` is missing. Groups share exact normalized components and retain explicit number sets; there is no expansion of gaps. A grouped source reference is a stable component hash; preserve the source file and its hash to trace individual original rows.

## Census TIGER address ranges

[2025 ADDRFEAT county ZIP files](https://www2.census.gov/geo/tiger/TIGER2025/ADDRFEAT/) and [technical documentation](https://www2.census.gov/geo/pdfs/maps-data/data/tiger/tgrshp2025/TGRSHP2025_TechDoc.pdf) describe source ranges and side-specific ZIP associations. These are potential address ranges, not evidence that a building exists at every number. See [Census Geocoder documentation](https://www.census.gov/programs-surveys/geography/technical-documentation/complete-technical-documentation/census-geocoder.html).

```bash
python -m usaddress_dataset import-tiger --raw work/raw.sqlite --input tl_2025_11001_addrfeat.zip --localities localities.csv --source tiger.source.json
```

The importer reads the DBF directly from the ZIP with the standard library; it does not extract geometry or require GDAL. CSV exports of ADDRFEAT are also supported. Character encoding comes from `.cpg` when present, otherwise UTF-8.

Supply an explicitly sourced postal-context mapping:

```csv
ZIP,CITY,STATE
20001,WASHINGTON,DC
```

`tiger.source.json` must include `locality_source` in addition to normal provenance fields. Use an authoritative or otherwise documented postal-city mapping; a county name or Census place is not automatically a postal city. Ambiguous mappings for a ZIP are rejected. The v0.1 mapping supports one selected city/state per ZIP and does not model postal aliases. Every source range is kept linked to its side and ZIP; it is never joined across unrelated segments or states.

Left/right ranges become separate families. Reversed numeric endpoints are normalized; parity `E`, `O`, `B` controls the allowed numbers. Unsupported parity, missing locality mappings, missing endpoints and nonnumeric intervals are counted and skipped. Equal explicit endpoints can be retained as strings. Nonnumeric intervals and numbers with leading zeros are not guessed; use explicit values through JSONL for those domains.

Direct Census download was unavailable from the development environment. The adapter was exercised against local CSV and ZIP/DBF fixtures; the bundled starter was obtained from the pinned NAD-derived source instead.

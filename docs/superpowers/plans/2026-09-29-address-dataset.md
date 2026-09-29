# Address Dataset Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a queryable Python US-address dataset toolkit to the user-selected GitHub repository.
**Architecture:** Separate raw SQLite data from one independently rebuildable SQLite index per declarative format. Preserve compact number domains and implement whole-interval containment.
**Tech Stack:** Python 3.10+, sqlite3, unittest, argparse, standard library.
**Spec:** docs/superpowers/specs/2026-09-29-address-dataset-design.md

## Global Constraints
- Runtime has no third-party dependencies.
- Query bounds contain every indexed line interval inclusively.
- Number width is reserved at domain maximum; output is not padded.
- Raw data is not duplicated in format indexes.
- Source coverage and source limitations must be explicit.

## Review Focus
- Source state/ZIP/number relationships must not be accidentally recombined.
- Shorter actual numbers must not cause containment semantics to change.
- Multiple lines and variants must count one family once.
- Failed imports/builds must not leave partial published data.
- Fresh databases must not validate against indexes of unrelated databases.

## Task 1: Models and raw database
Files: src/usaddress_dataset/models.py, store.py, tests/test_core.py.
Interfaces: NumberRange, NumberDomain, AddressFamily; RawStore.create/read/import_families/get/families/snapshot.
- [x] Write number validation, max-width, string ZIP preservation, deduplicated component storage, idempotent import and rollback tests; run unittest and observe missing feature failures.
- [x] Implement immutable models and transactional normalized store.
- [x] Run full unittest suite, then commit.

## Task 2: Formats, indexing and queries
Files: formats.py, indexer.py, query.py, tests/test_formats.py, tests/test_queries.py, formats/*.json.
Interfaces: FormatDefinition.from_dict/describe/variants_for; FormatIndexer.build; FormatQuery.metadata/count/query.
- [x] Write containment, correlated multiline histogram, fixed max number width, zero-match, seeded sampling, unique-family, raw independence, stale detection, atomic rebuild tests; verify failures.
- [x] Implement shared rendering/measurement logic, separate index, metadata and random sampling over complete eligible population.
- [x] Run full suite, then commit.

## Task 3: Ingestion and command line
Files: sources.py, cli.py, __main__.py, tests/test_sources.py, tests/test_cli.py, examples/, data/.
Interfaces: import_jsonl, import_points_csv, import_tiger; CLI init/import/index/describe/metadata/count/query.
- [x] Write source-side/parity, leading-zero ZIP, missing mapping, explicit set, DBF truncation and subprocess workflow tests; observe failures.
- [x] Implement source adapters, JSON reports, CLI, sample fixtures and reproducible bootstrap instructions.
- [x] Run full suite and CLI examples, then commit.

## Task 4: Delivery
Files: README.md, docs/source-data.md, docs/formats.md, pyproject.toml, .github/workflows/tests.yml.
- [x] Document exact contract, source limitations and extension API; package installation and examples.
- [x] Run full suite, compile check, installed CLI and representative batch generation.
- [x] Review whole branch and fix consequential findings.
- [ ] Push to the requested repository and verify remote head.

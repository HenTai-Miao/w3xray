# Testing and Acceptance

## Automated gates

Task 10 focused behavior and integration gate:

```bash
uv run python -m pytest -q \
  tests/test_integrity_snapshot.py \
  tests/test_integrity_snapshot_races.py \
  tests/test_integrity_cli.py \
  tests/test_integrity_output_safety.py \
  tests/test_integrity_output_identity_races.py \
  tests/test_integrity_physical_aliases.py \
  tests/test_integrity_platform_boundaries.py \
  tests/test_integrity_utf8_boundaries.py \
  tests/test_description_cache_retained_capture.py \
  tests/test_description_cache_retained_integrity.py \
  tests/test_description_cache_retained_integrity_bounds.py \
  tests/test_description_cache_retained_integrity_stability.py \
  tests/test_description_cache_retained_report_relations.py \
  tests/test_integrity_cli_retained_cache.py \
  tests/test_safe_output.py \
  tests/test_safe_output_races.py \
  tests/test_safe_output_publication_atomicity.py \
  tests/test_safe_output_publication_cleanup_races.py \
  tests/test_durable_io.py \
  tests/test_release_metadata.py \
  tests/test_posix_package_assets.py \
  tests/test_quality_gate.py \
  tests/test_batch_dependencies.py \
  tests/test_batch_e2e.py \
  tests/test_acceptance_runner.py
```

Verified on 2026-07-19 after wave-three independent-review closure, including
physical-alias, UTF-8-boundary, cleanup/restoration race, and continuous-name
publication regressions: 186 passed and 4 platform fixtures skipped.

Repository gate:

```bash
uv run w3xray-test
```

Verified on 2026-07-19 after wave-three independent-review closure: 2,108
passed, 15 skipped, and 1 subtest passed.

Maintained strict-path gate:

```bash
uv run w3xray-quality
```

The quality command runs Ruff lint, Ruff format check, and basedpyright `--level error` over one sorted, duplicate-free maintained path tuple. New paths must not be added to `tool.basedpyright.ignore`.

Verified on 2026-07-19 after wave-three independent-review closure: Ruff check
passed, 263 maintained files were formatted, and basedpyright reported 0
errors, 0 warnings, and 0 notes. The changed-file no-excuse audit reported no
violations in 24 Python files.

Changed-file diagnostics when narrowing a failure:

```bash
uv run --with ruff ruff check <paths>
uv run --with ruff ruff format --check <paths>
uv run --with basedpyright basedpyright --level error <paths>
```

## Task 10 fixture boundary

- All snapshot, retained-cache, CLI, migration, and batch integration tests use pytest `tmp_path` or system-temporary roots.
- Do not open or mutate `/Users/zhongerbing/Desktop/Maps`, `map-extract-output`, `map-extract-output-v2`, `map-extract-output-v4`, or `trusted-icon-cache-classic` during Task 10.
- Do not create acceptance outputs inside the repository. Check `git status --short` for tracked/generated output roots before commit.

## Required acceptance invariants

1. Snapshot formatting/parsing is canonical; roots are unique/nonoverlapping; no symlink or special entry is followed; content and nanosecond mtime changes compare as differences.
2. Retained-cache bounds are exact: 64 MiB/file, 512 MiB/tree, 100,000 files, 125,000 entries, and accepted depth 64; the first exceeded unit reports `oversized` without a partial digest.
3. Retained artifacts receive two complete tree intervals in two whole-set rounds. File/child mutation is `unstable`; active-root, top-level retained identity, or relevant sibling namespace replacement is a code-2 command boundary with no report.
4. A `previous` directory validates only the five already captured owned payloads. Pathname cache loaders are never called; retained failed/recovery objects are never description sources.
5. Codes 0/1 write canonical retained reports; 0 permits only valid-cache/ordinary partial evidence with no transient/malformed rows, 1 represents artifact violations, and 2 represents request/binding/namespace/report-write boundaries.
6. Every map publication binds `图标未解析.tsv`, all text/relation evidence counters, and exact report bytes in its content manifest.
7. The four global evidence reports reconcile only verified map snapshots. Candidate rows remain unadopted; failed/cancelled terminal inputs appear on the three-axis report without inventing map evidence.
8. Full regression, quality, lockfile version, whitespace, AGENTS line count, and generated-output checks must pass before the Task 10 commit.
9. Base snapshots traverse only through held directory descriptors and reject ancestor replacement or any `(dev, ino, size, mtime_ns, ctime_ns, mode)` change around hashing.
10. Snapshot and retained-report outputs reject symlink components and reserved cache-publication names, and publication rollback leaves no report when output or relevant retained namespaces change.
11. Snapshot roots and output ancestry reject physical case/normalization aliases while all protected descriptors remain held; rejected output paths create no stage.
12. Existing-output publication keeps the public name continuously present, including crash-state sync seams; cleanup/restoration atomically claim then prove caller-owned identities, and recovery paths are reported only after re-proof.
13. Every external label/path boundary rejects non-strict UTF-8 before binding or serialization, and exact 5/5 invalid-previous inventory mismatches require the canonical missing owned problem path.

## Opt-in real-data acceptance (Task 11 only)

Task 11 snapshots the four read-only map/historical roots before migration, writes only to the new external cache/output/evidence paths, then verifies the same snapshot after processing. It must prove first-run `processed`, immediate-run `reused`, manifest/report/count reconciliation, no transient publication names, retained-cache evidence, and exact source/input content+metadata equality.

Historical schema-4 measurements from 2026-07-15 remain evidence only: 39/39 processed then reused, 700,979 text rows, 13,442 relation rows, and 79,078 logical icon rows. Do not relabel those counts as schema-5 results.

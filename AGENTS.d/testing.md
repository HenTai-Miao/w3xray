# Testing and Acceptance

## Automated gates

Focused batch feature suite:

```bash
uv run python -m pytest -q \
  tests/test_classic_mpq_source.py \
  tests/test_batch_descriptions.py \
  tests/test_icon_resources.py \
  tests/test_batch_icon_export.py \
  tests/test_batch_reports.py \
  tests/test_batch_runner.py \
  tests/test_batch_cli.py \
  tests/test_batch_e2e.py \
  tests/test_batch_map_processing.py \
  tests/test_batch_map_icons.py \
  tests/test_batch_extraction_gaps.py
```

Verified result on 2026-07-14: 67 passed.

Repository test gate:

```bash
uv run w3xray-test
```

Verified result on 2026-07-14: 1269 passed, 4 skipped, and 1 subtest passed.

Changed-file static gates:

```bash
uv run --with ruff ruff check PATHS...
uv run --with ruff ruff format --check PATHS...
uv run --with basedpyright basedpyright --level error PATHS...
```

The full-repository Ruff and basedpyright commands also expose historical baseline findings outside the batch feature. Do not silently broaden a batch change to repair that baseline; require all batch-changed Python paths to pass their focused gates.

The 29 Python paths changed by the batch branch pass Ruff, Ruff format, basedpyright, and the programming no-excuse audit. The unchanged full-repository baseline remains 59 Ruff errors, 340 files requiring Ruff formatting, and 1,645 basedpyright errors.

## Real-map acceptance

1. Capture every source path, size, mtime-ns, and SHA-256 with `w3xtool.batch_runner.fingerprint_source` before processing. If sources were copied to a new root, match persisted results by SHA-256 and size and report path/mtime changes separately.
2. Copy the smallest and largest maps to private temporary directories. Final symlinks are intentionally rejected by the no-follow regular-file boundary.
3. Run the batch command against the smallest copy, largest copy, then the full source directory.
4. Require one summary row and one owned published directory per source, with all five map reports present.
5. Recompute source fingerprints and require an exact byte-for-byte match with the before manifest.
6. Cross-check every index row against its original SHA-256 and PNG magic, validate anonymous names against `block_[0-9]{6}_[0-9a-f]{8}.blp`, and parse all TSV files with a standard tab-delimited CSV reader.

Verified real output on 2026-07-14:

- 39/39 published, with 1 complete, 38 partial, 0 restricted, and 0 failed results.
- 79,078 logical icon rows, 78,916 unique original paths, and 78,916 unique PNG paths.
- 139,440 description rows; map-level state counts reconcile exactly and no malformed TSV rows remain.
- Every ownership marker and required report matched its summary row.
- No temporary publication directories remained.
- All 39 desktop sources match the persisted SHA-256 and size set. The 38 relocated copies intentionally differ in path and `mtime_ns`; the new map matches all persisted fields exactly.
- Every unique original passed SHA-256 verification, every PNG passed its magic-byte check, and the index path sets exactly matched the physical file sets, including path case.

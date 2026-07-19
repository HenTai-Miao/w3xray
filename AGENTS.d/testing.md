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
  tests/test_integrity_output_naming_probe.py \
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
  tests/test_safe_output_cleanup_recovery.py \
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

Verified on 2026-07-19 after wave-five independent-review closure, including
filesystem-aware alias behavior, probe ownership, typed cleanup/restoration
states, exchange-reversal races, and continuous-name publication regressions:
196 passed and 7 platform/capability fixtures skipped.

Repository gate:

```bash
uv run w3xray-test
```

On Windows, `tests/conftest.py` marks only suites that require POSIX dir-fd,
no-follow traversal, or atomic exchange as capability skips. Core batch,
trusted-cache reading, GUI, package construction, and packaged acceptance stay
mandatory; `tests/test_windows_acceptance_assets.py` guards that boundary.

Verified on 2026-07-19 after wave-five independent-review closure: 2,118
passed, 18 skipped, and 1 subtest passed.

Maintained strict-path gate:

```bash
uv run w3xray-quality
```

The quality command runs Ruff lint, Ruff format check, and basedpyright `--level error` over one sorted, duplicate-free maintained path tuple. New paths must not be added to `tool.basedpyright.ignore`.

Verified on 2026-07-19 after immutable integrity-report history: `w3xray-test`
reported 2131 passed, 18 skipped, and 1 subtest passed. Ruff check and format
covered 287 maintained files, and basedpyright reported 0 errors, 0 warnings,
and 0 notes. The changed-file no-excuse audit passed.

Verified on 2026-07-19 after the revision-6 three-defect closure: the focused
regression suite reported 153 passed; `w3xray-test` reported 2166 passed,
18 skipped, and 1 subtest passed. Ruff check and format covered 313 maintained
files, basedpyright reported 0 errors, 0 warnings, and 0 notes, and the
changed-file no-excuse audit reported no violations in 74 files.

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
10. Snapshot and retained-report outputs reject symlink components, reserved cache-publication names, and the integrity-history root or its proved filesystem aliases. A successful overwrite keeps the new report public and moves the exact old inode into a two-file manifested history generation; later overwrites append without changing or deleting earlier generations. Pre-exchange failures clean only the proved-owned new stage; uncertain exchange/history races fail closed and retain every provable current/old/concurrent object rather than deleting evidence.
11. Snapshot roots and output ancestry reject real physical case/normalization aliases while all protected descriptors remain held, but accept distinct spellings on filesystems that preserve them. Exact reserved prefixes remain forbidden; absent alias spellings require an exact-parent isolated capability probe.
12. Existing-output publication keeps the public name continuously present, including crash-state sync seams. Stage, backup, and cleanup-retained states are explicit; every exchange is proved in both directions, replacements are preserved, and nested recovery paths require outer-directory plus inner-leaf re-proof.
13. Every external label/path boundary rejects non-strict UTF-8 before binding or serialization, and exact 5/5 invalid-previous inventory mismatches require the canonical missing owned problem path.

## Opt-in real-data acceptance (Task 11 only)

Task 11 snapshots the four read-only map/historical roots before migration, writes only to the new external cache/output/evidence paths, then verifies the same snapshot after processing. It must prove first-run `processed`, immediate-run `reused`, manifest/report/count reconciliation, no transient publication names, retained-cache evidence, and exact source/input content+metadata equality.

The 2026-07-19 revision-6 three-defect acceptance processed and published 39/39
maps with zero failures, cancellations, or timeouts, then strictly reused 39/39
from `map-extract-output-v6-three-fix-20260719T133434Z`. All 82,880 located icon
payloads wrote both original and PNG with zero physical failures. The sole
zero-object map persisted one source-coverage gap and remained `部分完成`; the
slowest map completed in 127,561 ms. The input integrity snapshot verified
unchanged after both runs, and no stage/backup/transaction/retirement residue
remained.

Historical schema-4 measurements from 2026-07-15 remain evidence only: 39/39 processed then reused, 700,979 text rows, 13,442 relation rows, and 79,078 logical icon rows. Do not relabel those counts as schema-6 results.

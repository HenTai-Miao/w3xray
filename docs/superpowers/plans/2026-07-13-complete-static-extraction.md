# Complete Static Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add auditable per-block extraction results, source-bound compatibility bundles, deterministic batch extraction, shared CLI/GUI configuration, and release-grade cross-platform packaging.

**Architecture:** Keep `MPQArchive` as the only container parser. A verified supplemental-evidence layer wraps it with author plaintext, compatibility plaintext, and explicit final MPQ keys; a separate immutable ledger inventories every live block and supplies all JSON/TSV/text status views. Single-map, current-map, GUI, compatibility-builder, and batch entry points all build the same `MapLoadContext` and consume the same ledger.

**Tech Stack:** Python 3.14, uv, pytest, frozen dataclasses and `StrEnum`, existing pure-Python MPQ reader, CustomTkinter, GitHub Actions/PyInstaller.

---

### Task 1: Immutable extraction evidence and status aggregation

**Files:**
- Create: `w3xtool/extraction_ledger.py`
- Create: `w3xtool/extraction_ledger_format.py`
- Test: `tests/test_extraction_ledger.py`

- [ ] **Step 1: Write failing model and aggregation tests**

```python
def test_all_decoded_entries_are_complete() -> None:
    ledger = build_ledger((_entry(BlockState.DECODED),))
    assert ledger.status is ExtractionStatus.COMPLETE

def test_only_unresolved_encrypted_entries_are_encrypted_blocked() -> None:
    ledger = build_ledger((_entry(BlockState.ENCRYPTED_BLOCKED, encrypted=True),))
    assert ledger.status is ExtractionStatus.ENCRYPTED_BLOCKED

def test_damage_precedes_partial_and_encryption() -> None:
    ledger = build_ledger((_entry(BlockState.RAW_ONLY), _entry(BlockState.DAMAGED)))
    assert ledger.status is ExtractionStatus.DAMAGED
```

- [ ] **Step 2: Run `uv run python -m pytest -q tests/test_extraction_ledger.py` and verify import failure**
- [ ] **Step 3: Implement frozen `ExtractionEntry`, `ExtractionLedger`, `BlockState`, `BlockSource`, and `ExtractionStatus`; reject internally inconsistent state/source/hash combinations in constructors**
- [ ] **Step 4: Add deterministic schema-v1 JSON and TSV formatters with control-character cleanup, stable entry ordering, counts, first error, and source SHA-256**
- [ ] **Step 5: Re-run the focused tests and commit the green slice**

### Task 2: Compatibility-bundle parser and normalized supplemental evidence

**Files:**
- Create: `w3xtool/supplemental_evidence.py`
- Create: `w3xtool/compat_bundle.py`
- Test: `tests/test_compat_bundle.py`
- Test: `tests/test_supplemental_conflicts.py`

- [ ] **Step 1: Write failing tests for the v1 header, source hash binding, `name`, `file`, and `mpq_key` rows**

```python
def test_compat_bundle_accepts_bound_name_file_and_key(tmp_path: Path) -> None:
    bundle = load_compat_bundle(_bundle(tmp_path), _source(tmp_path))
    assert bundle.names == ("war3map.j",)
    assert bundle.files[0].sha256 == hashlib.sha256(b"script").hexdigest()
    assert bundle.keys[0].block_index == 7
```

- [ ] **Step 2: Verify RED for missing modules**
- [ ] **Step 3: Implement bounded manifest parsing: 2 MiB manifest, 100,000 names, 10,000 files, 262,144 keys, 256 MiB per file, 512 MiB total**
- [ ] **Step 4: Reuse `bounded_file` and `safe_relative_path`; reject symlinks, non-regular files, traversal, empty components, case-folded duplicates, malformed hashes/keys, and post-validation replacement**
- [ ] **Step 5: Normalize author and compatibility inputs to frozen supplemental name/plaintext/key records and reject cross-source path or block conflicts before opening the map**
- [ ] **Step 6: Run both focused test files and commit**

### Task 3: Explicit MPQ-key reads and supplemented archive wrapper

**Files:**
- Modify: `w3xtool/mpq.py`
- Create: `w3xtool/supplemented_archive.py`
- Create: `w3xtool/supplemented_source.py`
- Test: `tests/test_mpq_explicit_keys.py`
- Test: `tests/test_supplemented_archive.py`

- [ ] **Step 1: Write failing tests for single-unit, sector, compressed, and `FIX_KEY` blocks read with a final 32-bit key; an incorrect key must fail the declared SHA-256 check**
- [ ] **Step 2: Verify RED because no public explicit-key block method exists**
- [ ] **Step 3: Add `MPQArchive.read_block_with_key(block_index, key)` that passes the final key directly to `read_mpq_block` and never reapplies `FIX_KEY`**
- [ ] **Step 4: Implement `SupplementedArchive`: named archive read first unless verified plaintext explicitly overrides; anonymous recovery second; compatibility key third; raw payload last**
- [ ] **Step 5: Expose source metadata for each name/block, keep overlay warnings, and make `SupplementedPathArchiveSource.open()` rebuild and revalidate the wrapper on every use**
- [ ] **Step 6: Run focused tests and existing MPQ/author-bundle tests; commit**

### Task 4: Archive ledger inventory and map lifecycle integration

**Files:**
- Create: `w3xtool/archive_inventory.py`
- Create: `w3xtool/map_archive_open.py`
- Modify: `w3xtool/load_context.py`
- Modify: `w3xtool/map_data.py`
- Modify: `w3xtool/map_loader.py`
- Test: `tests/test_archive_inventory.py`
- Test: `tests/test_author_plaintext_bundle.py`
- Test: `tests/test_map_data_compat.py`

- [ ] **Step 1: Write failing tests proving one ledger row per live block plus block-null supplemental files, stable Unknown paths, raw SHA-256, source attribution, and all four aggregate statuses**
- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Inventory named blocks, recovered anonymous blocks, compatibility-key blocks, supplemental plaintext, raw encrypted blocks, and structural failures under the existing aggregate byte/decompression budgets**
- [ ] **Step 4: Add `compat_bundle_path` to `MapLoadContext`, `build_map_load_context`, and `MapData.extraction_ledger`; preserve all existing positional fields by appending new fields**
- [ ] **Step 5: Extract root archive construction from the near-limit `map_loader.py` into `map_archive_open.py`; retain `SupplementedPathArchiveSource` on root maps and never inherit a parent bundle into campaign children**
- [ ] **Step 6: Compute the ledger while the verified archive is open, keep existing author bundle behavior, and run focused plus map-loading regression tests; commit**

### Task 5: Compatibility bundle builder and CLI

**Files:**
- Create: `w3xtool/compat_bundle_builder.py`
- Create: `w3xtool/compat_cli.py`
- Modify: `main.py`
- Test: `tests/test_compat_bundle_builder.py`
- Test: `tests/test_compat_cli.py`

- [ ] **Step 1: Write failing tests for bounded directory scanning, deterministic manifest order, optional listfile names, verified keyfile rows, unsafe/symlink rejection, empty-output requirement, and staging cleanup**
- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement `build_compat_bundle(source, export_root, output, listfile, keyfile)` with max depth/file/byte budgets and source identity checks before and after scanning**
- [ ] **Step 4: Validate every keyfile row by decoding its source block and matching the declared plaintext SHA-256 before it enters the output manifest**
- [ ] **Step 5: Stage beside the final output and atomically rename only a complete regular-file tree**
- [ ] **Step 6: Add `main.py compat build ...`; return 0 success and 2 for stable boundary errors; run tests and commit**

### Task 6: Shared ledger reports and single-map/current-map/GUI options

**Files:**
- Create: `w3xtool/knowledge_extraction_exports.py`
- Modify: `w3xtool/knowledge_pack_contents.py`
- Modify: `w3xtool/knowledge_manifest.py`
- Modify: `w3xtool/cli_options.py`
- Modify: `w3xtool/current_map_cli.py`
- Modify: `w3xtool/gui_loader.py`
- Modify: `w3xtool/gui_loader_runner.py`
- Modify: `w3xtool/gui_external_data.py`
- Modify: `w3xtool/gui_lifecycle.py`
- Modify: `w3xtool/gui_topbar.py`
- Modify: `w3xtool/gui.py`
- Test: `tests/test_extraction_ledger_reports.py`
- Test: `tests/test_cli_options.py`
- Test: `tests/test_current_map_cli.py`
- Test: `tests/test_gui_loader.py`
- Test: `tests/test_gui_compat_bundle.py`

- [ ] **Step 1: Write failing tests for `提取结果.json`, `提取结果.tsv`, ledger-derived `提取完整性.txt`, and manifest entries**
- [ ] **Step 2: Write failing parser/forwarding tests for `--compat-bundle` on `cli` and `current`, then GUI select/clear/persist/reload tests**
- [ ] **Step 3: Verify RED for each focused group**
- [ ] **Step 4: Write all three report formats from the same immutable ledger and keep existing Unknown/UnknownRaw exports aligned to ledger paths**
- [ ] **Step 5: Thread `compat_bundle_path` through CLI, current snapshot delegation, GUI loaders, saved config, and data-tools menu; refresh status using the shared aggregate status**
- [ ] **Step 6: Run focused tests and commit**

### Task 7: Deterministic batch scanner, publisher, reports, and CLI

**Files:**
- Create: `w3xtool/batch_models.py`
- Create: `w3xtool/batch_scan.py`
- Create: `w3xtool/batch_runner.py`
- Create: `w3xtool/batch_reports.py`
- Create: `w3xtool/batch_cli.py`
- Modify: `main.py`
- Test: `tests/test_batch_scan.py`
- Test: `tests/test_batch_runner.py`
- Test: `tests/test_batch_cli.py`

- [ ] **Step 1: Write failing scanner tests for extensions, normalized ordering, depth 5, 10,000-map cap, regular files only, and symlink refusal**
- [ ] **Step 2: Write failing runner tests for SHA-256 identity before/after, compatibility-root hash index and duplicate rejection, unique `<safe-name>-<sha[:12]>` output, staging cleanup, and serial processing**
- [ ] **Step 3: Write failing JSON/TSV and exit-code tests: all complete 0, any map status 1, batch-level safety/argument failure 2**
- [ ] **Step 4: Verify RED, then implement the smallest scanner, runner, and report models needed to pass**
- [ ] **Step 5: Add `main.py batch <root> --output ...`; use the same load context and knowledge-pack publication path as single-map extraction**
- [ ] **Step 6: Run focused tests, a fixture-directory batch E2E, and commit**

### Task 8: Regression, quality, package acceptance, and version metadata

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.github/workflows/windows-package.yml`
- Modify: `.github/workflows/posix-package.yml`
- Modify: `README.md`
- Test: `tests/test_acceptance_runner.py`
- Test: `tests/test_release_metadata.py`
- Test: `tests/test_windows_acceptance_assets.py`
- Test: `tests/test_posix_package_assets.py`

- [ ] **Step 1: Add packaged acceptance assertions for `batch --help`, `compat build --help`, a fixture batch, and generated extraction result reports**
- [ ] **Step 2: Verify acceptance tests fail before workflow/code updates**
- [ ] **Step 3: Bump the feature release to `0.2.0`, update the lockfile, CLI documentation, and workflow acceptance commands**
- [ ] **Step 4: Run focused release tests, then `uv run w3xray-test`**
- [ ] **Step 5: Run `uv run --with ruff ruff check` and `ruff format --check` on changed Python, `uv run --with basedpyright basedpyright --level error` on changed Python, `compileall`, no-excuse checks, and `git diff --check`**
- [ ] **Step 6: Build the local distributable and run source/packaged fixture acceptance without executing historical binaries, DLLs, or map payloads**

### Task 9: Commit, push, GitHub package, and publish

**Files:**
- No source changes expected after verification

- [ ] **Step 1: Review the final diff for unrelated dirty work and verify the source-map fixture hashes are unchanged**
- [ ] **Step 2: Commit the complete implementation with a scoped feature message**
- [ ] **Step 3: Fast-forward local `main`, push `main`, and confirm the Windows package workflow starts at the exact commit SHA**
- [ ] **Step 4: Dispatch macOS/Linux packaging with `source_ref=main`; wait for every matrix job to succeed**
- [ ] **Step 5: Download and inspect artifact names and acceptance JSON, create tag/release `v0.2.0`, and upload Windows/macOS/Linux assets plus acceptance evidence**
- [ ] **Step 6: Verify the GitHub release URL, tag SHA, asset list, and clean local worktree**

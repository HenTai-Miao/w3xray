# Testing and Acceptance

## Automated gates

Focused schema-4 text/relation/icon suite:

```bash
uv run python -m pytest -q \
  tests/test_object_pipeline.py \
  tests/test_object_candidate_merge.py \
  tests/test_object_pipeline_priority.py \
  tests/test_object_candidate_collection.py \
  tests/test_object_text_pipeline.py \
  tests/test_object_text_roles.py \
  tests/test_object_text_sources.py \
  tests/test_object_text_index.py \
  tests/test_client_object_data.py \
  tests/test_item_relation_models.py \
  tests/test_item_relations.py \
  tests/test_item_relation_scripts.py \
  tests/test_item_relation_exports.py \
  tests/test_item_relation_resilience.py \
  tests/test_component_parse_diagnostics.py \
  tests/test_map_relation_loading.py \
  tests/test_campaign_shared_object_identity.py \
  tests/test_gui_item_relations.py \
  tests/test_gui_object_presentation.py \
  tests/test_gui_layout.py \
  tests/test_batch_dependencies.py \
  tests/test_batch_state_reports.py \
  tests/test_batch_description_cache.py \
  tests/test_batch_map_retirement.py \
  tests/test_batch_map_retirement_safety.py \
  tests/test_batch_runtime_runner.py \
  tests/test_batch_resume_runner.py \
  tests/test_batch_global_publication.py \
  tests/test_batch_reports.py \
  tests/test_description_cache.py \
  tests/test_windows_acceptance_assets.py \
  tests/test_windows_real_install_workflow.py \
  tests/test_posix_package_assets.py \
  tests/test_release_metadata.py \
  tests/test_quality_gate.py
```

Verified result on 2026-07-15: 241 passed.

Repository test gate:

```bash
uv run w3xray-test
```

Verified result on 2026-07-15: 1,542 passed, 11 skipped, and 1 subtest passed.

Maintained high-availability quality gate:

```bash
uv run w3xray-quality
```

Verified result on 2026-07-15: Ruff check passed, all 150 maintained paths were formatted, and basedpyright reported 0 errors, 0 warnings, and 0 notes. The no-excuse checker reported no violations in 76 changed Python files.

GUI worker regression after Tk-main-thread marshalling: 58 passed. The exact object-filter/reference-ID scenarios passed 12 tests with no `main thread is not in main loop` exception or thread-exception warning.

Pure-LOC audit of the 150 maintained Python paths: 0 files exceeded 250 code lines. Twenty-eight files are in the 200–250 warning band (`test_batch_cli`, `test_batch_runner`, `test_external_listfile_gui`, `test_gui_current_map_lifecycle`, `test_object_candidate_merge`, `test_object_text_index`, `test_object_text_pipeline`, `test_real_map_item_relation_acceptance`, `test_windows_acceptance_assets`, `acceptance_batch`, `acceptance_runner`, `batch_global_publication`, `batch_manifest_io`, `batch_map_attempt`, `batch_map_publication`, `batch_publication_record`, `batch_retirement_quarantine`, `batch_state_parser`, `gui_casc_browser`, `gui_item_relation_layout`, `gui_source_browser`, `item_relation_models`, `map_loader`, `object_materialization`, `object_text_index`, `quality_gate`, `safe_output`, and `safe_output_publication`); split their owning responsibility before adding substantial logic.

Changed-file static gates:

```bash
uv run --with ruff ruff check PATHS...
uv run --with ruff ruff format --check PATHS...
uv run --with basedpyright basedpyright --level error PATHS...
```

The full-repository Ruff and basedpyright commands may expose historical findings outside the maintained high-availability path set. Do not silently broaden a batch change to repair that baseline; require all batch-changed Python paths to pass `w3xray-quality`.

Run static gates on the reviewed task path list, not every unrelated dirty-worktree path. Preserve any user changes and do not broaden a feature to rewrite paths with independent Ruff/type/no-excuse findings. New task modules and tests must still pass all four focused gates.

## Real-map acceptance

High-availability source/packaged acceptance command:

```bash
uv run main.py acceptance \
  --map tests/fixtures/maps/war3net-map-script-builder.w3x \
  --campaign tests/fixtures/reference/stormlib-campaign.w3n \
  --output /tmp/w3xray-schema4-acceptance/output \
  --report /tmp/w3xray-schema4-acceptance/acceptance.json \
  --repeat 5
```

Verified on 2026-07-15: overall `pass`; map/campaign/71-file knowledge-pack checks passed, `batch_publication` reported `processed` then `reused` with zero leftovers, five repeated loads were stable, and all 10 GUI tabs loaded. Windows/CASC lanes were explicitly skipped on this non-Windows run.

1. Capture every source path, size, mtime-ns, and SHA-256 with `w3xtool.batch_runner.fingerprint_source` before processing. If sources were copied to a new root, match persisted results by SHA-256 and size and report path/mtime changes separately.
2. Copy the smallest and largest maps to private temporary directories. Final symlinks are intentionally rejected by the no-follow regular-file boundary.
3. Run the batch command against the smallest copy, largest copy, then the full source directory.
4. Require one summary row and one owned published directory per source, with the legacy reports plus `对象完整描述.tsv`, `掉落与获取关系.tsv`, `装备技能关系.tsv`, and `关系完整性.txt` present.
5. Recompute source fingerprints and require an exact byte-for-byte match with the before manifest.
6. Cross-check every icon row against its original SHA-256 and PNG magic, validate anonymous names, and parse all text/relation TSV files with a standard tab-delimited CSV reader.
7. Run `tests/test_real_map_item_relation_acceptance.py` with `W3XRAY_MAPS_ROOT`, `W3XRAY_OLD_OUTPUT`, and `W3XRAY_NEW_OUTPUT`; require every legacy non-placeholder value to remain bound to the same category/object identity, compatible level, and mapped text role, plus stable relation evidence, nested DOO indexes, and GUI/export count parity.

Current schema-4 / v4 content output verified on 2026-07-15:

- 39/39 published, with 1 complete, 38 partial, 0 restricted, and 0 failed results.
- 79,078 logical icon rows, 78,916 unique original paths, and 78,916 unique PNG paths; full physical/hash/magic audit passed.
- 700,979 complete-text rows and 13,442 relation rows; all state/type counts reconcile exactly and no malformed TSV rows remain.
- Every ownership marker and required report matched its summary row.
- No temporary publication directories remained.
- Real relation acceptance: 7 passed; focused audit suite: 241 passed; current full suite: 1,542 passed, 11 skipped, 1 subtest passed.
- The revision-4 real batch first processed 39/39 maps and then reused 39/39 validated publications. It left exactly 39 authoritative map directories and zero stage/backup/transaction/quarantine leftovers.
- All 39 desktop source paths, sizes, mtime-ns values, and SHA-256 values exactly match the before-run manifest for 4,227,067,802 source bytes. The historical v2 tree also retained 158,226 files, 5,860,928,096 bytes, and the same content+metadata Merkle SHA-256.
- No local classic MPQ/CASC text source is available. The icon-only trusted cache cannot fill descriptions, and the unbound legacy v2 description cache is rejected instead of being promoted to verified evidence.

Historical schema-3 / v2 output remains read-only at `map-extract-output-v2`; its older counts are not the schema-4 acceptance authority.

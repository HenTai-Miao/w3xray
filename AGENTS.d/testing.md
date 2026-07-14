# Testing and Acceptance

## Automated gates

Focused schema-v2 text/relation/icon suite:

```bash
uv run python -m pytest -q \
  tests/test_object_text_roles.py \
  tests/test_object_text_index.py \
  tests/test_description_cache.py \
  tests/test_doo.py \
  tests/test_doo_random_flags.py \
  tests/test_item_relation_models.py \
  tests/test_item_relations.py \
  tests/test_item_relation_scripts.py \
  tests/test_item_relation_exports.py \
  tests/test_gui_object_presentation.py \
  tests/test_gui_item_relations.py \
  tests/test_batch_map_processing.py \
  tests/test_batch_description_cache.py \
  tests/test_trusted_icon_cache.py \
  tests/test_knowledge_pack_item_relations.py \
  tests/test_real_map_text_acceptance.py
```

Verified result on 2026-07-15: 103 passed.

Repository test gate:

```bash
uv run w3xray-test
```

Verified result on 2026-07-15: 1,384 passed, 11 skipped, and 1 subtest passed.

Changed-file static gates:

```bash
uv run --with ruff ruff check PATHS...
uv run --with ruff ruff format --check PATHS...
uv run --with basedpyright basedpyright --level error PATHS...
```

The full-repository Ruff and basedpyright commands also expose historical baseline findings outside the batch feature. Do not silently broaden a batch change to repair that baseline; require all batch-changed Python paths to pass their focused gates.

Run static gates on the reviewed task path list, not every unrelated dirty-worktree path. The current shared worktree contains preserved user changes with independent Ruff/type/no-excuse findings; do not broaden this feature to rewrite those paths. New task modules and tests must still pass all four focused gates.

## Real-map acceptance

1. Capture every source path, size, mtime-ns, and SHA-256 with `w3xtool.batch_runner.fingerprint_source` before processing. If sources were copied to a new root, match persisted results by SHA-256 and size and report path/mtime changes separately.
2. Copy the smallest and largest maps to private temporary directories. Final symlinks are intentionally rejected by the no-follow regular-file boundary.
3. Run the batch command against the smallest copy, largest copy, then the full source directory.
4. Require one summary row and one owned published directory per source, with the legacy reports plus `对象完整描述.tsv`, `掉落与获取关系.tsv`, `装备技能关系.tsv`, and `关系完整性.txt` present.
5. Recompute source fingerprints and require an exact byte-for-byte match with the before manifest.
6. Cross-check every icon row against its original SHA-256 and PNG magic, validate anonymous names, and parse all text/relation TSV files with a standard tab-delimited CSV reader.
7. Run `tests/test_real_map_item_relation_acceptance.py` with `W3XRAY_MAPS_ROOT`, `W3XRAY_OLD_OUTPUT`, and `W3XRAY_NEW_OUTPUT`; require every legacy non-placeholder value to remain bound to the same category/object identity, compatible level, and mapped text role, plus stable relation evidence, nested DOO indexes, and GUI/export count parity.

Verified schema-v2 output on 2026-07-15:

- 39/39 published, with 1 complete, 38 partial, 0 restricted, and 0 failed results.
- 79,078 logical icon rows, 78,916 unique original paths, and 78,916 unique PNG paths; full physical/hash/magic audit passed.
- 766,396 complete-text rows and 13,047 relation rows; all state/type counts reconcile exactly and no malformed TSV rows remain.
- Every ownership marker and required report matched its summary row.
- No temporary publication directories remained.
- Real relation acceptance: 7 passed; identity-rule unit tests: 9 passed; focused feature suite: 103 passed; full suite: 1,384 passed, 11 skipped, 1 subtest passed.
- All 39 desktop source paths and SHA-256 values exactly match the before-run manifest.

# AGENTS.md

## Scope
- Applies to `/Users/zhongerbing/Documents/xm/war3_xg/w3xray` and descendants.
- Python 3.14+ project managed by `uv`; GUI uses CustomTkinter, map MPQ parsing is Python, and Windows CASC support uses pinned CascLib sources.
- Preserve unrelated dirty work. Never execute historical binaries, DLLs, or map payloads; source maps are read-only inputs.

## Orientation
- `main.py`: default GUI plus `description-cache`, `integrity`, `cli`, `current`, `casc`, `save`, `acceptance`, and `batch` dispatch.
- `w3xtool/gui.py`, `gui_topbar.py`, `gui_lifecycle.py`: GUI composition, top-level actions, and shutdown.
- `w3xtool/cli_options.py`, `api.py`, `archive_source.py`: existing map CLI, load/export API, and archive boundary.
- `w3xtool/current_map_models.py`: typed evidence and pure confidence resolution.
- `w3xtool/current_map_process.py`, `current_map_probe_command.py`: bounded OS process/open-file probes.
- `w3xtool/current_map_discovery.py`: bounded roots, recent cache/`.wgc`/game-log hints, and orchestration.
- `w3xtool/current_map_snapshot.py`, `current_map_snapshot_cleanup.py`: stable private copies and owned cleanup.
- `w3xtool/current_map_cli.py`, `gui_current_map.py`, `gui_current_map_worker.py`, `gui_current_map_presenter.py`: CLI/GUI current-map entry, worker, and presentation.
- `w3xtool/batch_cli.py`, `batch_runner.py`, `batch_map_processing.py`: sequential resumable map-directory extraction.
- `w3xtool/batch_manifest_*.py`, `batch_publication_*.py`: per-map content manifests, durable transactions, validation, and crash recovery.
- `w3xtool/batch_global_*.py`, `batch_resume.py`: authoritative immutable generations, `current.json`, checkpoints, and verified reuse.
- `w3xtool/batch_execution.py`, `batch_runtime.py`: isolated map workers, cancellation/timeouts, disk/RSS preflight, progress, and diagnostics.
- `w3xtool/integrity_snapshot*.py`, `integrity_cli*.py`: explicit read-only root snapshots, verification, and CLI boundaries.
- `w3xtool/integrity_report_*.py`: append-only manifested history for overwritten integrity reports.
- `w3xtool/description_cache_retained_*.py`: descriptor-relative, no-follow, two-round retained-cache evidence scanning and canonical reports.
- `w3xtool/object_text_models.py`, `object_text_index.py`, `description_cache.py`: lossless object-text evidence, seven states, and trusted base-object fills.
- `w3xtool/item_relation_models.py`, `item_relation_builder.py`, `item_relation_exports.py`: immutable drop/acquisition/equipment-skill relations and TSV reports.
- `w3xtool/gui_item_relations.py`, `gui_item_relation_layout.py`: searchable relation workspace and evidence navigation.
- `w3xtool/gui_worker_registry.py`, `gui_worker_host.py`: bounded GUI workers and Tk-main-thread callback delivery.
- `tests/`: pytest suite; current-map coverage is in `test_current_map_*.py` and `test_gui_current_map*.py`.

## Verified Commands
- Install dev dependencies: `uv sync --dev`.
- Run GUI: `uv run main.py`.
- Run map CLI: `uv run main.py cli <map-path>`.
- Locate current map: `uv run main.py current [--root PATH] [--accept-suggestion]`.
- Migrate trusted descriptions: `uv run main.py description-cache migrate --legacy-output <schema-1-root> --legacy-cache <schema-2-cache.tsv> --output <owned-cache-root>`.
- Batch schema 6: `uv run main.py batch <maps-root> --output <v6-root> --game-data <client-or-trusted-icon-root> --description-cache <owned-cache-root>`.
- Snapshot/verify inputs: `uv run main.py integrity snapshot --root LABEL=PATH --output <snapshot.json>` and `uv run main.py integrity verify --snapshot <snapshot.json>`.
- Inspect retained cache: `uv run main.py integrity retained-cache --active-root <owned-cache-root> --output <report.json>`.
- Full tests: `uv run w3xray-test` (Windows-safe); direct alternative: `uv run python -m pytest -q`.
- Maintained changed-path quality gate: `uv run w3xray-quality`.
- Focused tests: `uv run python -m pytest -q <test-paths>`.
- Lint/format changed Python: `uv run --with ruff ruff check <paths>` and `uv run --with ruff ruff format --check <paths>`.
- Type-check changed Python: `uv run --with basedpyright basedpyright --level error <paths>`; no checked-in basedpyright config.

## Knowledge
- `AGENTS.d/runtime.md`: schema-6 commands, protected roots, output semantics, required reports, and resume rules.
- `AGENTS.d/testing.md`: focused/full/static gates and schema-6 acceptance invariants.

## Boundaries
- Do not hand-edit caches/environments: `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`.
- Do not hand-edit packaging output: `build/`, `dist/`, `wheels/`, `*.egg-info/`.
- Treat `third_party/` as vendored; CascLib DLL/hash under `third_party/CascLib/bin/win-x64/` are generated local artifacts.
- Generated tables: `w3xtool/base_names.py`, `base_objects.py`, `westrings.py`, `jass_natives.py`, `field_meta.py`; update through their `build_*.py` generators.
- Keep current-map discovery bounded and evidence-based; never add memory reads, `Game.dll` loading, injection, elevation, or runtime decryption.
- Keep `/Users/zhongerbing/Desktop/Maps`, `map-extract-output`, `map-extract-output-v2`, `map-extract-output-v4`, and `trusted-icon-cache-classic` read-only; never use a historical root as a new-run destination.
- Generated caches, schema-6 batch outputs, logs, integrity snapshots, and acceptance reports belong outside the repository.

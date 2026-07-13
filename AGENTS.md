# AGENTS.md

## Scope
- Applies to `/Users/zhongerbing/Documents/xm/war3_xg/w3xray` and descendants.
- Python 3.14+ project managed by `uv`; GUI uses CustomTkinter, map MPQ parsing is Python, and Windows CASC support uses pinned CascLib sources.
- Preserve unrelated dirty work. Never execute historical binaries, DLLs, or map payloads; source maps are read-only inputs.

## Orientation
- `main.py`: default GUI plus `cli`, `current`, `casc`, `save`, and `acceptance` dispatch.
- `w3xtool/gui.py`, `gui_topbar.py`, `gui_lifecycle.py`: GUI composition, top-level actions, and shutdown.
- `w3xtool/cli_options.py`, `api.py`, `archive_source.py`: existing map CLI, load/export API, and archive boundary.
- `w3xtool/current_map_models.py`: typed evidence and pure confidence resolution.
- `w3xtool/current_map_process.py`, `current_map_probe_command.py`: bounded OS process/open-file probes.
- `w3xtool/current_map_discovery.py`: bounded roots, recent cache/`.wgc` hints, and orchestration.
- `w3xtool/current_map_snapshot.py`, `current_map_snapshot_cleanup.py`: stable private copies and owned cleanup.
- `w3xtool/current_map_cli.py`, `gui_current_map.py`, `gui_current_map_worker.py`, `gui_current_map_presenter.py`: CLI/GUI current-map entry, worker, and presentation.
- `tests/`: pytest suite; current-map coverage is in `test_current_map_*.py` and `test_gui_current_map*.py`.

## Verified Commands
- Install dev dependencies: `uv sync --dev`.
- Run GUI: `uv run main.py`.
- Run map CLI: `uv run main.py cli <map-path>`.
- Locate current map: `uv run main.py current [--root PATH] [--accept-suggestion]`.
- Full tests: `uv run w3xray-test` (Windows-safe); direct alternative: `uv run python -m pytest -q`.
- Focused tests: `uv run python -m pytest -q <test-paths>`.
- Lint/format changed Python: `uv run --with ruff ruff check <paths>` and `uv run --with ruff ruff format --check <paths>`.
- Type-check changed Python: `uv run --with basedpyright basedpyright --level error <paths>`; no checked-in basedpyright config.

## Boundaries
- Do not hand-edit caches/environments: `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`.
- Do not hand-edit packaging output: `build/`, `dist/`, `wheels/`, `*.egg-info/`.
- Treat `third_party/` as vendored; CascLib DLL/hash under `third_party/CascLib/bin/win-x64/` are generated local artifacts.
- Generated tables: `w3xtool/base_names.py`, `base_objects.py`, `westrings.py`, `jass_natives.py`, `field_meta.py`; update through their `build_*.py` generators.
- Keep current-map discovery bounded and evidence-based; never add memory reads, `Game.dll` loading, injection, elevation, or runtime decryption.

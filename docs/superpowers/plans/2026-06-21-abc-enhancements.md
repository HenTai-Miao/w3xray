# ABC Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the A/B/C enhancement tracks as read-only analysis: map audit, resource dependency graph, and version compatibility report. Follow-up page review also added read-only terrain/W3E, map-structure, gameplay-constant, and numeric order-id summaries.

**Architecture:** Keep each analysis as a focused pure module consuming `MapData`. `resources.py` owns resource extraction and unreferenced resource detection, `compat.py` owns target-version compatibility findings, `audit.py` stays the health-summary aggregator, and `main.py` only renders compact CLI lines.

**Tech Stack:** Python 3.14, frozen dataclasses, pytest, existing `MapData` / `GameObject` structures.

---

### Task 1: Resource Dependency Core

**Files:**
- Create: `w3xtool/resources.py`
- Test: `tests/test_resources.py`

- [x] **Step 1: Write failing tests**

Cover:
- Object icon/model field paths become resource references.
- Script literals such as `war3mapImported\\foo.blp` become script references.
- Archive asset files that are never referenced are reported as unreferenced.

Run: `uv run pytest tests/test_resources.py -q`
Expected: FAIL because `w3xtool.resources` does not exist.

- [x] **Step 2: Implement minimal resource graph**

Create frozen `ResourceRef`, `ResourceNode`, `ResourceReport` plus `build_resource_report(md)`.

Rules:
- Normalize slash direction and case for matching.
- Do not reopen MPQ.
- Only inspect parsed object fields, scripts, and `md.all_files`.

- [x] **Step 3: Verify**

Run: `uv run pytest tests/test_resources.py -q`
Expected: PASS.

### Task 2: Version Compatibility Core

**Files:**
- Create: `w3xtool/compat.py`
- Test: `tests/test_compat.py`

- [x] **Step 1: Write failing tests**

Cover:
- Lua maps warn for target `1.24E`.
- `w3i.version` 28/31 warns for target `1.24E`.
- Large-map flag warns for classic target.
- Old 1.20E return bug helpers such as `H2I`/`I2U` warn for target `1.24E`.
- Plain version 25 JASS map reports compatible.

Run: `uv run pytest tests/test_compat.py -q`
Expected: FAIL because `w3xtool.compat` does not exist.

- [x] **Step 2: Implement compatibility report**

Create frozen `CompatItem`, `CompatReport`, `CompatSeverity` plus `build_compat_report(md, target_patch="1.24E")`.
Detect obvious JASS return-bug casts where a function returns a parameter across `integer` and handle-derived types.

Rules:
- Read only from `MapData`.
- Keep messages deterministic.
- Make target patch explicit in report.

- [x] **Step 3: Verify**

Run: `uv run pytest tests/test_compat.py -q`
Expected: PASS.

### Task 3: CLI Integration and Documentation

**Files:**
- Modify: `main.py`
- Modify: `w3xtool/audit.py`
- Modify: `README.md`
- Test: `tests/test_cli_audit.py`
- Test: `tests/test_audit.py`

- [x] **Step 1: Extend failing CLI tests**

Assert CLI output includes compact `资源:` and `兼容:` blocks.

- [x] **Step 2: Render reports**

Use `build_resource_report()` and `build_compat_report()` in `iter_cli_summary_lines()`.

- [x] **Step 3: Enrich audit**

Add warning items when resource report has unreferenced assets and compatibility report has warnings.

- [x] **Step 4: Document**

Update README to describe resource dependency and 1.24E compatibility analysis.

- [x] **Step 5: Verify**

Run:
- `uv run pytest tests/test_resources.py tests/test_compat.py tests/test_audit.py tests/test_cli_audit.py -q`
- `uv run pytest -q`

### Task 4: Terrain/W3E Summary

**Files:**
- Create: `w3xtool/terrain.py`
- Modify: `main.py`
- Modify: `README.md`
- Test: `tests/test_terrain.py`
- Test: `tests/test_cli_audit.py`

- [x] **Step 1: Write failing tests**

Cover:
- `war3map.w3e` header parsing returns version, base tileset, custom flag, ground tile IDs, cliff tile IDs, and terrain grid size.
- Invalid or truncated W3E data returns no summary.
- CLI output includes a compact `地形:` block when terrain metadata is available.

- [x] **Step 2: Implement W3E parser**

Create frozen `TerrainInfo`, `parse_w3e_header(data)`, and `terrain_info_from_map_path(path)`.

Rules:
- Keep the parser independent from the large API module.
- Read only `war3map.w3e`; do not modify maps.
- Gracefully omit the section when terrain data is absent or unreadable.

- [x] **Step 3: Verify**

Run:
- `uv run pytest tests/test_terrain.py tests/test_cli_audit.py -q`

### Task 5: Map Structure, Gameplay Constants, and Numeric Orders

**Files:**
- Create: `w3xtool/mapmeta.py`
- Create: `w3xtool/gameplay.py`
- Modify: `w3xtool/orders.py`
- Modify: `main.py`
- Modify: `README.md`
- Test: `tests/test_mapmeta.py`
- Test: `tests/test_gameplay.py`
- Test: `tests/test_orders.py`
- Test: `tests/test_cli_audit.py`

- [x] **Step 1: Write failing tests**

Cover:
- `war3map.w3r/.w3c/.w3s` header count parsing.
- `war3map.wpm` pathing map dimensions and cell count.
- `war3mapMisc.txt` section/key/value parsing.
- `Issue*OrderById(851xxx)` numeric order extraction and known-name mapping.
- CLI blocks for map structure and gameplay constants.

- [x] **Step 2: Implement focused modules**

Create `MapStructureReport`, `PathingSummary`, `GameplayConstant`, and MPQ path readers that gracefully return empty results when files are missing or unreadable.

- [x] **Step 3: Integrate CLI and docs**

Render compact `地图结构:` and `游戏常数:` sections; document numeric order IDs and the new modules.

- [x] **Step 4: Verify**

Run:
- `uv run pytest tests/test_mapmeta.py tests/test_gameplay.py tests/test_orders.py tests/test_cli_audit.py -q`

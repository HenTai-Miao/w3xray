# Current Game Map Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely locate the Warcraft III map tied to the running game, snapshot it, and load it through the existing GUI and CLI workflows.

**Architecture:** Immutable observations feed a pure evidence resolver. Platform probes and a bounded hint scanner are adapters; a separate snapshot module owns stable copying. GUI and CLI orchestration consume the same typed resolution without changing the map parser.

**Tech Stack:** Python 3.14, standard library, pytest, CustomTkinter, existing W3XRAY loader.

## Global Constraints

- Do not read process memory, inject code, load `Game.dll`, elevate privileges, or execute old binaries/map payloads.
- Do not modify source maps; verify their identity before and after snapshot copying.
- Auto-load only a unique process-linked map. Suggestions require explicit confirmation.
- Bound probes to 8 roots, 8 PIDs, 5000 entries, 5 levels, a 2-second command timeout, and 1 MiB output.
- Keep every new handwritten Python module below 250 pure LOC.
- Preserve all pre-existing uncommitted work. Do not stage, commit, push, reset, or checkout.

---

### Task 1: Typed evidence resolution

**Files:**
- Create: `w3xtool/current_map_models.py`
- Test: `tests/test_current_map_resolution.py`

**Interfaces:**
- Produces: `GameProcess`, `MapEvidence`, `MapCandidate`, `CurrentMapResolution`, `EvidenceKind`, `ResolutionStatus`, and `resolve_current_map(...)`.
- Direct evidence kinds are `DIRECT_OPEN` and `EXPLICIT_ARGUMENT`; hints are `WGC_REFERENCE` and `RECENT_CACHE`.

- [ ] Write Given/When/Then tests for one direct path, duplicate evidence for one path, two direct paths, suggestion-only with/without a game process, and unavailable direct probes.
- [ ] Run `uv run pytest -q tests/test_current_map_resolution.py` and confirm import/behavior failures.
- [ ] Implement path normalization, evidence grouping, deterministic ordering, and exhaustive status construction.
- [ ] Re-run the test file and confirm it passes.

### Task 2: Process-linked platform probes

**Files:**
- Create: `w3xtool/current_map_process.py`
- Test: `tests/test_current_map_process.py`

**Interfaces:**
- Consumes: `GameProcess`, `MapEvidence`, `EvidenceKind`.
- Produces: `probe_game_processes()`, `probe_open_map_files(processes)`, `explicit_argument_evidence(processes, roots)`, plus typed probe reports.

- [ ] Test parsing of POSIX and Windows process records, exclusion of editor/launcher processes, NUL-delimited `lsof` with Chinese paths, `/proc` symlinks, explicit quoted arguments, timeout, and malformed output.
- [ ] Run the focused tests and confirm failures before implementation.
- [ ] Implement platform dispatch using absolute tools when present, `shell=False`, timeouts, output limits, PID/path budgets, and no raw command logging.
- [ ] Add a POSIX integration test that holds a real temporary `.w3x` open in the pytest PID and probes only that injected PID.
- [ ] Re-run the focused tests.

### Task 3: Bounded disk hints and orchestration

**Files:**
- Create: `w3xtool/current_map_discovery.py`
- Test: `tests/test_current_map_discovery.py`

**Interfaces:**
- Consumes: process/open-file reports and `parse_game_configuration`.
- Produces: `discover_default_map_roots(extra_roots=())` and `locate_current_map(extra_roots=(), now_ns=None)`.

- [ ] Test root de-duplication, bounds/depth, regular-file filtering, recent-cache window, game-running requirement, `.wgc` reference resolution, stale hints, and direct-over-hint precedence.
- [ ] Run focused tests and confirm failures.
- [ ] Implement bounded metadata-only scanning and call the pure resolver.
- [ ] Re-run focused tests.

### Task 4: Stable source snapshot

**Files:**
- Create: `w3xtool/current_map_snapshot.py`
- Test: `tests/test_current_map_snapshot.py`

**Interfaces:**
- Produces: `CurrentMapSnapshot`, `CurrentMapSnapshotError`, `create_current_map_snapshot(path)`, and `cleanup_current_map_snapshot(snapshot)`.

- [ ] Test exact bytes/hash, fixed safe filename, source identity preservation, invalid/non-regular input, changing source rejection, cleanup, and bounded stale cleanup.
- [ ] Run focused tests and confirm failures.
- [ ] Implement private temp directories, identity checks, streaming hash copy, flush/fsync, and safe cleanup.
- [ ] Re-run focused tests.

### Task 5: CLI entry

**Files:**
- Create: `w3xtool/current_map_cli.py`
- Modify: `main.py`
- Test: `tests/test_current_map_cli.py`

**Interfaces:**
- Produces: `parse_current_map_cli_options(argv)` and `run_current_map_cli(options)`.
- Delegates successful snapshots to `run_cli(replace(options.map_options, map_path=snapshot.path))` and always cleans CLI snapshots.

- [ ] Test all forwarded options, repeated roots, direct success, suggestion refusal/acceptance, ambiguity, not-found/unavailable, cleanup on parser failure, and an actual subprocess bad-option result.
- [ ] Run focused tests and confirm failures.
- [ ] Implement typed parsing, stable Chinese diagnostics, exit codes `0/2/3`, delegation, and `finally` cleanup.
- [ ] Re-run focused tests.

### Task 6: Non-blocking GUI entry

**Files:**
- Create: `w3xtool/gui_current_map.py`
- Modify: `w3xtool/gui.py`
- Modify: `w3xtool/gui_topbar.py`
- Modify: `w3xtool/gui_lifecycle.py`
- Test: `tests/test_gui_current_map.py`

**Interfaces:**
- Produces: `CurrentMapGuiMixin.on_open_current_map()` with queue-based worker results.
- Delegates only accepted snapshots to existing `_start_path_load(snapshot.path)`.

- [ ] Test button wiring, worker start, direct delegation, suggestion confirmation, ambiguity/no-result messages, busy-state suppression, and snapshot cleanup during close.
- [ ] Run focused tests and confirm failures.
- [ ] Implement the mixin, initialize it in `App`, add the topbar button, and shut it down before Tk destruction.
- [ ] Re-run focused tests.

### Task 7: Documentation and verification

**Files:**
- Modify: `README.md`
- Create or update: `AGENTS.md` only with verified project commands and boundaries.

- [ ] Document `main.py current`, GUI behavior, confidence rules, and memory/decryption limitations.
- [ ] Run all new focused tests and existing CLI/GUI regression tests.
- [ ] Run ruff/basedpyright if configured, the programming no-excuse checker, and pure-LOC checks for every changed Python file.
- [ ] Run `uv run pytest -q` and record exact counts.
- [ ] Hash every source map before and after real-map CLI/current-map regression; confirm no source changed.
- [ ] Review `git diff` to prove unrelated dirty HM3W work was preserved and no old binary/DLL was executed.

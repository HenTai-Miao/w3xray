# Complete Static Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make real Warcraft III WTG/TriggerData, external listfiles, knowledge-pack reporting, safe exports, archive diagnostics, CLI workflows, and Windows CASC installation reading work end to end without runtime execution or protection bypass.

**Architecture:** Parse TriggerData and TriggerStrings into a typed schema before reading WTG ECA bytes, and expose the resulting tree through TSV and a dedicated GUI view. Route game data through a common source protocol with CascLib on Windows and existing directory/path-map readers as fallbacks; route all output through one safe writer and all map opens through typed diagnostics.

**Tech Stack:** Python 3.14, `uv`, `pytest`, CustomTkinter/Tkinter, `ctypes` on Windows, PyInstaller, CascLib 3.0 (MIT), Apache-2.0 wc3libs test fixture.

## Global Constraints

- Keep all map and game-data operations read-only.
- Do not execute map scripts, call platform APIs, inspect process memory, dump runtime plaintext, or bypass protection.
- Preserve `load_map(path)` and `write_knowledge_pack(md, out_dir)` compatibility.
- Keep every new or expanded Python module at or below 250 pure LOC; split by responsibility before crossing the limit.
- Use real-format WTG and TriggerData/TriggerStrings fixtures; implementation-shaped fake formats do not satisfy acceptance.
- Optional TriggerData, icon, or CASC failures degrade the enhancement and never abort the base knowledge pack.
- Put downloads/build intermediates under `${TMPDIR:-/tmp}` and remove them after use.
- Keep `.DS_Store`, caches, build directories, downloaded archives, and generated binaries out of commits unless the binary is an intentional verified CascLib distribution artifact.
- Every vendored fixture must have a pinned upstream commit, source URL, license copy, original SHA256, and extraction/copy notes in a neighboring README.

---

### Task 1: Real TriggerData and TriggerStrings Schema

**Files:**
- Create: `w3xtool/trigger_schema.py`
- Create: `w3xtool/trigger_strings.py`
- Modify: `w3xtool/triggerdata.py`
- Create: `tests/fixtures/trigger/TriggerData.txt`
- Create: `tests/fixtures/trigger/TriggerStrings.txt`
- Create: `tests/fixtures/trigger/README.md`
- Create: `tests/fixtures/licenses/War3Lib-Apache-2.0.txt`
- Create: `tests/test_trigger_schema.py`
- Modify: `tests/test_triggerdata_semantics.py`

**Interfaces:**
- Produces: `TriggerFunctionKind`, `TriggerFunctionSchema`, `TriggerSchema`, `parse_trigger_schema(trigger_data: str, trigger_strings: str) -> TriggerSchema`.
- Produces: `load_trigger_schema_from_source(source: TriggerDataSource | None) -> TriggerSchema | None`.
- Produces: `render_eca_semantic(function: TriggerEcaFunction, schema: TriggerSchema | None, *, wts: Mapping[int, str] | None = None, object_names: Mapping[str, str] | None = None) -> str`.
- Consumes: `GameDataSource.has_file/read_file` and `decode_warcraft_string`.

- [ ] **Step 1: Vendor attributed real-format metadata and add failing schema tests**

Copy the complete files from Crainax/War3Lib commit
`03cc4765f6b5e262c0e9d6ed9f36e1f3f12c77bf` (Apache-2.0):

```text
https://raw.githubusercontent.com/Crainax/War3Lib/03cc4765f6b5e262c0e9d6ed9f36e1f3f12c77bf/fdf/TriggerData.txt
SHA256 e017e7caf50bc1e2e5426d7cbbd5710c78cea360151cdccbfa0ab2f1fc7f233b
https://raw.githubusercontent.com/Crainax/War3Lib/03cc4765f6b5e262c0e9d6ed9f36e1f3f12c77bf/fdf/TriggerStrings.txt
SHA256 1f926154476c4674b5333e3c418ce65b3f724a2440216206285137c29ed06852
```

`tests/fixtures/trigger/README.md` records those URLs, hashes, the direct-copy
method, and the covered signatures/localized duplicate-key records.

```python
def test_real_trigger_data_signature_and_trigger_strings_template() -> None:
    data = _fixture("TriggerData.txt")
    strings = _fixture("TriggerStrings.txt")

    schema = parse_trigger_schema(data, strings)

    action = schema.require(TriggerFunctionKind.ACTION, "DisplayTextToForce")
    assert action.parameter_types == ("force", "StringExt")
    assert action.display_name


def test_missing_trigger_strings_keeps_signature_without_fake_template() -> None:
    schema = parse_trigger_schema("[TriggerActions]\nDisplayTextToForce=0,force,StringExt\n", "")

    action = schema.require(TriggerFunctionKind.ACTION, "DisplayTextToForce")
    assert action.parameter_types == ("force", "StringExt")
    assert action.template is None
```

- [ ] **Step 2: Run the schema tests and confirm the old parser fails**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_trigger_schema.py -q -p no:cacheprovider`

Expected: FAIL because `w3xtool.trigger_schema` does not exist.

- [ ] **Step 3: Implement typed schema parsing**

```python
class TriggerFunctionKind(StrEnum):
    EVENT = "event"
    CONDITION = "condition"
    ACTION = "action"
    CALL = "call"


@dataclass(frozen=True, slots=True)
class TriggerFunctionSchema:
    kind: TriggerFunctionKind
    name: str
    category: str
    return_type: str | None
    parameter_types: tuple[str, ...]
    display_name: str
    template: str | None


@dataclass(frozen=True, slots=True)
class TriggerSchema:
    functions: Mapping[tuple[TriggerFunctionKind, str], TriggerFunctionSchema]
    has_trigger_strings: bool = False

    def get(self, kind: TriggerFunctionKind, name: str) -> TriggerFunctionSchema | None: ...
    def require(self, kind: TriggerFunctionKind, name: str) -> TriggerFunctionSchema: ...
```

Parse `[TriggerEvents]`, `[TriggerConditions]`, `[TriggerActions]`, and `[TriggerCalls]` as comma-separated signatures. Preserve repeated TriggerStrings keys as ordered values instead of collapsing the section into a dictionary. Never treat the TriggerData signature itself as display text.

- [ ] **Step 4: Implement resilient source loading and semantic fallback**

```python
def load_trigger_schema_from_source(source: TriggerDataSource | None) -> TriggerSchema | None:
    if source is None:
        return None
    try:
        data = _read_first(source, _TRIGGER_DATA_NAMES)
        strings = _read_first(source, _TRIGGER_STRING_NAMES)
    except (FileNotFoundError, OSError, ValueError, CascUnsupportedError):
        return None
    if data is None:
        return None
    return parse_trigger_schema(_decode(data), _decode(strings or b""))
```

Import the existing `CascUnsupportedError` from `w3xtool.casc_source`; Task 1
does not introduce a second CASC error hierarchy.

- [ ] **Step 5: Run schema and legacy semantic tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_trigger_schema.py tests/test_triggerdata_semantics.py -q -p no:cacheprovider`

Expected: PASS; no output contains `0,force,StringExt(...)` as a semantic sentence.

- [ ] **Step 6: Commit the schema task**

```bash
git add w3xtool/trigger_schema.py w3xtool/trigger_strings.py w3xtool/triggerdata.py tests/fixtures/trigger tests/fixtures/licenses tests/test_trigger_schema.py tests/test_triggerdata_semantics.py
git commit -m "feat: parse real trigger schemas"
```

### Task 2: Spec-Driven Classic and Reforged WTG ECA

**Files:**
- Create: `w3xtool/wtg_models.py`
- Create: `w3xtool/wtg_reader.py`
- Create: `w3xtool/wtg_classic.py`
- Create: `w3xtool/wtg_reforged.py`
- Create: `w3xtool/wtg_diagnostics.py`
- Create: `w3xtool/load_context.py`
- Rewrite: `w3xtool/wtg_eca.py`
- Modify: `w3xtool/wtg.py`
- Modify: `w3xtool/api.py`
- Modify: `w3xtool/map_extras.py`
- Modify: `w3xtool/trigger_exports.py`
- Create: `tests/fixtures/wtg/classic-wc3libs-war3map.wtg`
- Create: `tests/fixtures/wtg/reforged-war3net-map-script-builder.wtg`
- Create: `tests/fixtures/wtg/README.md`
- Create: `tests/fixtures/maps/war3net-map-script-builder.w3x`
- Create: `tests/fixtures/maps/README.md`
- Create: `tests/fixtures/licenses/wc3libs-Apache-2.0.txt`
- Create: `tests/fixtures/licenses/War3Net-MIT.txt`
- Create: `tests/test_wtg_real_fixture.py`
- Modify: `tests/test_wtg.py`
- Modify: `tests/test_wtg_eca_exports.py`

**Interfaces:**
- Consumes: `TriggerSchema` from Task 1.
- Produces: `parse_wtg(data: bytes, schema: TriggerSchema | None = None) -> TriggerTreeSummary`.
- Produces: `TriggerParseFailure`, `UnknownTriggerFunction`, and summary fields `missing_schema_functions` and `parse_failures`.
- Produces: ECA nodes with `branch`, `parameters`, `children`, `depth`, and `source_offset`.
- Produces: `MapLoadContext(external_names=(), trigger_schema=None)` and changes
  `load_map(path, ..., load_context: MapLoadContext | None = None)` compatibly so
  `add_trigger_summary` receives the selected schema before any GUI view is built.

- [ ] **Step 1: Vendor pinned Classic/Reforged fixtures and write red tests**

Use these unmodified real files and record their provenance in the fixture READMEs:

```text
Classic WTG: inwc3/wc3libs commit ac41f780a5e2dfc35310be4ed3267f23ab3fea44
src/test/resources/wc3data/WTG/war3map.wtg
SHA256 c3398add7e0e51b66300629f152d190d80e00a4aecb6c64e07b81f3963185cb8
License: Apache-2.0

Reforged map: Drake53/War3Net commit 11ff1ed081e02a91fc960ba653b0ee91e9b498b0
tests/War3Net.TestTools.UnitTesting/TestData/Maps/MapScriptBuilderTestMap1.w3x
SHA256 c405bf8750fc72fc2c21a2a69b37a4703bf30f720a378bb70bf8a03275fdc415
Extracted war3map.wtg SHA256 6b64cb88e25da01163130f0bd97680dc743bd826fa1b73c590e16278cb719503
License: MIT
```

The Reforged fixture contains variables, arrays, nested calls, code/bool forms,
multiple-function branches, and child ECA groups. The Classic fixture prevents
the Reforged implementation from becoming the only real-format path.

```python
def test_wc3libs_real_wtg_never_silently_accepts_bad_parameter_values() -> None:
    raw = CLASSIC_FIXTURE.read_bytes()
    schema = load_fixture_schema()

    summary = parse_wtg(raw, schema)

    assert not summary.parse_failures
    assert summary.eca_functions
    assert all(0 <= param.parameter_type <= 3 for node in walk_eca(summary) for param in node.parameters)


def test_wtg_without_schema_keeps_headers_and_reports_missing_schema() -> None:
    summary = parse_wtg(REFORGED_FIXTURE.read_bytes())

    assert summary.triggers
    assert summary.eca_functions == ()
    assert summary.missing_schema_functions
```

- [ ] **Step 2: Run real WTG tests and confirm failure**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_wtg_real_fixture.py -q -p no:cacheprovider`

Expected: FAIL because the current parser reads an implementation-shaped parameter count.

- [ ] **Step 3: Split WTG models and readers before adding logic**

```python
@dataclass(frozen=True, slots=True)
class TriggerParseFailure:
    trigger_name: str
    function_name: str
    offset: int
    reason: str


@dataclass(frozen=True, slots=True)
class TriggerTreeSummary:
    # Existing metadata fields remain unchanged.
    eca_functions: tuple[TriggerEcaFunction, ...] = ()
    missing_schema_functions: tuple[UnknownTriggerFunction, ...] = ()
    parse_failures: tuple[TriggerParseFailure, ...] = ()
```

Keep `w3xtool.wtg` as the compatibility facade and move version-specific layouts out before new code pushes it over 250 pure LOC.

- [ ] **Step 4: Implement schema-counted normal parameters and special forms**

```python
def read_eca(reader: WtgReader, trigger_name: str, schema: TriggerSchema, *, has_branch: bool, depth: int) -> TriggerEcaFunction:
    kind = read_function_kind(reader.i32())
    branch = reader.i32() if has_branch else 0
    name = reader.cstr()
    enabled = bool(reader.i32())
    function_schema = schema.require(kind, name)
    params = tuple(read_parameter(reader, schema, type_name, depth=depth + 1) for type_name in function_schema.parameter_types)
    child_count = reader.bounded_count("child ECA")
    children = tuple(read_eca(reader, trigger_name, schema, has_branch=True, depth=depth + 1) for _ in range(child_count))
    return TriggerEcaFunction(trigger_name, kind.value, name, enabled, params, children, depth=depth, branch=branch)
```

Implement version 4 and version 7 parameter layouts, nested begin-function records, array indexes, bool/code special parameters, branch/group fields, recursion limits, and exact offset diagnostics from the referenced wc3libs reader.

- [ ] **Step 5: Replace stale unexpanded messages**

`format_trigger_tree_tsv`, `format_trigger_eca_tsv`, GUI reports, map info, and CLI must distinguish:

```text
缺少 TriggerData/TriggerStrings：只读取触发器头
WTG 解析失败：<trigger>/<function> @ 0x<offset>：<reason>
```

- [ ] **Step 6: Run WTG regression tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_wtg.py tests/test_wtg_eca_exports.py tests/test_wtg_real_fixture.py tests/test_trigger_schema.py -q -p no:cacheprovider`

Expected: PASS for real and synthetic header fixtures; the obsolete fake ECA-count fixture is replaced, not blessed.

- [ ] **Step 7: Commit the WTG task**

```bash
git add w3xtool/wtg*.py w3xtool/load_context.py w3xtool/api.py w3xtool/map_extras.py w3xtool/trigger_exports.py tests/fixtures/wtg tests/fixtures/maps tests/fixtures/licenses tests/test_wtg.py tests/test_wtg_eca_exports.py tests/test_wtg_real_fixture.py
git commit -m "fix: parse WTG ECA from real schemas"
```

### Task 3: GUI Trigger ECA Workbench

**Files:**
- Create: `w3xtool/gui_trigger_eca.py`
- Modify: `w3xtool/gui_shell.py`
- Modify: `w3xtool/gui_data_refresh.py`
- Modify: `w3xtool/gui.py`
- Modify: `tests/gui_base.py`
- Create: `tests/test_gui_trigger_eca.py`
- Modify: `tests/test_gui_layout.py`

**Interfaces:**
- Consumes: `TriggerTreeSummary.eca_functions`, `missing_schema_functions`, and `parse_failures`.
- Produces: `TriggerEcaViewMixin._build_trigger_eca_tab`, `_refresh_trigger_eca`, `_show_trigger_eca_detail`, and `_search_trigger_eca`.

- [ ] **Step 1: Write failing GUI hierarchy and state tests**

```python
def test_gui_trigger_tab_renders_function_hierarchy(self) -> None:
    self.app._render_map(_map_with_nested_eca(), [], [], None)

    roots = self.app.trigger_eca_tree.get_children()
    assert roots
    action = self.app.trigger_eca_tree.get_children(roots[0])[0]
    nested = self.app.trigger_eca_tree.get_children(action)[0]
    assert self.app.trigger_eca_tree.item(action, "text") == "创建单位"
    assert self.app.trigger_eca_tree.item(nested, "text") == "整数比较"


def test_gui_trigger_tab_distinguishes_missing_schema_from_parse_failure(self) -> None:
    self.app._render_map(_map_with_trigger_diagnostics(), [], [], None)

    text = self.app.trigger_eca_status.cget("text")
    assert "缺 TriggerData" in text
    assert "解析失败" in text
```

- [ ] **Step 2: Run GUI tests and confirm missing tab**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_gui_trigger_eca.py tests/test_gui_layout.py -q -p no:cacheprovider`

Expected: FAIL because the tab and widgets do not exist.

- [ ] **Step 3: Build a stable two-pane trigger tab**

```python
class TriggerEcaViewMixin:
    def _build_trigger_eca_tab(self, parent) -> None: ...
    def _refresh_trigger_eca(self) -> None: ...
    def _show_trigger_eca_detail(self, _event=None) -> None: ...
    def _search_trigger_eca(self) -> None: ...
```

Use one `ttk.Treeview` with stable row IDs and lazy child insertion on the left, and one read-only detail textbox on the right. Add the tab label `GUI触发器` between `地图信息` and `场景放置`; keep `触发指令` for chat commands.

- [ ] **Step 4: Wire refresh and cleanup**

Reset trigger widgets in `tests/gui_base.py`, populate them from `_render_map`, preserve selection where possible, and avoid image loading or one-widget-per-ECA allocation.

- [ ] **Step 5: Run GUI tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_gui_trigger_eca.py tests/test_gui_layout.py tests/test_gui_reports.py -q -p no:cacheprovider`

Expected: PASS with nested nodes, details, search, missing schema, and parse failure states.

- [ ] **Step 6: Commit the GUI task**

```bash
git add w3xtool/gui_trigger_eca.py w3xtool/gui_shell.py w3xtool/gui_data_refresh.py w3xtool/gui.py tests/gui_base.py tests/test_gui_trigger_eca.py tests/test_gui_layout.py
git commit -m "feat: add GUI trigger ECA browser"
```

### Task 4: Verified External Listfile and Dynamic Coverage

**Files:**
- Modify: `w3xtool/load_context.py`
- Modify: `w3xtool/external_listfile.py`
- Modify: `w3xtool/api.py`
- Modify: `w3xtool/gui_lifecycle.py`
- Modify: `w3xtool/gui_loader.py`
- Modify: `w3xtool/gui_loader_runner.py`
- Modify: `w3xtool/knowledge_pack.py`
- Rewrite: `w3xtool/knowledge_requirements.py`
- Modify: `tests/test_external_listfile_gui.py`
- Create: `tests/test_external_listfile_loading.py`
- Create: `tests/test_requirement_coverage_dynamic.py`

**Interfaces:**
- Consumes and extends the Task 2 `MapLoadContext(external_names, trigger_schema)` flow.
- Produces: `ExternalListfileReport(confirmed, missing, unsafe, duplicates)`.
- Changes compatibly: `load_map(path, ..., load_context: MapLoadContext | None = None)`.
- Changes compatibly: `format_requirement_coverage(md: MapData | None = None, capabilities: ExtractionCapabilities | None = None) -> str`.
- Produces in `w3xtool/knowledge_requirements.py`:
  `ExtractionCapabilities(game_data_kind, has_trigger_schema, has_trigger_strings,
  external_listfile, archive_diagnosis_kind)` with immutable fields and defaults for
  the legacy no-argument report.

```python
@dataclass(frozen=True, slots=True)
class ExtractionCapabilities:
    game_data_kind: str = "missing"
    has_trigger_schema: bool = False
    has_trigger_strings: bool = False
    external_listfile: ExternalListfileReport | None = None
    archive_diagnosis_kind: str = ""
```

- [ ] **Step 1: Write failing listfile truthfulness tests**

```python
def test_load_map_confirms_external_names_before_listing(monkeypatch) -> None:
    archive = FakeArchive(existing={"hidden/config.json"})
    context = MapLoadContext(external_names=("hidden/config.json", "ghost.blp", "../escape"))

    md = load_map_with_archive(archive, context)

    assert md.external_listfile.confirmed == ("hidden/config.json",)
    assert md.external_listfile.missing == ("ghost.blp",)
    assert md.external_listfile.unsafe == ("../escape",)
    assert "ghost.blp" not in md.all_files
```

- [ ] **Step 2: Write failing dynamic coverage tests**

```python
def test_requirement_coverage_uses_map_results() -> None:
    md = MapData(path="x.w3x", name="x")
    md.trigger_summary = summary_with_missing_schema()

    text = format_requirement_coverage(md, ExtractionCapabilities(game_data_kind="missing"))

    assert "WTG ECA\t部分提取" in text
    assert "原生 CASC\t源数据缺失" in text
    assert "运行时解密\t不支持" in text
```

- [ ] **Step 3: Run tests and confirm fixed-matrix/current-mutation failures**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_external_listfile_loading.py tests/test_requirement_coverage_dynamic.py -q -p no:cacheprovider`

Expected: FAIL because no load context/report exists and coverage is static.

- [ ] **Step 4: Extend the immutable load context with validation results**

```python
@dataclass(frozen=True, slots=True)
class ExternalListfileReport:
    confirmed: tuple[str, ...]
    missing: tuple[str, ...]
    unsafe: tuple[str, ...]
    duplicates: tuple[str, ...]
```

Validate names against the archive during map loading. Selecting or clearing the GUI listfile rebuilds the active view with the same `game_data_path`. Remove `_merge_external_file_names`; knowledge-pack export must not mutate `MapData`.

- [ ] **Step 5: Implement dynamic requirement rows**

Compute statuses from actual artifact counts, trigger diagnostics, source probes, listfile report, extraction completeness, and explicit static-only boundaries. Keep the old no-argument call returning a generic capability description for compatibility tests.

- [ ] **Step 6: Run listfile, pack, and GUI tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_external_listfile_gui.py tests/test_external_listfile_loading.py tests/test_requirement_coverage_dynamic.py tests/test_knowledge_pack*.py -q -p no:cacheprovider`

Expected: PASS; repeated pack exports leave `md.all_files` unchanged.

- [ ] **Step 7: Commit the loading task**

```bash
git add w3xtool/load_context.py w3xtool/external_listfile.py w3xtool/api.py w3xtool/gui_lifecycle.py w3xtool/gui_loader.py w3xtool/gui_loader_runner.py w3xtool/knowledge_pack.py w3xtool/knowledge_requirements.py tests/test_external_listfile_gui.py tests/test_external_listfile_loading.py tests/test_requirement_coverage_dynamic.py
git commit -m "fix: verify external listfile analysis"
```

### Task 5: Unified Safe Output

**Files:**
- Create: `w3xtool/safe_output.py`
- Modify: `w3xtool/archive_export_paths.py`
- Modify: `w3xtool/archive_export.py`
- Modify: `w3xtool/knowledge_io.py`
- Modify: `w3xtool/knowledge_assets.py`
- Modify: `w3xtool/knowledge_unknown_exports.py`
- Modify: `w3xtool/knowledge_object_exports.py`
- Modify: `w3xtool/knowledge_script_exports.py`
- Modify: `tests/test_export_safety.py`
- Create: `tests/test_safe_output.py`

**Interfaces:**
- Produces: `safe_relative_path(name: str) -> PurePosixPath | None`.
- Produces: `safe_destination(root: str, name: str) -> str | None`.
- Produces: `write_bytes_safely(root: str, name: str, data: bytes) -> SafeWriteResult` and `write_text_safely(...)`.
- Existing `_safe_export_path` delegates to `safe_destination`.

- [ ] **Step 1: Write path and symlink red tests**

```python
@pytest.mark.parametrize("name", ["../x", "/tmp/x", "//server/share/x", "C:/x", "a\0b"])
def test_rejects_non_relative_output_names(name: str) -> None:
    assert safe_relative_path(name) is None


def test_rejects_existing_destination_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "out"
    root.mkdir()
    (root / "assets").symlink_to(outside, target_is_directory=True)

    result = write_bytes_safely(str(root), "assets/x.bin", b"x")

    assert result.status is SafeWriteStatus.UNSAFE
    assert not (outside / "x.bin").exists()
```

- [ ] **Step 2: Run safety tests and confirm current writer follows links**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_safe_output.py tests/test_export_safety.py -q -p no:cacheprovider`

Expected: FAIL because the unified writer does not exist and `knowledge_assets` follows links.

- [ ] **Step 3: Implement normalized destination and no-follow writes**

```python
class SafeWriteStatus(StrEnum):
    WRITTEN = "written"
    UNSAFE = "unsafe"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SafeWriteResult:
    status: SafeWriteStatus
    path: str
    size: int
    error: str = ""
```

Reject POSIX/UNC/drive absolutes before stripping separators. Validate each created parent with `realpath`; use `os.open(..., O_NOFOLLOW | O_CREAT | O_TRUNC | O_WRONLY, 0o600)` when available and reject `os.path.islink(dest)` otherwise.

- [ ] **Step 4: Route all user-controlled names through the writer**

Replace direct writes for archive names, resource bodies, anonymous blocks, script names, and object/category output. Fixed internal report names may use `write_text_safely` for one consistent manifest path.

Add integration cases for archive names, resource bodies, anonymous blocks,
script names, and object/category-derived names using parent traversal, absolute
paths, destination symlinks, and nested directory symlinks. A helper-only test
does not satisfy this step.

- [ ] **Step 5: Run all export tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_safe_output.py tests/test_export_safety.py tests/test_batch_extraction_gaps.py tests/test_knowledge_pack.py -q -p no:cacheprovider`

Expected: PASS; no path outside a temporary output root is created.

- [ ] **Step 6: Commit the output task**

```bash
git add w3xtool/safe_output.py w3xtool/archive_export_paths.py w3xtool/archive_export.py w3xtool/knowledge_io.py w3xtool/knowledge_assets.py w3xtool/knowledge_unknown_exports.py w3xtool/knowledge_object_exports.py w3xtool/knowledge_script_exports.py tests/test_export_safety.py tests/test_safe_output.py
git commit -m "fix: contain all extraction outputs"
```

### Task 6: Archive Diagnostics and CLI Workflows

**Files:**
- Create: `w3xtool/archive_diagnostics.py`
- Create: `w3xtool/cli_options.py`
- Modify: `w3xtool/extraction_completeness.py`
- Modify: `w3xtool/gui_loader_runner.py`
- Modify: `main.py`
- Create: `tests/test_archive_diagnostics.py`
- Create: `tests/test_cli_options.py`
- Modify: `tests/test_cli_audit.py`

**Interfaces:**
- Produces: `ArchiveOpenDiagnosis(kind, message, evidence)` and `diagnose_archive_open(path: str, error: BaseException | None = None) -> ArchiveOpenDiagnosis`.
- Produces: `CliOptions`, `parse_cli_options(argv: Sequence[str]) -> CliOptions`, and `run_cli(options: CliOptions) -> int`.
- Consumes: `MapLoadContext`, `write_knowledge_pack`, and external/game-data source loaders.

- [ ] **Step 1: Write diagnostic and exit-code red tests**

```python
def test_hash_table_overflow_is_reported_as_structure_damage(tmp_path: Path) -> None:
    path = write_mpq_with_hash_table_past_eof(tmp_path)

    diagnosis = diagnose_archive_open(str(path))

    assert diagnosis.kind is ArchiveDiagnosisKind.TABLE_DAMAGE
    assert "hash" in " ".join(diagnosis.evidence).lower()


def test_cli_parse_failure_returns_nonzero(capsys) -> None:
    code = run_cli(CliOptions(map_path="missing.w3x"))

    assert code != 0
    assert "无法解析地图" in capsys.readouterr().err
```

- [ ] **Step 2: Run diagnostics/CLI tests and confirm failure**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_archive_diagnostics.py tests/test_cli_options.py -q -p no:cacheprovider`

Expected: FAIL because typed diagnostics and return codes do not exist.

- [ ] **Step 3: Implement bounded read-only archive diagnosis**

```python
class ArchiveDiagnosisKind(StrEnum):
    MISSING = "missing"
    PERMISSION = "permission"
    READ_ERROR = "read_error"
    NO_HEADER = "no_header"
    TABLE_DAMAGE = "table_damage"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ArchiveOpenDiagnosis:
    kind: ArchiveDiagnosisKind
    message: str
    evidence: tuple[str, ...]
```

Do not construct `MPQArchive` inside this helper: that path can mmap/copy the
whole file and mask the original permission error. Probe the original file with
bounded reads, scan 512-byte-aligned header candidates within at most 16 MiB,
and preserve the existing multiple-candidate behavior (an invalid candidate at
512 must not hide a valid one at 1024). A truncated `MPQ\x1a` candidate is
`TABLE_DAMAGE`; no candidate is `NO_HEADER`; a structurally valid nonzero MPQ
format version is `UNSUPPORTED`. Keep the existing compatibility rule that a
block-table start past EOF is damage, but a declared block-table *end* past EOF
is tolerated. Do not scan/decode payloads or unknown appended data.

`PROBABLE_PROTECTION` is not an archive-open outcome. It remains in
`ExtractionCompletenessReport` only after an archive opened successfully and
the existing thresholds are met (`encrypted_raw >= 8` and
`raw_fallback / block_count >= 0.25`).

- [ ] **Step 4: Implement compatible CLI options**

Support:

```text
uv run main.py cli <map> [--listfile FILE] [--game-data DIR] [--pack DIR]
```

`main()` must `raise SystemExit(run_cli(...))` for CLI paths while GUI launch behavior remains unchanged. Errors go to stderr and return `2`; successful summaries and packs return `0`.

- [ ] **Step 5: Wire GUI error text and completeness reports**

The loader boundary converts archive failures to `ArchiveOpenDiagnosis.message`. Openable archives retain block-level completeness; unopened archives show header/table diagnosis without claiming recovery.

- [ ] **Step 6: Run CLI, loader, and diagnostic tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_archive_diagnostics.py tests/test_cli_options.py tests/test_cli_audit.py tests/test_gui_loader.py tests/test_extraction_completeness.py -q -p no:cacheprovider`

Expected: PASS with stable nonzero errors.

- [ ] **Step 7: Commit the diagnostics task**

```bash
git add w3xtool/archive_diagnostics.py w3xtool/cli_options.py w3xtool/extraction_completeness.py w3xtool/gui_loader_runner.py main.py tests/test_archive_diagnostics.py tests/test_cli_options.py tests/test_cli_audit.py
git commit -m "feat: diagnose archive open failures"
```

### Task 7: Windows CascLib Backend and Packaging

**Files:**
- Create: `w3xtool/casclib_api.py`
- Create: `w3xtool/casclib_source.py`
- Modify: `w3xtool/game_data_source.py`
- Create: `third_party/CascLib/README.md`
- Create: `third_party/CascLib/LICENSE`
- Create: `third_party/CascLib/SOURCE_PROVENANCE.json`
- Create: `tools/build_casclib.ps1`
- Modify: `魔兽地图提取器.spec`
- Modify: `w3xtool/dist_build.py`
- Create: `tests/test_casclib_source.py`
- Create: `tests/test_casclib_windows_integration.py`
- Modify: `tests/test_game_data_source.py`
- Modify: `tests/test_dist_build.py`

**Interfaces:**
- Produces: `CascLibApi` protocol and `CtypesCascLibApi` implementation.
- Produces: `CascLibDataSource(root: str, api: CascLibApi | None = None)` implementing `GameDataSource` and `close()`.
- Changes: `probe_game_data_path` returns backend and detailed unreadable reason.

- [ ] **Step 1: Write fake-native API contract tests**

```python
def test_casclib_source_reads_internal_file_and_closes_handles() -> None:
    api = FakeCascLibApi({"UI\\TriggerData.txt": b"[TriggerActions]\n"})

    with CascLibDataSource("C:/Warcraft III", api=api) as source:
        assert source.has_file("UI/TriggerData.txt")
        assert source.read_file("UI\\TriggerData.txt").startswith(b"[")

    assert api.open_handles == set()


def test_native_probe_prefers_casclib_without_path_map(monkeypatch) -> None:
    monkeypatch.setattr("w3xtool.casclib_source.casclib_available", lambda: True)
    probe = probe_game_data_path(native_install_fixture())
    assert probe.backend == "casclib"
    assert probe.is_readable
```

Also test missing DLL, wrong architecture/load failure, `CascOpenStorage`
failure, one-file read failure, and path-map fallback without weakening the
base directory source.

- [ ] **Step 2: Run CascLib tests and confirm missing adapter**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_casclib_source.py tests/test_game_data_source.py -q -p no:cacheprovider`

Expected: FAIL because the API and source do not exist.

- [ ] **Step 3: Implement the typed ctypes boundary**

```python
class CascLibApi(Protocol):
    def open_storage(self, path: str) -> int: ...
    def close_storage(self, handle: int) -> None: ...
    def open_file(self, storage: int, name: str) -> int: ...
    def file_size(self, handle: int) -> int: ...
    def read_file(self, handle: int, size: int) -> bytes: ...
    def close_file(self, handle: int) -> None: ...
```

Build with `CASC_UNICODE=ON`: bind `CascOpenStorage` with a wide local path,
while `CascOpenFile(..., CASC_OPEN_BY_NAME, ...)` still receives a NUL-terminated
narrow internal filename. Bind `CascOpenStorage`, `CascCloseStorage`,
`CascOpenFile`, `CascGetFileSize64`, `CascReadFile`, `CascCloseFile`, and
`GetCascError` with explicit `argtypes/restype`; CascLib's success return type is
C++ `bool` (`ctypes.c_bool`), not Win32 `BOOL`. Always pass a real `DWORD*` to
`CascReadFile`, distinguish `ERROR_FILE_NOT_FOUND` at open time from native read
failure, and reject files above the archive resource size ceiling.

- [ ] **Step 4: Add pinned MIT build and provenance**

Pin tag `3.0` to commit `4971d363e665551ac4142f541e5f2d71f1cda653`.
`tools/build_casclib.ps1` downloads
`https://codeload.github.com/ladislav-zezula/CascLib/tar.gz/4971d363e665551ac4142f541e5f2d71f1cda653`,
verifies SHA256
`6b40739449d12f9c55b0acca7c40cba591ac0bdd10f485d58fafcb164021021e`,
builds x64 Release with CMake/Visual Studio, copies `CascLib.dll` into
`third_party/CascLib/bin/win-x64/`, and writes the produced DLL SHA256 beside it
as `CascLib.dll.sha256`. `SOURCE_PROVENANCE.json` records the immutable upstream
URL, tag, commit, source hash, and license. The DLL and generated hash are local
Windows build artifacts and are not committed. The CMake configuration includes
`-DCASC_UNICODE=ON -DCASC_BUILD_SHARED_LIB=ON -DCASC_BUILD_STATIC_LIB=OFF
-DCASC_BUILD_TESTS=OFF`. Do not download during startup.

- [ ] **Step 5: Package the DLL conditionally**

The PyInstaller spec adds the DLL only on Windows and fails the Windows dist
build when the DLL or matching generated hash is missing, the hash mismatches,
or the binary is not x64 PE. Non-Windows tests and builds do not require it.

- [ ] **Step 6: Add opt-in real Windows integration**

```python
@unittest.skipUnless(sys.platform == "win32" and os.getenv("W3XRAY_WAR3_DIR"), "需要 Windows Warcraft III CASC 安装")
def test_real_install_reads_trigger_schema_and_icon() -> None:
    with CascLibDataSource(os.environ["W3XRAY_WAR3_DIR"]) as source:
        assert source.read_file("UI/TriggerData.txt")
        assert source.read_file("UI/TriggerStrings.txt")
        assert source.read_file("ReplaceableTextures/CommandButtons/BTNSelectHeroOn.blp")
```

- [ ] **Step 7: Run cross-platform CascLib and packaging tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_casclib_source.py tests/test_casclib_windows_integration.py tests/test_game_data_source.py tests/test_dist_build.py -q -p no:cacheprovider`

Expected on macOS: fake API and packaging tests PASS; real Windows integration SKIP with the exact environment reason.

- [ ] **Step 8: Commit the CascLib task**

```bash
git add w3xtool/casclib_api.py w3xtool/casclib_source.py w3xtool/game_data_source.py third_party/CascLib tools/build_casclib.ps1 魔兽地图提取器.spec w3xtool/dist_build.py tests/test_casclib_source.py tests/test_casclib_windows_integration.py tests/test_game_data_source.py tests/test_dist_build.py
git commit -m "feat: read native CASC through CascLib"
```

### Task 8: Integration, Documentation, and Release Gate

**Files:**
- Modify: `tests/fixtures/maps/README.md`
- Modify: `README.md`
- Modify: `docs/KKWE借鉴清单.md`
- Modify: `progress.md`
- Modify: `findings.md`
- Modify: `w3xtool/knowledge_manifest.py`
- Modify: relevant tests when user-visible filenames or tab labels change

**Interfaces:**
- Consumes all prior tasks.
- Produces truthful user-facing capability statements and one final verification record.

- [ ] **Step 1: Add an end-to-end pack scenario**

```python
def test_real_format_trigger_listfile_pack_workflow(tmp_path: Path) -> None:
    md = load_real_fixture_map_with_schema_and_listfile(
        MAP_FIXTURE,
        trigger_data_dir=TRIGGER_FIXTURE_DIR,
    )
    before = tuple(md.all_files)

    written = write_knowledge_pack(md, str(tmp_path / "pack"))

    assert written > 0
    assert tuple(md.all_files) == before
    assert "本地化" in (tmp_path / "pack" / "触发器ECA.tsv").read_text(encoding="utf-8")
    assert "部分提取" in (tmp_path / "pack" / "需求覆盖.tsv").read_text(encoding="utf-8")
```

- [ ] **Step 2: Update documentation to exact capability boundaries**

Document separately:

```text
WTG headers: works without game data
WTG ECA: requires a matching TriggerData schema
Localized ECA text: requires TriggerStrings
Native CASC: CascLib on Windows; directory/path-map fallbacks elsewhere
Protected maps: diagnosis and raw preservation only
```

Remove stale “WTG ECA unavailable” and “CASC entirely unsupported” statements, and do not mark Windows integration complete without its recorded evidence.

- [ ] **Step 3: Run formatting and source-size checks**

Run:

```bash
git diff --check
for f in $(git diff --name-only HEAD~8 -- '*.py'); do awk '!/^[[:space:]]*$/ && !/^[[:space:]]*#/' "$f" | wc -l; done
```

Expected: no whitespace errors; every new/expanded module at or below 250 pure LOC. Existing oversized modules must have net deletions or be split before final commit.

- [ ] **Step 4: Run the complete automated suite**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -q -p no:cacheprovider -rs`

Expected: zero failures; only explicitly external real-game/Windows tests may skip with named prerequisites.

- [ ] **Step 5: Run GUI and CLI smoke checks**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_gui_trigger_eca.py tests/test_gui_layout.py tests/test_cli_options.py -q -p no:cacheprovider
uv run main.py cli tests/fixtures/maps/war3net-map-script-builder.w3x --game-data tests/fixtures/trigger --pack "${TMPDIR:-/tmp}/w3xray-final-pack"
```

Expected: GUI tests PASS; CLI exits 0 and writes ECA, dynamic coverage, listfile diagnostics, resources, and map identity reports.

- [ ] **Step 6: Run post-implementation review**

Use `review-work` with five independent lanes. Any failed lane blocks completion; fix findings and rerun affected verification before reporting.

- [ ] **Step 7: Commit final integration documentation**

```bash
git add README.md docs/KKWE借鉴清单.md progress.md findings.md w3xtool/knowledge_manifest.py tests
git commit -m "docs: align extraction capability claims"
```

- [ ] **Step 8: Verify final repository state**

Run: `git status --short --branch && git log --oneline -10`

Expected: only the two pre-existing `.DS_Store` files remain untracked; implementation commits are ahead of `origin/local` until the user requests a push.

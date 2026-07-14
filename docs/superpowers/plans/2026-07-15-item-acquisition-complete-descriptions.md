# Item Acquisition and Complete Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one source-aware, lossless object-text index and one evidence-backed item-relation index that power object details, a searchable acquisition page, knowledge packs, and resumable batch TSV exports.

**Architecture:** Preserve every map/client/cache text candidate before `GameObject` compatibility materialization, resolve it into immutable records, and attach an immutable text index to `MapData`. Preserve nested DOO drops, then combine placement, object-field, recipe, script, and WTG evidence into one immutable relation index; all GUI and export surfaces query these two indexes rather than rescanning maps.

**Tech Stack:** Python 3.14, frozen dataclasses and `StrEnum`, CustomTkinter/ttk, existing MPQ/SLK/WTG parsers, pytest, Ruff, basedpyright, existing safe TSV and atomic publication helpers.

## Global Constraints

- Source maps under `/Users/zhongerbing/Desktop/Maps` are read-only; never execute map scripts, historical EXEs, DLLs, or payloads.
- Preserve every existing dirty-worktree change. Never use `git add .`; stage only new files or individually reviewed hunks.
- Every available source string must round-trip exactly in the raw TSV column; readable text is stored separately and never replaces raw text.
- Resolve text in this exact order: current map named binary/text/SLK/WTS evidence, verified current-map anonymous text blocks, current Warcraft client data, then a unique validated base-object cache. A named-map conflict is never resolved by archive order.
- A zero-length named-map value blocks every lower tier; fixed placeholders remain evidence but permit lower-tier fill. Never use another map's custom-object text as cache evidence.
- GUI text, clipboard text, and TSV values have no character limit and use no preview slicing or ellipsis.
- Missing, unavailable, conflicting, inferred, and unresolved evidence must remain explicit; never invent names, descriptions, drop chances, coordinates, or event links.
- Keep existing public `GameObject`, `MapData` positional construction, flat `Doodad.drops`, `recipes_from_map`, and current report files compatible.
- Do not add runtime dependencies.
- Each task follows red-green-refactor: add a focused failing test, observe the expected failure, implement the minimum complete behavior, rerun focused tests, then review the exact staged diff.

---

## File Structure

### New production modules

- `w3xtool/object_text_models.py` — immutable text states, rows, index, and query/count methods.
- `w3xtool/object_text_roles.py` — deterministic field-key/label to semantic-role and level mapping.
- `w3xtool/object_text_index.py` — map/client/cache evidence resolution and conflict handling.
- `w3xtool/description_cache.py` — owned batch-output cache discovery, validation, parsing, and TSV formatting.
- `w3xtool/object_text_exports.py` — complete-description TSV and completeness text.
- `w3xtool/item_relation_models.py` — relation enums, immutable endpoints/evidence/records, stable IDs, and reverse indexes.
- `w3xtool/item_relation_builder.py` — DOO, placement, shop, recipe, and item-skill relation builders.
- `w3xtool/item_relation_scripts.py` — script-call/trigger/WTG reward evidence extraction.
- `w3xtool/item_relation_exports.py` — acquisition, equipment-skill, and completeness reports.
- `w3xtool/gui_item_relations.py` — relation-tab layout, filtering, evidence details, and object navigation.

### New focused tests

- `tests/test_object_text_roles.py`
- `tests/test_object_text_index.py`
- `tests/test_description_cache.py`
- `tests/test_item_relation_models.py`
- `tests/test_item_relations.py`
- `tests/test_item_relation_scripts.py`
- `tests/test_item_relation_exports.py`
- `tests/test_gui_item_relations.py`

### Existing files changed

- Object loading: `w3xtool/textobj.py`, `w3xtool/wts.py`, `w3xtool/object_text_sources.py`, `w3xtool/object_candidates.py`, `client_object_data.py`, `object_pipeline.py`, `load_context.py`, `map_data.py`, `map_loader.py`.
- Placement and recipes: `w3xtool/doo.py`, `script_scan.py`, `api.py`, `object_id_summary.py`, `knowledge_preplaced_exports.py`.
- Exports: `w3xtool/knowledge_pack_contents.py`, `knowledge_manifest.py`, `knowledge_requirements.py`, `knowledge_requirement_dynamic.py`, `knowledge_audit.py`.
- Batch: `w3xtool/batch_runner.py`, `batch_map_processing.py`, `batch_models.py`, `batch_state_io.py`, `batch_reports.py`, `batch_global_reports.py`.
- GUI: `w3xtool/object_detail_presentation.py`, `gui_object_detail.py`, `gui.py`, `gui_shell.py`, `gui_module_refresh.py`, `gui_loader.py`, `gui_loader_runner.py`, `gui_lifecycle.py`, `gui_external_data.py`, `gui_topbar.py`.
- Regression fixtures/tests: `tests/test_doo.py`, `test_client_object_data.py`, `test_object_pipeline.py`, `test_map_data_compat.py`, `test_map_reuse.py`, `test_batch_reports.py`, `test_batch_runner.py`, `test_batch_map_processing.py`, `test_knowledge_pack.py`, `test_knowledge_pack_manifest.py`, `test_gui_layout.py`, `tests/gui_base.py`.

---

### Task 1: Immutable complete-text models and semantic role classifier

**Files:**
- Create: `w3xtool/object_text_models.py`
- Create: `w3xtool/object_text_roles.py`
- Create: `tests/test_object_text_roles.py`

**Interfaces:**
- Produces: `ObjectTextState`, `ObjectTextRecord`, `ObjectTextIndex`, `empty_object_text_index()`.
- Produces: `TextRoleMatch` and `classify_text_field(category: str, key: str, label: str) -> TextRoleMatch | None`.

- [ ] **Step 1: Write failing role and immutable-index tests**

```python
from dataclasses import FrozenInstanceError

import pytest

from w3xtool.object_text_models import ObjectTextIndex, ObjectTextRecord, ObjectTextState
from w3xtool.object_text_roles import TextRoleMatch, classify_text_field


def test_roles_cover_all_requested_tooltip_variants_and_levels() -> None:
    assert classify_text_field("技能", "aret", "提示工具 - 学习") == TextRoleMatch("学习提示", None)
    assert classify_text_field("技能", "arut:3", "提示工具 - 学习 - 扩展的 (等级3)") == TextRoleMatch("学习扩展提示", 3)
    assert classify_text_field("技能", "aut1:2", "提示工具 - 关闭 (等级2)") == TextRoleMatch("关闭提示", 2)
    assert classify_text_field("单位", "AwakenTip", "提示工具 - 唤醒") == TextRoleMatch("唤醒提示", None)
    assert classify_text_field("物品", "ides", "描述") == TextRoleMatch("编辑器描述", None)


def test_text_index_is_immutable_and_queries_by_category_and_id() -> None:
    row = ObjectTextRecord(
        category="物品", object_id="I001", base_id="ratf", object_name="戒指",
        is_custom=True, role="扩展提示", field_key="utub", field_label="提示文本",
        level=None, raw_value="|cffffcc00全文|r|n第二行", readable_value="全文\n第二行",
        source_kind="地图", source_path="war3map.w3t", state=ObjectTextState.MAP_VALUE,
        placeholder=False, conflict_group="", evidence_ordinal=1,
    )
    index = ObjectTextIndex.build((row,))
    assert index.for_object("物品", "I001") == (row,)
    with pytest.raises(FrozenInstanceError):
        row.raw_value = "changed"
```

- [ ] **Step 2: Run the tests and verify import failure**

Run: `uv run python -m pytest -q tests/test_object_text_roles.py`
Expected: FAIL because `w3xtool.object_text_models` and `object_text_roles` do not exist.

- [ ] **Step 3: Implement the frozen records, mapping proxies, role table, and level parser**

```python
class ObjectTextState(StrEnum):
    MAP_VALUE = "地图原值"
    CLIENT_FILL = "客户端补全"
    CACHE_FILL = "可信缓存补全"
    MAP_EXPLICIT_EMPTY = "作者明确清空"
    AUTHOR_UNDEFINED = "作者未定义"
    SOURCE_UNAVAILABLE = "源数据不可用"
    SOURCE_CONFLICT = "来源冲突"


@dataclass(frozen=True, slots=True)
class ObjectTextRecord:
    category: str
    object_id: str
    base_id: str
    object_name: str
    is_custom: bool
    role: str
    field_key: str
    field_label: str
    level: int | None
    raw_value: str
    readable_value: str
    source_kind: str
    source_path: str
    state: ObjectTextState
    placeholder: bool
    conflict_group: str
    evidence_ordinal: int


@dataclass(frozen=True, slots=True)
class ObjectTextIndex:
    records: tuple[ObjectTextRecord, ...]
    _by_object: Mapping[tuple[str, str], tuple[ObjectTextRecord, ...]]

    @classmethod
    def build(cls, records: Iterable[ObjectTextRecord]) -> "ObjectTextIndex":
        ordered = tuple(sorted(records, key=object_text_sort_key))
        grouped: dict[tuple[str, str], list[ObjectTextRecord]] = {}
        for record in ordered:
            grouped.setdefault((record.category, record.object_id), []).append(record)
        frozen = MappingProxyType({key: tuple(value) for key, value in grouped.items()})
        return cls(ordered, frozen)

    def for_object(self, category: str, object_id: str) -> tuple[ObjectTextRecord, ...]:
        return self._by_object.get((category, object_id), ())
```

Implement `classify_text_field` with explicit case-insensitive key families for name, proper name, suffix, base/extended, learn/learn-extended, close/close-extended, buff, revive, awaken, and editor description. Parse only `:<decimal>` binary levels and recognized trailing numeric text/SLK keys; do not treat the `1` embedded in `atp1/aub1/aut1/auu1` as a level.

- [ ] **Step 4: Run focused tests**

Run: `uv run python -m pytest -q tests/test_object_text_roles.py`
Expected: PASS.

- [ ] **Step 5: Commit only the three new files**

```bash
git add -- w3xtool/object_text_models.py w3xtool/object_text_roles.py tests/test_object_text_roles.py
git diff --cached --check
git commit -m "feat: model complete object text evidence"
```

---

### Task 2: Trusted description cache and client evidence snapshot

**Files:**
- Create: `w3xtool/description_cache.py`
- Create: `tests/test_description_cache.py`
- Modify: `w3xtool/client_object_data.py`
- Modify: `tests/test_client_object_data.py`

**Interfaces:**
- Consumes: `TextRoleMatch` from Task 1.
- Produces: `DescriptionCacheEntry`, `DescriptionCache`, `build_description_cache_from_batch(root: Path)`, `load_description_cache(path: str | None)`, `format_description_cache_tsv(cache)`.
- Extends: `ClientBaseObject.evidence_fields: tuple[ObjectFieldValue, ...]` without changing its first three positional fields.
- Produces: `ClientObjectSnapshot(objects: tuple[ClientBaseObject, ...], text_available: bool)`.

- [ ] **Step 1: Add failing cache identity, conflict, ownership, and client-source tests**

```python
import csv
from pathlib import Path

from w3xtool.description_cache import build_description_cache_from_batch


def test_cache_accepts_only_owned_unique_client_fill_rows(tmp_path: Path) -> None:
    owned = tmp_path / "地图" / "001_map_deadbeef"
    owned.mkdir(parents=True)
    (owned / ".w3xray-batch-owned").write_text("d" * 64, encoding="ascii")
    with (owned / "对象描述.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("分类", "对象ID", "基础ID", "名称", "自定义", "等级",
                         "原始提示", "可读提示", "提示来源", "原始说明", "可读说明",
                         "说明来源", "完整性状态"))
        writer.writerow(("物品", "I001", "ratf", "戒指", "是", "", "提示", "提示",
                         "base:ratf", "完整说明", "完整说明", "base:ratf", "客户端补全"))
    cache = build_description_cache_from_batch(tmp_path)
    assert cache.lookup("物品", "ratf", "扩展提示", None)[0].raw_value == "完整说明"
    assert cache.conflict_count == 0


def test_cache_rejects_conflicting_values_for_the_same_exact_key(tmp_path: Path) -> None:
    # Create two independently owned result directories with different client-fill values.
    first = _write_owned_description(tmp_path, "001", "甲")
    second = _write_owned_description(tmp_path, "002", "乙")
    assert first.is_file() and second.is_file()
    cache = build_description_cache_from_batch(tmp_path)
    assert cache.lookup("物品", "ratf", "扩展提示", None) == ()
    assert cache.conflict_count == 1
```

Extend `tests/test_client_object_data.py` to assert `snapshot.text_available is True` when at least one required client text table can be read, `False` for `None`, and that `evidence_fields` retains key, value, source path, and source kind after the source closes.

- [ ] **Step 2: Run focused tests and verify missing APIs**

Run: `uv run python -m pytest -q tests/test_description_cache.py tests/test_client_object_data.py`
Expected: FAIL on missing cache module and snapshot attributes.

- [ ] **Step 3: Implement strict cache parsing and client evidence retention**

Use `csv.reader(..., delimiter="\t")`; accept only regular, non-symlink `对象描述.tsv` files whose sibling ownership marker is a 64-character lowercase/uppercase hexadecimal digest. Support both legacy 13-column rows and the new complete-text header. Normalize cache keys to `(category, base_id, role, level)`, retain source map digest/path, discard placeholders and non-`客户端补全` rows, and remove every key that has more than one distinct raw value.

```python
@dataclass(frozen=True, slots=True)
class ClientObjectSnapshot:
    objects: tuple[ClientBaseObject, ...]
    text_available: bool


def snapshot_client_base_objects(source: GameDataSource | None) -> ClientObjectSnapshot:
    if source is None:
        return ClientObjectSnapshot((), False)
    available = any(source.has_file(name) for name in _CLIENT_TEXT_NAMES)
    return ClientObjectSnapshot(collect_client_base_objects(source), available)
```

Build `ClientBaseObject.evidence_fields` directly from collected client candidates before `merge_object_candidates` removes losing aliases. Keep `fields` as the existing label/value compatibility tuple.

- [ ] **Step 4: Run focused tests and static checks**

Run: `uv run python -m pytest -q tests/test_description_cache.py tests/test_client_object_data.py tests/test_load_context_compat.py`
Expected: PASS.

Run: `uv run --with ruff ruff check w3xtool/description_cache.py w3xtool/client_object_data.py tests/test_description_cache.py tests/test_client_object_data.py`
Expected: PASS.

- [ ] **Step 5: Stage new files and only reviewed client-data hunks**

```bash
git add -- w3xtool/description_cache.py tests/test_description_cache.py
git add -p -- w3xtool/client_object_data.py tests/test_client_object_data.py
git diff --cached --check
git commit -m "feat: validate trusted description cache"
```

---

### Task 3: Resolve all map, client, and cache text into `MapData`

**Files:**
- Create: `w3xtool/object_text_index.py`
- Create: `tests/test_object_text_index.py`
- Modify: `w3xtool/textobj.py`
- Modify: `w3xtool/wts.py`
- Modify: `w3xtool/object_text_sources.py`
- Modify: `w3xtool/object_candidates.py`
- Modify: `w3xtool/object_pipeline.py`
- Modify: `w3xtool/load_context.py`
- Modify: `w3xtool/map_data.py`
- Modify: `w3xtool/map_loader.py`
- Modify: `tests/test_object_pipeline.py`
- Modify: `tests/test_wts.py`
- Modify: `tests/test_object_text_sources.py`
- Modify: `tests/test_object_candidate_collection.py`
- Modify: `tests/test_map_data_compat.py`

**Interfaces:**
- Consumes: Task 1 models/roles and Task 2 client/cache records.
- Produces: `build_object_text_index(objects, map_candidates, client_objects, cache, client_text_available) -> ObjectTextIndex`.
- Appends defaulted `value_source: str = ""` to `ObjectFieldValue`; a resolved WTS field records both its object-field source and `war3map.wts#STRING n` or `war3campaign.wts#STRING n`.
- Adds `ObjectSourceKind.TEXT_ANONYMOUS`; named binary/text/SLK/WTS evidence is one resolution tier and verified anonymous object blocks are the next tier.
- Adds at the end of `MapData`: `object_texts: ObjectTextIndex = field(default_factory=empty_object_text_index)`.
- Adds to `MapLoadContext`: `client_text_available: bool = False` and `description_cache: DescriptionCache = EMPTY_DESCRIPTION_CACHE`.

- [ ] **Step 1: Add failing resolution tests for every state and lossless long text**

```python
from w3xtool.object_text_index import build_object_text_index
from w3xtool.object_text_models import ObjectTextState


def test_resolution_preserves_all_roles_levels_placeholders_and_conflicts() -> None:
    long_raw = "|cffffcc00" + ("完整文本\t带引号\"\r\n" * 500) + "|r"
    candidates = (
        _candidate("A001", "AHbz", (
            _field("aret", "学习提示", "学习"),
            _field("arut:2", "未学习提示 (等级2)", long_raw),
            _field("aut1:2", "提示工具 - 关闭 (等级2)", "-"),
        )),
        _candidate("A001", "AHbz", (_field("arut:2", "未学习提示 (等级2)", "冲突值"),)),
    )
    index = build_object_text_index(
        (_object("技能", "A001", "AHbz"),), candidates, (), _empty_cache(),
        client_text_available=False,
    )
    rows = index.for_object("技能", "A001")
    assert {row.role for row in rows} >= {"学习提示", "学习扩展提示", "关闭提示"}
    assert all(row.raw_value in {long_raw, "冲突值"} for row in rows if row.role == "学习扩展提示")
    assert {row.state for row in rows if row.role == "学习扩展提示"} == {ObjectTextState.SOURCE_CONFLICT}
    assert next(row for row in rows if row.role == "关闭提示").state is ObjectTextState.SOURCE_UNAVAILABLE


def test_explicit_empty_blocks_fill_but_placeholder_allows_client_or_cache_fill() -> None:
    # Map empty expansion stays cleared; map '-' normal tip is retained as placeholder and client text fills it.
    index = build_object_text_index(
        (_object("物品", "I001", "ratf"),),
        (_candidate("I001", "ratf", (
            _field("utip", "工具提示", "-"),
            _field("utub", "提示文本", ""),
        )),),
        (_client("ratf", "物品", tip="客户端提示", description="客户端说明"),),
        _empty_cache(),
        client_text_available=True,
    )
    rows = index.for_object("物品", "I001")
    assert any(row.role == "基础提示" and row.state is ObjectTextState.CLIENT_FILL for row in rows)
    assert any(row.role == "扩展提示" and row.state is ObjectTextState.MAP_EXPLICIT_EMPTY for row in rows)
    assert not any(row.role == "扩展提示" and row.state is ObjectTextState.CLIENT_FILL for row in rows)


def test_named_map_sources_precede_anonymous_client_and_cache_without_cross_map_custom_fill() -> None:
    named = ObjectCandidate(
        "物品", "I001", "ratf", True, "w3t",
        (ObjectFieldValue("utub", "提示文本", "具名地图全文", "war3map.w3t", ObjectSourceKind.BINARY),),
        (),
    )
    anonymous = ObjectCandidate(
        "物品", "I001", "I001", True, "txt",
        (ObjectFieldValue("Ubertip", "提示文本", "匿名全文", "anonymous:block:000007", ObjectSourceKind.TEXT_ANONYMOUS),),
        (),
    )
    index = build_object_text_index(
        (GameObject("物品", "I001", "ratf", "戒指", True, "", "", (), (), (), ""),),
        (anonymous, named),
        (ClientBaseObject("物品", "ratf", "戒指", evidence_fields=(
            ObjectFieldValue("utub", "提示文本", "客户端全文", "Units/ItemStrings.txt", ObjectSourceKind.BASE),
        )),),
        DescriptionCache.build((DescriptionCacheEntry(
            "物品", "ratf", "扩展提示", None, "缓存全文", "缓存全文", "a" * 64, "owned.tsv",
        ),)),
        client_text_available=True,
    )
    row = next(record for record in index.for_object("物品", "I001") if record.role == "扩展提示")
    assert (row.raw_value, row.state, row.source_path) == (
        "具名地图全文", ObjectTextState.MAP_VALUE, "war3map.w3t",
    )


def test_text_rhs_and_wts_body_preserve_whitespace_line_endings_and_value_source() -> None:
    parsed = parse_text_objects("[I001]\r\nUbertip=  前导\t正文  \r\n")
    assert parsed[0][1]["Ubertip"] == "  前导\t正文  "
    wts = parse_wts(b"STRING 9\r\n{\r\n  first\r\nsecond\t  \r\n}\r\n")
    assert wts[9] == "  first\r\nsecond\t  "
    archive = FakeArchive({
        "war3map.w3t": _binary_object("ratf", "I001", (("utub", "TRIGSTR_9"),)),
    })
    candidate = collect_binary_object_candidates(archive, wts, "w3t")[0]
    field = next(value for value in candidate.fields if value.key == "utub")
    assert field.value == "  first\r\nsecond\t  "
    assert field.value_source == "war3map.wts#STRING 9"
```

- [ ] **Step 2: Run the new tests and verify missing builder/state failures**

Run: `uv run python -m pytest -q tests/test_object_text_index.py tests/test_object_pipeline.py tests/test_map_data_compat.py`
Expected: FAIL because no index builder or `MapData.object_texts` exists.

- [ ] **Step 3: Implement deterministic evidence resolution**

Group map evidence by `(category, object_id, role, level)` and client/cache evidence by the target object's `base_id`. Split map evidence into named and anonymous tiers before resolving. Deduplicate byte-for-byte equal evidence, preserve all differing values within the first usable tier with one stable conflict-group hash, and emit synthetic empty rows only for expected category roles that have no evidence. Apply the exact precedence and placeholder rules from the design. Cache lookup is by base ID only and rejects entries whose published object ID was custom or did not equal its proven base ID.

```python
def _resolved_state(
    named_map_values: tuple[_Evidence, ...],
    anonymous_map_values: tuple[_Evidence, ...],
    client_values: tuple[_Evidence, ...],
    cache_values: tuple[_Evidence, ...],
    client_text_available: bool,
) -> tuple[ObjectTextState, tuple[_Evidence, ...]]:
    explicit_empty = tuple(item for item in named_map_values if item.raw_value == "")
    if explicit_empty:
        return ObjectTextState.MAP_EXPLICIT_EMPTY, explicit_empty
    usable_map = _usable_unique(named_map_values)
    if len({item.raw_value for item in usable_map}) > 1:
        return ObjectTextState.SOURCE_CONFLICT, usable_map
    if usable_map:
        return ObjectTextState.MAP_VALUE, usable_map
    usable_anonymous = _usable_unique(anonymous_map_values)
    if len({item.raw_value for item in usable_anonymous}) > 1:
        return ObjectTextState.SOURCE_CONFLICT, usable_anonymous
    if usable_anonymous:
        return ObjectTextState.MAP_VALUE, usable_anonymous
    usable_client = _usable_unique(client_values)
    if len({item.raw_value for item in usable_client}) > 1:
        return ObjectTextState.SOURCE_CONFLICT, usable_client
    if usable_client:
        return ObjectTextState.CLIENT_FILL, usable_client
    usable_cache = _usable_unique(cache_values)
    if usable_cache:
        return ObjectTextState.CACHE_FILL, usable_cache
    state = ObjectTextState.AUTHOR_UNDEFINED if client_text_available else ObjectTextState.SOURCE_UNAVAILABLE
    return state, ()
```

Remove the `if value` filters only where they currently discard explicitly present object text fields. `parse_text_objects` preserves the RHS exactly after the first `=`, including leading/trailing spaces and tabs; section/control syntax may be normalized but field values may not. `parse_wts` removes only the structural newline immediately after `{` and immediately before `}`, preserving all internal bytes after per-entry decoding, including CRLF versus LF. Record WTS provenance separately from the object-field source. Call `build_object_text_index` from `populate_object_pipeline` after final objects are materialized, using the original map candidates and the immutable client/cache snapshots. Keep old callers valid through keyword defaults.

- [ ] **Step 4: Run object-loading regressions**

Run: `uv run python -m pytest -q tests/test_object_text_index.py tests/test_object_pipeline.py tests/test_object_text_sources.py tests/test_object_candidate_collection.py tests/test_wts.py tests/test_client_object_data.py tests/test_map_data_compat.py`
Expected: PASS.

- [ ] **Step 5: Commit reviewed task hunks**

```bash
git add -- w3xtool/object_text_index.py tests/test_object_text_index.py
git add -p -- w3xtool/textobj.py w3xtool/wts.py w3xtool/object_text_sources.py w3xtool/object_candidates.py w3xtool/object_pipeline.py w3xtool/load_context.py w3xtool/map_data.py w3xtool/map_loader.py tests/test_wts.py tests/test_object_text_sources.py tests/test_object_candidate_collection.py tests/test_object_pipeline.py tests/test_map_data_compat.py
git diff --cached --check
git commit -m "feat: retain complete object text evidence"
```

---

### Task 4: Preserve nested unit and destructable drop sets

**Files:**
- Modify: `w3xtool/doo.py`
- Modify: `tests/test_doo.py`
- Modify: `w3xtool/object_id_summary.py`
- Modify: `w3xtool/knowledge_preplaced_exports.py`
- Modify: `tests/test_knowledge_pack_preplaced.py`

**Interfaces:**
- Produces: `DropEntry(item_id, chance, group_index, entry_index, source_offset)` and `DropSet(group_index, entries)`.
- Appends `drop_sets: tuple[DropSet, ...]` and `source_offset: int` to `Unit` and `Doodad`.
- Keeps `Doodad.drops` as the flattened compatibility list and adds `Unit.drops` as the same read-only flattened property.

- [ ] **Step 1: Extend fixtures and add failing nested-drop assertions**

```python
def test_doodad_preserves_multiple_drop_sets_without_losing_flat_compatibility() -> None:
    data = _build_doo([_doodad_with_sets(
        "D001", [[("I001", 70), ("I002", 30)], [("I003", 100)]], serial=9,
    )])
    (doodad,) = parse_doodads(data)
    assert [[(row.item_id, row.chance) for row in group.entries] for group in doodad.drop_sets] == [
        [("I001", 70), ("I002", 30)],
        [("I003", 100)],
    ]
    assert doodad.drops == [("I001", 70), ("I002", 30), ("I003", 100)]


def test_unit_retains_dropped_item_sets_that_were_previously_discarded() -> None:
    unit = _unit("n001", 0, (1, 2, 0), 0, (1, 1, 1), 2, 12, -1, -1,
                 0, -1, 1, [], [], 77,
                 dropsets=[[("I001", 50)], [("I002", 25), ("I003", 75)]])
    (parsed,) = parse_units(_build_units([unit]))
    assert parsed.drops == [("I001", 50), ("I002", 25), ("I003", 75)]
    assert [group.group_index for group in parsed.drop_sets] == [0, 1]
    assert all(entry.source_offset > parsed.source_offset for group in parsed.drop_sets for entry in group.entries)
```

- [ ] **Step 2: Run DOO tests and verify missing attributes**

Run: `uv run python -m pytest -q tests/test_doo.py tests/test_knowledge_pack_preplaced.py tests/test_object_id_summary.py`
Expected: FAIL on missing `drop_sets`/unit drops.

- [ ] **Step 3: Parse one shared nested representation and derive flat views**

Capture `record_offset = r.p` at the beginning of each placement and `source_offset = r.p` before each item tag. Return tuples from a `_read_drop_sets` helper used by both parsers. Populate the legacy doodad `drops` list from `DropSet.entries` and update preplaced reports to display `组1[...]；组2[...]` while retaining item IDs and probabilities.

- [ ] **Step 4: Run placement regressions**

Run: `uv run python -m pytest -q tests/test_doo.py tests/test_knowledge_pack_preplaced.py tests/test_object_id_summary.py tests/test_investigation_exports.py`
Expected: PASS.

- [ ] **Step 5: Commit reviewed placement hunks**

```bash
git add -p -- w3xtool/doo.py w3xtool/object_id_summary.py w3xtool/knowledge_preplaced_exports.py tests/test_doo.py tests/test_knowledge_pack_preplaced.py
git diff --cached --check
git commit -m "fix: preserve nested placement drop sets"
```

---

### Task 5: Relation models and structural acquisition builders

**Files:**
- Create: `w3xtool/item_relation_models.py`
- Create: `w3xtool/item_relation_builder.py`
- Create: `tests/test_item_relation_models.py`
- Create: `tests/test_item_relations.py`

**Interfaces:**
- Produces enums `ItemRelationKind`, `RelationConfidence`, `RelationCompleteness`.
- Produces records `RelationObject`, `RelationIngredient`, `RelationEvidence`, `ItemRelation`.
- Produces `ItemRelationIndex.build(records)` and queries `for_item`, `for_source`, `for_skill`.
- Produces `build_structural_item_relations(md: MapData) -> tuple[ItemRelation, ...]` for DOO, shop, placement, and equipment-skill evidence.

- [ ] **Step 1: Add failing stable-ID, reverse-index, and structural relation tests**

```python
def test_relation_id_is_stable_but_distinct_per_instance_and_drop_group() -> None:
    first = _drop_relation(serial=10, group=0, entry=0)
    same = _drop_relation(serial=10, group=0, entry=0)
    other_group = _drop_relation(serial=10, group=1, entry=0)
    assert first.relation_id == same.relation_id
    assert first.relation_id != other_group.relation_id
    index = ItemRelationIndex.build((first, same, other_group))
    assert index.records == (first, other_group)
    assert index.for_item("I001") == (first, other_group)


def test_structural_builder_emits_drop_shop_placement_inventory_and_skill_relations() -> None:
    md = _map_with_items_units_shops_and_placements()
    records = build_structural_item_relations(md)
    assert {row.kind for row in records} >= {
        ItemRelationKind.UNIT_DROP,
        ItemRelationKind.DESTRUCTABLE_DROP,
        ItemRelationKind.SHOP_SELL,
        ItemRelationKind.SHOP_MAKE,
        ItemRelationKind.GROUND_PLACEMENT,
        ItemRelationKind.PREPLACED_INVENTORY,
        ItemRelationKind.ITEM_ABILITY,
        ItemRelationKind.COOLDOWN_ABILITY,
    }
    shop_rows = [row for row in records if row.kind is ItemRelationKind.SHOP_SELL]
    assert {(row.instance_serial, row.player, row.x, row.y) for row in shop_rows} == {
        (41, 11, 128.0, -64.0),
        (42, 12, 256.0, -32.0),
    }
```

- [ ] **Step 2: Run the tests and verify missing modules**

Run: `uv run python -m pytest -q tests/test_item_relation_models.py tests/test_item_relations.py`
Expected: FAIL because relation modules do not exist.

- [ ] **Step 3: Implement immutable records, SHA-256 identity, and structural builders**

Use a canonical UTF-8 JSON array of all semantic/evidence fields for `relation_id`; never use Python's randomized `hash()`. Resolve endpoint names from `md.obj_index`, then `BASE_NAMES`, otherwise the literal `未解析` with `RelationCompleteness.UNRESOLVED`. Build:

- one row per unit/destructable drop entry and group;
- one row per shop field and preplaced shop instance, or one type-level row with no coordinates;
- one ground-placement row when a top-level `Unit.type_id` resolves to category `物品`;
- one inventory row per slot;
- one `abilList` and `cooldownID` row per item reference.

```python
@dataclass(frozen=True, slots=True)
class ItemRelationIndex:
    records: tuple[ItemRelation, ...]
    _by_item: Mapping[str, tuple[ItemRelation, ...]]
    _by_source: Mapping[str, tuple[ItemRelation, ...]]
    _by_skill: Mapping[str, tuple[ItemRelation, ...]]

    @classmethod
    def build(cls, records: Iterable[ItemRelation]) -> "ItemRelationIndex":
        unique = {record.relation_id: record for record in records}
        ordered = tuple(sorted(unique.values(), key=item_relation_sort_key))
        return cls(
            ordered,
            _frozen_group(ordered, lambda row: row.item.object_id),
            _frozen_group(ordered, lambda row: row.source.object_id if row.source else ""),
            _frozen_group(ordered, lambda row: row.skill.object_id if row.skill else ""),
        )
```

- [ ] **Step 4: Run focused model/builder tests**

Run: `uv run python -m pytest -q tests/test_item_relation_models.py tests/test_item_relations.py tests/test_references.py tests/test_doo.py`
Expected: PASS.

- [ ] **Step 5: Commit the four new files**

```bash
git add -- w3xtool/item_relation_models.py w3xtool/item_relation_builder.py tests/test_item_relation_models.py tests/test_item_relations.py
git diff --cached --check
git commit -m "feat: index structural item acquisition relations"
```

---

### Task 6: Evidence-bearing recipes without breaking the legacy recipe view

**Files:**
- Modify: `w3xtool/script_scan.py`
- Modify: `w3xtool/api.py`
- Modify: `tests/test_map_reuse.py`
- Modify: `tests/test_recipe_scroll.py`
- Create: `tests/test_recipe_evidence.py`

**Interfaces:**
- Extends `Recipe` after its existing first three fields with `source: str = ""`, `line: int = 0`, `confidence: str = "已确认"`, `evidence: str = ""`.
- Changes `scan_recipes(script: str, *, source: str = "") -> list[Recipe]`.
- `recipes_from_map` retains different source/line evidence rows; legacy callers still read `ingredients/result/func`.

- [ ] **Step 1: Add failing source, function, line, quantity, and comment-noise tests**

```python
def test_recipe_evidence_keeps_source_function_result_line_and_duplicate_material_counts() -> None:
    script = "\n".join((
        "function Forge takes nothing returns nothing",
        "    call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))",
        "    call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))",
        "    call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I002'))",
        "    call UnitAddItemById(u, 'I999')",
        "endfunction",
    ))
    (recipe,) = scan_recipes(script, source="war3map.j")
    assert recipe.ingredients == ["I001", "I001", "I002"]
    assert (recipe.result, recipe.func, recipe.source, recipe.line) == (
        "I999", "Forge", "war3map.j", 5,
    )
    assert "UnitAddItemById" in recipe.evidence


def test_recipe_scanner_ignores_calls_inside_comments_and_strings() -> None:
    script = "// call RemoveItem('I001')\ncall BJDebugMsg(\"CreateItem('I999')\")"
    assert scan_recipes(script, source="war3map.j") == []
```

- [ ] **Step 2: Run recipe tests and verify signature/evidence failures**

Run: `uv run python -m pytest -q tests/test_recipe_evidence.py tests/test_map_reuse.py tests/test_recipe_scroll.py`
Expected: FAIL because `Recipe` lacks source/line evidence.

- [ ] **Step 3: Add source-aware scanning on comment/string-masked code**

Scan `script_code_text(script)` for control decisions while using original lines for evidence text. Track the current JASS/Lua function and absolute line number; clear the material buffer after each result. Key deduplication by `(source, line, sorted ingredients, result)` rather than only ingredients/result. Keep standard same-function fixed-code recipes `已确认`; no speculative variable resolution is added.

- [ ] **Step 4: Run recipe/API/GUI regressions**

Run: `uv run python -m pytest -q tests/test_recipe_evidence.py tests/test_map_reuse.py tests/test_recipe_scroll.py tests/test_gui_layout.py`
Expected: PASS.

- [ ] **Step 5: Commit reviewed recipe hunks**

```bash
git add -- tests/test_recipe_evidence.py
git add -p -- w3xtool/script_scan.py w3xtool/api.py tests/test_map_reuse.py tests/test_recipe_scroll.py
git diff --cached --check
git commit -m "feat: retain recipe source evidence"
```

---

### Task 7: Script and WTG item reward evidence

**Files:**
- Create: `w3xtool/item_relation_scripts.py`
- Create: `tests/test_item_relation_scripts.py`
- Modify: `w3xtool/item_relation_builder.py`
- Modify: `tests/test_item_relations.py`

**Interfaces:**
- Consumes existing `ScriptCallArgumentIndex`, `ScriptTriggerRegistrationIndex`, `TriggerTreeSummary`, and Task 6 `Recipe`.
- Produces `build_script_item_relations(md: MapData) -> tuple[ItemRelation, ...]`.
- Extends `build_item_relation_index(md)` to combine structural, recipe, script, and WTG relations.

- [ ] **Step 1: Add failing JASS, Lua, trigger-context, WTG, and negative tests**

```python
def test_fixed_item_reward_calls_keep_recipient_location_function_and_line() -> None:
    md = MapData("x.w3x", "奖励图", scripts={
        "war3map.j": "\n".join((
            "function Reward takes nothing returns nothing",
            "    call UnitAddItemById(GetTriggerUnit(), 'I001')",
            "    call CreateItem('I002', 128.0, -64.0)",
            "endfunction",
        )),
    })
    rows = build_script_item_relations(md)
    assert {(row.item.object_id, row.evidence.source, row.evidence.line) for row in rows} == {
        ("I001", "war3map.j", 2),
        ("I002", "war3map.j", 3),
    }
    assert all(row.kind is ItemRelationKind.SCRIPT_REWARD for row in rows)
    assert all(row.confidence is RelationConfidence.CONFIRMED for row in rows)


def test_death_event_context_is_inferred_not_claimed_as_direct_monster_drop() -> None:
    md = _map_with_death_registration_and_reward_action()
    (row,) = build_script_item_relations(md)
    assert row.kind is ItemRelationKind.SCRIPT_REWARD
    assert row.confidence is RelationConfidence.INFERRED
    assert "EVENT_UNIT_DEATH" in row.evidence.raw


def test_wtg_fixed_item_parameter_keeps_trigger_ordinal_and_offset() -> None:
    md = _map_with_wtg_item_action("I777", trigger="奖励触发", ordinal=4, offset=0x120)
    (row,) = build_script_item_relations(md)
    assert row.item.object_id == "I777"
    assert row.evidence.trigger == "奖励触发"
    assert row.evidence.location == "ECA 4 @ 0x120"
```

Also assert that comments, player-facing strings, dynamic variables without a fixed rawcode, and `UnitAddItem(unit, itemHandle)` do not become confirmed relations; dynamic calls may emit only `仅线索` when a concrete item rawcode is present.

- [ ] **Step 2: Run focused tests and verify missing extractor**

Run: `uv run python -m pytest -q tests/test_item_relation_scripts.py tests/test_item_relations.py`
Expected: FAIL because `build_script_item_relations` does not exist.

- [ ] **Step 3: Implement bounded call signatures and conservative context joins**

Use an explicit argument-position table for `CreateItem`, `CreateItemLoc`, `UnitAddItemById`, `UnitAddItemByIdSwapped`, `UnitAddItemToSlotById`, `AddItemToStock`, and `AddItemToAllStock`. Accept exactly one static 4cc from the declared item argument. Join action handlers to registrations only by exact source/function/handle evidence; death context changes confidence to `可推断` but never changes kind to direct drop without a proven fixed source object.

Traverse WTG ECA functions recursively. Accept only enabled known item-action names with one fixed four-character item parameter. Preserve trigger, ordinal, branch, and `source_offset`.

- [ ] **Step 4: Run all script-index and relation tests**

Run: `uv run python -m pytest -q tests/test_item_relation_scripts.py tests/test_item_relations.py tests/test_script_call_argument_index.py tests/test_script_trigger_registration_index.py tests/test_trigger_exports.py`
Expected: PASS.

- [ ] **Step 5: Commit script relation files/hunks**

```bash
git add -- w3xtool/item_relation_scripts.py tests/test_item_relation_scripts.py
git add -p -- w3xtool/item_relation_builder.py tests/test_item_relations.py
git diff --cached --check
git commit -m "feat: index script and trigger item rewards"
```

---

### Task 8: Build both indexes once during map loading and expose compatibility APIs

**Files:**
- Modify: `w3xtool/map_data.py`
- Modify: `w3xtool/map_loader.py`
- Modify: `w3xtool/load_context.py`
- Modify: `w3xtool/gui_loader.py`
- Modify: `w3xtool/gui_loader_runner.py`
- Modify: `w3xtool/api.py`
- Modify: `tests/test_map_reuse.py`
- Create: `tests/test_map_relation_loading.py`

**Interfaces:**
- Adds at the end of `MapData`: `item_relations: ItemRelationIndex = field(default_factory=empty_item_relation_index)`.
- Extends `build_map_load_context(..., description_cache_path: str | None = None)`.
- `recipes_from_map` derives compatibility `Recipe` rows from indexed recipe relations when present and falls back to scanning manually constructed maps.

- [ ] **Step 1: Add failing single-build and context propagation tests**

```python
def test_map_loader_publishes_text_and_relation_indexes_before_return() -> None:
    archive = _archive_with_item_shop_and_preplaced_drop()
    context = MapLoadContext(client_text_available=False)
    md = _load_map_impl(archive, archive.path, 0, None, context)
    assert md.object_texts.records
    assert md.item_relations.records
    assert md.item_relations.for_item("I001")


def test_description_cache_path_reaches_background_map_context(tmp_path: Path) -> None:
    cache_path = tmp_path / "可信描述缓存.tsv"
    cache_path.write_text(_valid_cache_tsv(), encoding="utf-8")
    context = build_map_load_context(description_cache_path=str(cache_path))
    assert context.description_cache.lookup("物品", "ratf", "扩展提示", None)
```

- [ ] **Step 2: Run loader/API tests and verify empty indexes**

Run: `uv run python -m pytest -q tests/test_map_relation_loading.py tests/test_map_reuse.py tests/test_gui_loader.py tests/test_load_context_compat.py`
Expected: FAIL because loaders do not build/propagate the indexes.

- [ ] **Step 3: Integrate in deterministic load order**

Build object text immediately after object materialization. Build item relations after scripts, preplaced records, WTG, and the reference graph are available. Apply the same order recursively to campaign children. Pass `description_cache_path` through `load_path_payload`, `load_campaign_payload`, and background runner closures. Keep `_load_with_context` from dropping a context that contains only a cache or source-availability flag.

- [ ] **Step 4: Run map/campaign/GUI-loader regressions**

Run: `uv run python -m pytest -q tests/test_map_relation_loading.py tests/test_map_reuse.py tests/test_gui_loader.py tests/test_object_pipeline.py tests/test_campaign_budget.py tests/test_map_data_compat.py`
Expected: PASS.

- [ ] **Step 5: Commit only reviewed loader hunks**

```bash
git add -- tests/test_map_relation_loading.py
git add -p -- w3xtool/map_data.py w3xtool/map_loader.py w3xtool/load_context.py w3xtool/gui_loader.py w3xtool/gui_loader_runner.py w3xtool/api.py tests/test_map_reuse.py
git diff --cached --check
git commit -m "feat: build item intelligence during map load"
```

---

### Task 9: Lossless complete-text and relation TSV formatters

**Files:**
- Create: `w3xtool/object_text_exports.py`
- Create: `w3xtool/item_relation_exports.py`
- Create: `tests/test_item_relation_exports.py`
- Modify: `tests/test_batch_reports.py`

**Interfaces:**
- Produces `format_object_text_tsv(index)` and `format_object_text_completeness(index)`.
- Produces `format_item_acquisition_tsv(index)`, `format_equipment_skills_tsv(index)`, and `format_relation_completeness(index)`.
- Uses `batch_tsv.format_tsv_rows` for all raw multiline values.

- [ ] **Step 1: Add failing exact-header and TSV round-trip tests**

```python
import csv
import io


def test_complete_text_tsv_round_trips_tabs_newlines_quotes_and_long_values() -> None:
    raw = "\"开头\t字段\r\n" + ("长文本|n" * 2000)
    index = _text_index_with_raw_value(raw)
    rendered = format_object_text_tsv(index)
    rows = list(csv.reader(io.StringIO(rendered), delimiter="\t"))
    assert rows[0] == [
        "分类", "对象ID", "基础ID", "名称", "自定义", "文本角色", "字段键", "字段标签",
        "等级/变体", "原始全文", "可读全文", "来源类型", "来源路径", "状态", "占位",
        "冲突组", "证据序号",
    ]
    assert rows[1][9] == raw


def test_relation_exports_split_acquisition_and_equipment_skill_rows() -> None:
    index = ItemRelationIndex.build((_drop_relation(), _item_ability_relation()))
    acquisition = list(csv.reader(io.StringIO(format_item_acquisition_tsv(index)), delimiter="\t"))
    skills = list(csv.reader(io.StringIO(format_equipment_skills_tsv(index)), delimiter="\t"))
    assert [row[2] for row in acquisition[1:]] == ["怪物直接掉落"]
    assert [row[3] for row in skills[1:]] == ["装备技能"]
    assert "证据行号/偏移" in acquisition[0]
    assert "未解析原因" in acquisition[0]
```

- [ ] **Step 2: Run export tests and verify missing formatters**

Run: `uv run python -m pytest -q tests/test_item_relation_exports.py tests/test_batch_reports.py`
Expected: FAIL because formatter modules do not exist.

- [ ] **Step 3: Implement the exact design headers and state summaries**

Serialize floats deterministically without changing their numeric value, ingredient IDs separately from human-readable name/count text, and evidence line/offset in one stable cell. Description completeness lists all seven states in enum order. Relation completeness lists every relation kind, confidence, completeness state, unavailable channel, and unresolved reason count.

- [ ] **Step 4: Run formatter and safety tests**

Run: `uv run python -m pytest -q tests/test_item_relation_exports.py tests/test_batch_reports.py tests/test_security_output_safety.py`
Expected: PASS.

- [ ] **Step 5: Commit formatter files**

```bash
git add -- w3xtool/object_text_exports.py w3xtool/item_relation_exports.py tests/test_item_relation_exports.py
git add -p -- tests/test_batch_reports.py
git diff --cached --check
git commit -m "feat: export complete item intelligence TSVs"
```

---

### Task 10: Publish complete descriptions and relations in knowledge packs

**Files:**
- Modify: `w3xtool/knowledge_pack_contents.py`
- Modify: `w3xtool/knowledge_manifest.py`
- Modify: `w3xtool/knowledge_requirements.py`
- Modify: `w3xtool/knowledge_requirement_dynamic.py`
- Modify: `w3xtool/knowledge_audit.py`
- Modify: `tests/test_knowledge_pack.py`
- Modify: `tests/test_knowledge_pack_manifest.py`
- Create: `tests/test_knowledge_pack_item_relations.py`

**Interfaces:**
- Writes `对象完整描述.tsv`, `掉落与获取关系.tsv`, `装备技能关系.tsv`, and `关系完整性.txt` from `MapData` indexes.
- Manifest and requirement coverage name these exact artifacts.

- [ ] **Step 1: Add failing knowledge-pack artifact and count tests**

```python
def test_pack_writes_complete_text_and_all_relation_artifacts(tmp_path: Path) -> None:
    md = _map_with_text_and_relations()
    write_knowledge_pack(md, str(tmp_path))
    expected = {
        "对象完整描述.tsv",
        "掉落与获取关系.tsv",
        "装备技能关系.tsv",
        "关系完整性.txt",
    }
    assert expected <= {path.name for path in tmp_path.iterdir()}
    assert "I001" in (tmp_path / "掉落与获取关系.tsv").read_text(encoding="utf-8")
    assert "A001" in (tmp_path / "装备技能关系.tsv").read_text(encoding="utf-8")
    assert "原始全文" in (tmp_path / "对象完整描述.tsv").read_text(encoding="utf-8")


def test_manifest_and_coverage_point_to_item_relation_outputs(tmp_path: Path) -> None:
    write_knowledge_pack(_map_with_text_and_relations(), str(tmp_path))
    manifest = (tmp_path / "资料包目录.tsv").read_text(encoding="utf-8")
    coverage = (tmp_path / "需求覆盖.tsv").read_text(encoding="utf-8")
    assert "装备关系\t掉落与获取关系.tsv" in manifest
    assert "分析装备掉落与获取\t已覆盖（静态证据）\t掉落与获取关系.tsv" in coverage
```

- [ ] **Step 2: Run pack tests and verify missing files**

Run: `uv run python -m pytest -q tests/test_knowledge_pack_item_relations.py tests/test_knowledge_pack.py tests/test_knowledge_pack_manifest.py`
Expected: FAIL because new artifacts are not written/listed.

- [ ] **Step 3: Wire formatter outputs and dynamic audit counts**

Write the four artifacts alongside existing object and preplaced reports. Add audit lines for total text records/states and relation records/confidence. Dynamic coverage reports `未发现数据` when the index is empty and `部分覆盖` when any relation is partial/unresolved or any text is unavailable/conflicting.

- [ ] **Step 4: Run all knowledge-pack tests**

Run: `uv run python -m pytest -q tests/test_knowledge_pack*.py tests/test_knowledge_results.py tests/test_static_extraction_workflow.py`
Expected: PASS.

- [ ] **Step 5: Commit reviewed pack hunks**

```bash
git add -- tests/test_knowledge_pack_item_relations.py
git add -p -- w3xtool/knowledge_pack_contents.py w3xtool/knowledge_manifest.py w3xtool/knowledge_requirements.py w3xtool/knowledge_requirement_dynamic.py w3xtool/knowledge_audit.py tests/test_knowledge_pack.py tests/test_knowledge_pack_manifest.py
git diff --cached --check
git commit -m "feat: publish item relations in knowledge packs"
```

---

### Task 11: Batch schema v2, trusted-cache reuse, and per-map relation reports

**Files:**
- Modify: `w3xtool/batch_models.py`
- Modify: `w3xtool/batch_state_io.py`
- Modify: `w3xtool/batch_runner.py`
- Modify: `w3xtool/batch_map_processing.py`
- Modify: `w3xtool/batch_reports.py`
- Modify: `w3xtool/batch_global_reports.py`
- Modify: `tests/test_batch_reports.py`
- Modify: `tests/test_batch_runner.py`
- Modify: `tests/test_batch_map_processing.py`
- Create: `tests/test_batch_description_cache.py`

**Interfaces:**
- Batch state schema becomes exactly `2`; schema 1 is deliberately non-reusable.
- Appends defaulted `relation_counts` and `relation_incomplete_count` to `MapBatchResult`.
- Required per-map reports add `掉落与获取关系.tsv`, `装备技能关系.tsv`, and `关系完整性.txt`.
- Global output adds `可信描述缓存.tsv`.

- [ ] **Step 1: Add failing schema/cache/report/resume tests**

```python
def test_schema_one_result_is_not_reused_after_relation_reports_become_required(tmp_path: Path) -> None:
    old = _schema_one_state_json()
    (tmp_path / "批量提取状态.json").write_text(old, encoding="utf-8")
    assert batch_runner._read_previous_state(str(tmp_path)) is None


def test_batch_builds_cache_before_processing_and_writes_all_new_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output"
    _write_legacy_owned_client_fill(output)
    seen_cache_sizes: list[int] = []
    def process(index, fingerprint, options, context):
        seen_cache_sizes.append(len(context.description_cache.entries))
        return _publish_fake_v2_result(index, fingerprint, options)
    monkeypatch.setattr(batch_runner, "process_one_map", process)
    state = run_batch(BatchOptions(str(_map_source(tmp_path)), str(output)))
    assert state.schema_version == 2
    assert seen_cache_sizes == [1]
    assert (output / "可信描述缓存.tsv").is_file()
```

Update `test_batch_map_processing.py` to assert the exact four description/relation files, parse their TSV with `csv.reader`, and confirm raw multiline text round-trips.

- [ ] **Step 2: Run batch tests and verify schema/report failures**

Run: `uv run python -m pytest -q tests/test_batch_description_cache.py tests/test_batch_reports.py tests/test_batch_runner.py tests/test_batch_map_processing.py`
Expected: FAIL because schema 2 and relation reports are absent.

- [ ] **Step 3: Implement v2 state and use already-built indexes**

At batch startup build/cache `DescriptionCache` from the owned output root, publish the cache TSV safely, then insert it into the immutable load context with `dataclasses.replace`. Aggregate text and relation records across root/campaign maps without rescanning scripts. Use new text states to derive map partial status: `作者未定义`, `源数据不可用`, or `来源冲突` make the result partial; `作者明确清空` does not.

Ensure `_published_result_exists` requires every new file and schema 2, so old complete directories are reprocessed.

- [ ] **Step 4: Run batch and end-to-end synthetic tests**

Run: `uv run python -m pytest -q tests/test_batch*.py tests/test_batch_e2e.py tests/test_static_extraction_workflow.py`
Expected: PASS.

- [ ] **Step 5: Commit reviewed batch hunks**

```bash
git add -- tests/test_batch_description_cache.py
git add -p -- w3xtool/batch_models.py w3xtool/batch_state_io.py w3xtool/batch_runner.py w3xtool/batch_map_processing.py w3xtool/batch_reports.py w3xtool/batch_global_reports.py tests/test_batch_reports.py tests/test_batch_runner.py tests/test_batch_map_processing.py
git diff --cached --check
git commit -m "feat: publish relation-aware batch schema"
```

---

### Task 12: Complete text and bidirectional relations in object details

**Files:**
- Modify: `w3xtool/object_detail_presentation.py`
- Modify: `w3xtool/gui_object_detail.py`
- Modify: `tests/test_gui_object_presentation.py`

**Interfaces:**
- Adds `format_complete_text_section(md, obj) -> str`.
- Adds `format_object_relation_sections(md, obj) -> str`.
- `ObjectDetailMixin._show_detail` inserts summary, complete readable/raw text, all materialized fields, references, and relation sections in that order.

- [ ] **Step 1: Add failing no-truncation and three-direction detail tests**

```python
def test_item_detail_shows_full_readable_and_raw_text_acquisition_and_skills() -> None:
    raw = "|cffffcc00" + ("原始全文|n" * 1200) + "|r"
    md, item = _item_map_with_complete_text_acquisition_and_skill(raw)
    self.app.map_data = md
    self.app._show_detail(item)
    text = self.app.detail.get("1.0", "end-1c")
    assert "【完整文本：可读版】" in text
    assert "【完整文本：原始版】" in text
    assert raw in text
    assert "【获取方式】" in text
    assert "怪物直接掉落" in text
    assert "【装备技能】" in text
    assert "A001" in text
    assert "……" not in text


def test_unit_and_skill_details_use_reverse_relation_indexes() -> None:
    md, unit, skill = _unit_skill_map_with_relations()
    self.app.map_data = md
    self.app._show_detail(unit)
    assert "【掉落/可获取装备】" in self.app.detail.get("1.0", "end")
    self.app._show_detail(skill)
    assert "【由哪些装备提供】" in self.app.detail.get("1.0", "end")
```

- [ ] **Step 2: Run presentation tests and verify missing sections**

Run: `uv run python -m pytest -q tests/test_gui_object_presentation.py`
Expected: FAIL because details do not query text/relation indexes.

- [ ] **Step 3: Implement pure formatters and keep all existing fields**

Format one heading per role/level/state and one evidence block per conflict variant. Always render readable and raw values, even when identical. Relation lines include IDs, names, group/chance/materials, player/coordinates, confidence, completeness, and evidence location. Do not slice any value. Continue using the existing scrollable textbox and copy-all menu.

- [ ] **Step 4: Run GUI presentation/layout regressions**

Run: `uv run python -m pytest -q tests/test_gui_object_presentation.py tests/test_gui_layout.py tests/test_gui_detail.py`
Expected: PASS.

- [ ] **Step 5: Commit only reviewed detail hunks**

```bash
git add -p -- w3xtool/object_detail_presentation.py w3xtool/gui_object_detail.py tests/test_gui_object_presentation.py
git diff --cached --check
git commit -m "feat: show complete item intelligence in details"
```

---

### Task 13: Searchable independent acquisition page and cache selection

**Files:**
- Create: `w3xtool/gui_item_relations.py`
- Create: `tests/test_gui_item_relations.py`
- Modify: `w3xtool/gui.py`
- Modify: `w3xtool/gui_shell.py`
- Modify: `w3xtool/gui_module_refresh.py`
- Modify: `w3xtool/gui_topbar.py`
- Modify: `w3xtool/gui_external_data.py`
- Modify: `w3xtool/gui_lifecycle.py`
- Modify: `w3xtool/gui_loader.py`
- Modify: `w3xtool/gui_loader_runner.py`
- Modify: `tests/gui_base.py`
- Modify: `tests/test_gui_layout.py`

**Interfaces:**
- `ItemRelationGuiMixin._build_item_relation_tab(parent)`, `_refresh_item_relations()`, `_show_relation_evidence()`, `_open_relation_target()`, and `_open_relation_source()`.
- App state `description_cache_path: str | None` persisted as `description_cache_path` in existing GUI JSON.

- [ ] **Step 1: Add failing layout, filter, evidence, navigation, and cache-menu tests**

```python
def test_relation_tab_lists_every_row_and_filters_without_mutating_index() -> None:
    md = _map_with_three_relation_kinds()
    self.app._render_map(md, [], [], None)
    assert "掉落/获取" in self.app.editor_tab_labels
    assert len(self.app.item_relation_tree.get_children()) == 3
    before = md.item_relations.records
    self.app.item_relation_search.set("I002")
    self.app._refresh_item_relations()
    assert len(self.app.item_relation_tree.get_children()) == 1
    assert md.item_relations.records == before


def test_relation_evidence_and_object_buttons_open_the_expected_details() -> None:
    md = _map_with_source_item_and_skill()
    self.app._render_map(md, [], [], None)
    iid = self.app.item_relation_tree.get_children()[0]
    self.app.item_relation_tree.selection_set(iid)
    self.app._show_relation_evidence()
    assert "war3mapUnits.doo" in self.app.item_relation_detail.get("1.0", "end")
    self.app._open_relation_target()
    assert self.app.tabs.get() == "对象编辑器"
    assert self.app.detail_title.cget("text") == "目标装备"
```

Assert type/confidence combobox filters, unresolved-object disabled buttons, double-click default target behavior, cache picker validation, clear action, config restore, and `GuiTestCase.setUp` cleanup.

- [ ] **Step 2: Run GUI tests and verify missing tab/mixin**

Run: `uv run python -m pytest -q tests/test_gui_item_relations.py tests/test_gui_layout.py`
Expected: FAIL because the new GUI surface does not exist.

- [ ] **Step 3: Build the tab with existing ttk/CustomTkinter patterns**

Add the tab between `场景放置` and `触发指令`. Use a search entry, read-only type/confidence comboboxes, a full Treeview with vertical/horizontal scrollbars, a read-only evidence textbox, and source/target buttons. Store `iid -> ItemRelation` in a per-render dictionary. Search the complete relation blob with existing `compile_query` and render all matching records without a limit.

Add “选择可信描述缓存” and “清除可信描述缓存” data-tool commands. Accept only a regular, non-symlink file that `load_description_cache` parses successfully; persist and reload the active map.

- [ ] **Step 4: Run the complete GUI suite**

Run: `uv run python -m pytest -q tests/test_gui*.py tests/test_recipe_scroll.py`
Expected: PASS.

- [ ] **Step 5: Commit the new mixin and reviewed GUI hunks**

```bash
git add -- w3xtool/gui_item_relations.py tests/test_gui_item_relations.py
git add -p -- w3xtool/gui.py w3xtool/gui_shell.py w3xtool/gui_module_refresh.py w3xtool/gui_topbar.py w3xtool/gui_external_data.py w3xtool/gui_lifecycle.py w3xtool/gui_loader.py w3xtool/gui_loader_runner.py tests/gui_base.py tests/test_gui_layout.py
git diff --cached --check
git commit -m "feat: add searchable item acquisition workspace"
```

---

### Task 14: Documentation, full verification, and 39-map read-only acceptance

**Files:**
- Modify: `docs/batch-icon-description-extraction.md`
- Create: `tests/test_real_map_item_relation_acceptance.py`
- Create outside repository during acceptance: `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2/`
- Do not modify: `/Users/zhongerbing/Desktop/Maps/**`

**Interfaces:**
- Documents the new GUI tab, complete-text states, relation confidence/completeness, TSV files, cache selection, and static-analysis limits.
- Produces machine-checkable before/after source manifests and v2 batch output.

- [ ] **Step 1: Run focused feature tests**

Run:

```bash
uv run python -m pytest -q \
  tests/test_object_text_roles.py \
  tests/test_object_text_index.py \
  tests/test_description_cache.py \
  tests/test_doo.py \
  tests/test_item_relation_models.py \
  tests/test_item_relations.py \
  tests/test_item_relation_scripts.py \
  tests/test_item_relation_exports.py \
  tests/test_gui_object_presentation.py \
  tests/test_gui_item_relations.py \
  tests/test_batch_map_processing.py \
  tests/test_knowledge_pack_item_relations.py
```

Expected: all selected tests pass.

- [ ] **Step 2: Run formatting, lint, and type checks on every changed Python file**

Run:

```bash
uv run --with ruff ruff format --check w3xtool tests
uv run --with ruff ruff check w3xtool tests
uv run --with basedpyright basedpyright --level error w3xtool tests
```

Expected: zero Ruff errors and zero basedpyright errors. If repository-wide pre-existing diagnostics appear, rerun the exact changed-file list and record both outputs without suppressing new diagnostics.

- [ ] **Step 3: Run the full regression suite**

Run: `uv run w3xray-test`
Expected: exit 0; all tests pass, with only the repository's explicitly skipped tests.

- [ ] **Step 4: Record immutable source identities before batch processing**

Run:

```bash
find '/Users/zhongerbing/Desktop/Maps' -type f \( -iname '*.w3x' -o -iname '*.w3m' -o -iname '*.w3n' \) -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 \
  > /Users/zhongerbing/Documents/xm/war3_xg/maps-before-item-relations.sha256
```

Expected: exactly 39 source rows and no read errors.

- [ ] **Step 5: Run v2 batch into a separate owned output root**

Run:

```bash
uv run main.py batch \
  '/Users/zhongerbing/Desktop/Maps' \
  --output '/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2'
```

Expected: 39 published per-map directories; every directory contains `对象描述.tsv`, `掉落与获取关系.tsv`, `装备技能关系.tsv`, and `关系完整性.txt`. Missing client data may produce “部分完成” but never a fabricated value.

- [ ] **Step 6: Verify old raw descriptions are a subset of v2 evidence and audit relation rows**

Run the repository acceptance test through explicit environment variables; the test reads these three variables with `os.environ[...]` and does not register private pytest options:

```bash
W3XRAY_MAPS_ROOT='/Users/zhongerbing/Desktop/Maps' \
W3XRAY_OLD_OUTPUT='/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output' \
W3XRAY_NEW_OUTPUT='/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2' \
uv run python -m pytest -q tests/test_real_map_item_relation_acceptance.py
```

The test must assert:

- every old non-placeholder raw tip/description appears byte-for-byte in the matching v2 map output;
- v2 TSV parses with the standard CSV reader and contains all required columns;
- every relation has a stable ID, source evidence, confidence, and completeness;
- every unresolved item/skill uses the explicit `未解析` state;
- direct DOO drops retain group and entry indexes;
- GUI and exporter formatter counts equal the underlying index counts for representative smallest, largest, and script-heavy maps.

Expected: PASS.

- [ ] **Step 7: Re-hash sources and compare manifests**

```bash
find '/Users/zhongerbing/Desktop/Maps' -type f \( -iname '*.w3x' -o -iname '*.w3m' -o -iname '*.w3n' \) -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 \
  > /Users/zhongerbing/Documents/xm/war3_xg/maps-after-item-relations.sha256
cmp \
  /Users/zhongerbing/Documents/xm/war3_xg/maps-before-item-relations.sha256 \
  /Users/zhongerbing/Documents/xm/war3_xg/maps-after-item-relations.sha256
```

Expected: `cmp` exits 0.

- [ ] **Step 8: Update user documentation with measured counts and verified limitations**

Document the actual v2 object-text state counts, relation-kind/confidence counts, unresolved IDs, runtime, peak memory if measured, source-hash result, and exact full-test result. State that the 9,682 unresolved named icon references remain an evidence/source limitation unless a matching client source is later supplied; do not label them extracted.

- [ ] **Step 9: Commit documentation and acceptance test without generated outputs**

```bash
git add -- docs/batch-icon-description-extraction.md tests/test_real_map_item_relation_acceptance.py
git diff --cached --check
git commit -m "docs: record item relation acceptance"
```

Never add `map-extract-output-v2`, before/after hash manifests, caches, images, or map files to Git.

---

## Plan Completion Criteria

- Tasks 1–13 each pass their focused tests and expose the exact interfaces consumed by the next task.
- Task 14 passes focused, full, Ruff, basedpyright, TSV round-trip, and 39-map read-only checks.
- The final worktree diff is reviewed against the pre-existing dirty baseline so unrelated user edits are neither reverted nor accidentally committed.
- The final handoff reports implemented relation counts, all seven text-state counts, unresolved evidence boundaries, test totals, and source-hash equality without claiming unavailable icons or descriptions were recovered.

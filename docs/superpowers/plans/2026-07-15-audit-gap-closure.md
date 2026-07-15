# Audit Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all seven confirmed extraction/relation/GUI audit gaps and publish a verified schema-4 39-map result without modifying source maps or the schema-3 output.

**Architecture:** Preserve exact object identities and field evidence during object materialization, then build all presentation and exports from the existing immutable text/relation indexes. Isolate each relation channel at the analysis boundary and propagate placement diagnostics into relation completeness.

**Tech Stack:** Python 3.14, uv, pytest, CustomTkinter/ttk, Ruff, basedpyright, existing safe batch publication.

## Global Constraints

- Source maps under `/Users/zhongerbing/Desktop/Maps` are read-only.
- Never modify `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2`.
- No runtime decryption, memory reading, DLL injection, map execution, or fabricated evidence.
- Every behavior change follows red → green → refactor.
- Preserve `obj_index` as a compatibility index while adding exact category-aware identity.
- Batch schema is 4 and project version is 0.1.3.

---

### Task 1: Exact object identity and field evidence

**Files:**
- Modify: `w3xtool/map_data.py`
- Modify: `w3xtool/object_candidates.py`
- Modify: `w3xtool/object_materialization.py`
- Modify: `w3xtool/object_pipeline.py`
- Modify: `w3xtool/map_components.py`
- Test: `tests/test_object_pipeline.py`
- Test: `tests/test_object_pipeline_priority.py`

**Interfaces:**
- Produces: `GameObjectFieldEvidence`, `MapData.obj_identity_index`, `build_object_identity_index()`.
- Preserves: existing `MapData.obj_index` and positional `GameObject` construction.

- [ ] **Step 1: Write failing tests for duplicate rawcodes and retained field variants**

```python
def test_exact_identity_index_keeps_same_rawcode_in_two_categories() -> None:
    unit = _object("单位", "X001")
    item = _object("物品", "X001")
    assert build_object_identity_index((unit, item)) == {
        ("单位", "X001"): unit,
        ("物品", "X001"): item,
    }

def test_materialization_retains_equal_priority_field_conflicts() -> None:
    merged = merge_object_candidates((first_sellitems, second_sellitems), {})[0]
    assert {row.value for row in merged.field_evidence} == {"I001", "I002"}
```

- [ ] **Step 2: Run the new tests and confirm identity/evidence assertions fail**

Run: `uv run python -m pytest -q tests/test_object_pipeline.py tests/test_object_pipeline_priority.py`

- [ ] **Step 3: Add immutable evidence records and populate both indexes**

```python
@dataclass(frozen=True, slots=True)
class GameObjectFieldEvidence:
    key: str
    label: str
    value: str
    source: str
    source_priority: int
    value_type: str = ""
```

- [ ] **Step 4: Re-run focused tests and static checks**

Run: `uv run python -m pytest -q tests/test_object_pipeline.py tests/test_object_pipeline_priority.py`

---

### Task 2: Metadata text fallback and mixed Buff classification

**Files:**
- Modify: `w3xtool/object_text_roles.py`
- Modify: `w3xtool/object_text_evidence.py`
- Modify: `w3xtool/object_candidate_values.py`
- Modify: `w3xtool/object_text_sources.py`
- Modify: `w3xtool/textobj.py`
- Test: `tests/test_object_text_roles.py`
- Test: `tests/test_object_text_sources.py`
- Test: `tests/test_object_text_index.py`
- Test: `tests/test_client_object_data.py`

**Interfaces:**
- Extends: `classify_text_field(category, key, label, value_type="")`.
- Produces: per-section Ability/Buff classification.

- [ ] **Step 1: Write failing metadata and mixed-file tests**

```python
def test_metadata_confirmed_unknown_string_uses_raw_field_role() -> None:
    assert classify_text_field("科技", "gco1", "效果 1 - %s", "string") == TextRoleMatch("gco1", None)

def test_mixed_ability_strings_classifies_buff_section_separately() -> None:
    records = collect_text_object_records(archive_with_a001_and_b001)
    assert [(row.obj_id, row.category) for row in records] == [
        ("A001", "技能"),
        ("B001", "增益"),
    ]
```

- [ ] **Step 2: Run tests and confirm both behaviors fail**

Run: `uv run python -m pytest -q tests/test_object_text_roles.py tests/test_object_text_sources.py tests/test_object_text_index.py tests/test_client_object_data.py`

- [ ] **Step 3: Implement field-type propagation and per-section classification**

Named Unit/Item/Upgrade files use their trusted file family. Ability files classify Buff-specific sections independently; anonymous blocks retain bounded whole-block classification.

- [ ] **Step 4: Re-run the focused tests**

Run: `uv run python -m pytest -q tests/test_object_text_roles.py tests/test_object_text_sources.py tests/test_object_text_index.py tests/test_client_object_data.py`

---

### Task 3: Category-safe relation endpoints and conflict rows

**Files:**
- Modify: `w3xtool/item_relation_endpoints.py`
- Modify: `w3xtool/item_relation_fields.py`
- Modify: `w3xtool/item_relation_builder.py`
- Test: `tests/test_item_relations.py`
- Test: `tests/test_item_relation_exports.py`

**Interfaces:**
- Consumes: `MapData.obj_identity_index`, `GameObject.field_evidence`.
- Produces: real `RelationCompleteness.CONFLICT` rows with retained evidence.

- [ ] **Step 1: Write failing category-collision and conflict tests**

```python
def test_relation_endpoint_resolves_requested_category_when_rawcodes_collide() -> None:
    endpoint, resolved = resolve_relation_object(md, "X001", "物品")
    assert resolved and endpoint.category == "物品"

def test_equal_priority_sellitems_conflicts_keep_both_rows() -> None:
    rows = tuple(row for row in object_field_relations(md) if row.kind is ItemRelationKind.SHOP_SELL)
    assert {row.item.object_id for row in rows} == {"I001", "I002"}
    assert {row.completeness for row in rows} == {RelationCompleteness.CONFLICT}
```

- [ ] **Step 2: Run tests and confirm the wrong endpoint and missing conflict**

Run: `uv run python -m pytest -q tests/test_item_relations.py tests/test_item_relation_exports.py`

- [ ] **Step 3: Select highest-priority variants per relation role and retain same-tier conflicts**

Legacy hand-built test objects without `field_evidence` continue to synthesize one selected evidence row.

- [ ] **Step 4: Re-run relation tests**

Run: `uv run python -m pytest -q tests/test_item_relations.py tests/test_item_relation_exports.py`

---

### Task 4: Placement partial-state propagation and relation-channel isolation

**Files:**
- Modify: `w3xtool/item_relation_endpoints.py`
- Modify: `w3xtool/item_relation_builder.py`
- Modify: `w3xtool/item_relation_fields.py`
- Modify: `w3xtool/item_relation_scripts.py`
- Test: `tests/test_item_relations.py`
- Test: `tests/test_component_parse_diagnostics.py`
- Test: `tests/test_map_relation_loading.py`

**Interfaces:**
- Produces: `placement_incomplete_reason(md, source)` and channel diagnostics with component `item-relations`.

- [ ] **Step 1: Write failing partial-DOO and injected-channel-failure tests**

```python
def test_recovered_drop_from_partial_doo_is_marked_partial() -> None:
    md.diagnostics.append(partial_units_diagnostic)
    (row,) = build_structural_item_relations(md)
    assert row.completeness is RelationCompleteness.PARTIAL
    assert "recovered 1 of 2" in row.unresolved_reason

def test_object_field_failure_does_not_remove_unit_drop(monkeypatch) -> None:
    monkeypatch.setattr(builder, "object_field_relations", fail)
    index = build_item_relation_index(md)
    assert index.for_kind(ItemRelationKind.UNIT_DROP)
    assert any(row.component == "item-relations" for row in md.diagnostics)
```

- [ ] **Step 2: Run tests and confirm current complete/abort behavior**

Run: `uv run python -m pytest -q tests/test_item_relations.py tests/test_component_parse_diagnostics.py tests/test_map_relation_loading.py`

- [ ] **Step 3: Propagate diagnostics and isolate each builder channel**

Catch broad exceptions only around the six top-level analysis channels, record the concrete exception, and continue with already completed channels.

- [ ] **Step 4: Re-run component and relation tests**

Run: `uv run python -m pytest -q tests/test_item_relations.py tests/test_component_parse_diagnostics.py tests/test_map_relation_loading.py`

---

### Task 5: Equipment-skill GUI target navigation

**Files:**
- Modify: `w3xtool/gui_item_relations.py`
- Modify: `w3xtool/gui_item_relation_layout.py`
- Test: `tests/test_gui_item_relations.py`

**Interfaces:**
- Produces: `_target_endpoint(relation)` for double-click/button behavior.

- [ ] **Step 1: Write failing skill-row navigation and table-value tests**

```python
def test_equipment_skill_double_click_target_opens_skill() -> None:
    self.app._render_map(_map_with_relations(), [], [], None)
    self.app.item_relation_tree.selection_set(skill_iid)
    self.app._open_relation_target()
    assert self.app.detail_title.cget("text") == "烈焰技能"
```

- [ ] **Step 2: Run the GUI test and confirm it opens the item**

Run: `uv run python -m pytest -q tests/test_gui_item_relations.py`

- [ ] **Step 3: Separate source, displayed-related, and default-target endpoints**

Skill rows display/open the skill as target and the equipment as source; acquisition rows retain existing behavior.

- [ ] **Step 4: Run the complete GUI relation suite**

Run: `uv run python -m pytest -q tests/test_gui_item_relations.py tests/test_gui_object_presentation.py tests/test_gui_layout.py`

---

### Task 6: Schema, documentation, and workflow migration

**Files:**
- Modify: `w3xtool/batch_models.py`
- Modify: `w3xtool/__init__.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/windows-real-war3.yml`
- Modify: `.github/workflows/posix-package.yml`
- Modify: `README.md`
- Modify: `AGENTS.d/runtime.md`
- Modify: `AGENTS.d/testing.md`
- Test: `tests/test_batch_state_reports.py`
- Test: `tests/test_windows_acceptance_assets.py`

**Interfaces:**
- Produces: batch schema 4 and version 0.1.3.

- [ ] **Step 1: Update tests to require schema 4 and selectable workflow refs**
- [ ] **Step 2: Run tests and confirm schema/workflow expectations fail**
- [ ] **Step 3: Update version, workflows, README, and current operational documentation**
- [ ] **Step 4: Run schema, workflow, and documentation tests**

Run: `uv run python -m pytest -q tests/test_batch_state_reports.py tests/test_windows_acceptance_assets.py tests/test_posix_package_assets.py`

---

### Task 7: Full verification and 39-map publication

**Files:**
- No repository source edits during acceptance.
- Output: `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v4`
- Temporary evidence: `/tmp/w3xray-schema4-acceptance`

**Interfaces:**
- Consumes: schema-4 application and trusted classic icon cache.
- Produces: verified state, per-map reports, source before/after hashes, and acceptance JSON.

- [ ] **Step 1: Run focused and static gates**

```bash
uv run w3xray-quality
uv run python -m pytest -q tests/test_object_text_roles.py tests/test_object_text_sources.py tests/test_object_text_index.py tests/test_item_relations.py tests/test_item_relation_exports.py tests/test_gui_item_relations.py
```

- [ ] **Step 2: Run the complete repository suite**

Run: `uv run w3xray-test`

- [ ] **Step 3: Record source hashes and run portable acceptance with GUI when available**

Run: `uv run main.py acceptance --map tests/fixtures/maps/war3net-map-script-builder.w3x --campaign tests/fixtures/reference/stormlib-campaign.w3n --output /tmp/w3xray-schema4-acceptance/output --report /tmp/w3xray-schema4-acceptance/acceptance.json --repeat 5`

- [ ] **Step 4: Run all 39 maps into the new owned root**

```bash
uv run main.py batch /Users/zhongerbing/Desktop/Maps \
  --output /Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v4 \
  --game-data /Users/zhongerbing/Documents/xm/war3_xg/trusted-icon-cache-classic
```

- [ ] **Step 5: Run real-map acceptance and compare source hashes**

Set `W3XRAY_MAPS_ROOT`, `W3XRAY_OLD_OUTPUT`, and `W3XRAY_NEW_OUTPUT` and run `tests/test_real_map_item_relation_acceptance.py`; require 39 results, schema 4, parseable TSV files, reconciled counts, and identical before/after source hashes.

- [ ] **Step 6: Review the final diff and commit implementation/documentation**


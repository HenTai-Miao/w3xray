# Icon and Complete-Text Evidence Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one evidence-driven schema-5 pipeline that removes false icon references, explains every remaining icon gap, selects complete object text by exact field and source priority, migrates only provable historical description evidence, exposes the same indexes in reports and GUI, and publishes a verified 39-map v5 result.

**Architecture:** Preserve exact icon/text field evidence at object materialization, then resolve it once into immutable indexes consumed by export, batch status, global reports, and GUI. Keep trusted historical data behind fail-closed owned-cache boundaries; keep source maps and all historical output roots read-only; publish only atomically validated schema-5 generations.

**Tech Stack:** Python 3.14, uv, pytest, frozen/slots dataclasses, CustomTkinter/ttk, existing MPQ/CASC readers, existing safe-output and manifest publication layers, Ruff, basedpyright.

## Global Constraints

- `/Users/zhongerbing/Desktop/Maps` is read-only and contains exactly the 39 acceptance sources.
- `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output`, `map-extract-output-v2`, and `map-extract-output-v4` are read-only historical evidence.
- New batch output is `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v5`; the new owned description cache is `/Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5`.
- Do not execute map scripts, EXE/DLL files, historical tools, or `Game.dll`; do not read game memory or perform runtime decryption.
- Do not resolve icons through basename, shortest-suffix, visual similarity, cross-map custom resources, or unbound anonymous payloads.
- Do not use another map's custom text as a description fill.
- Preserve raw and readable text without length limits; TSV must round-trip tabs, quotes, formula prefixes, CRLF, and physical newlines.
- Project version is `0.1.4`; batch schema and extraction revision are both `5`; schema-4 results are never reusable by revision 5.
- Every production change follows red → green → refactor, and every edited/created hand-written Python module remains at or below 250 pure LOC.
- `w3xtool/object_text_index.py` is already 249 pure LOC, so move selection logic out before adding behavior.

---

### Task 1: Exact icon-field eligibility and selected field evidence

**Files:**
- Create: `w3xtool/icon_field_evidence.py`
- Modify: `w3xtool/map_data.py:27-63`
- Modify: `w3xtool/object_field_selection.py:12-134`
- Modify: `w3xtool/object_materialization.py:96-185`
- Modify: `w3xtool/object_candidates.py:27-35`
- Test: `tests/test_icon_field_evidence.py`
- Test: `tests/test_object_candidate_merge.py`
- Test: `tests/test_object_pipeline_priority.py`

**Interfaces:**
- Produces: `IconFieldDisposition`, `IconFieldDecision`, `classify_icon_field(category, key, label, value_type, source_kind)`.
- Extends: `GameObjectFieldEvidence.value_source: str` and `GameObject.icon_field_evidence: GameObjectFieldEvidence | None` with trailing defaults so legacy positional construction remains valid.
- Changes: `select_object_field(selected, value, category)`; only an eligible field may use identity `display:icon`.
- Changes: `object_field_source_priority(value, category)` and `_materialized_evidence(values, category)` so the category needed for icon eligibility is never inferred from a label.
- Preserves: `GameObject.icon` as the compatibility display path derived from the selected evidence.

- [ ] **Step 1: Write failing tests for true, false, and base icon fields**

```python
@pytest.mark.parametrize(
    ("category", "key", "value_type", "expected"),
    (
        ("单位", "uico", "icon", IconFieldDisposition.ELIGIBLE),
        ("物品", "iico", "icon", IconFieldDisposition.ELIGIBLE),
        ("技能", "aart", "icon", IconFieldDisposition.ELIGIBLE),
        ("技能", "Art", "string", IconFieldDisposition.ELIGIBLE),
        ("科技", "gar1", "icon", IconFieldDisposition.ELIGIBLE),
        ("增益", "fart", "icon", IconFieldDisposition.ELIGIBLE),
        ("可破坏物", "bgsc", "real", IconFieldDisposition.FILTERED_NON_ICON),
        ("装饰物", "dfil", "model", IconFieldDisposition.FILTERED_NON_ICON),
        ("技能", "ResearchArt", "string", IconFieldDisposition.FILTERED_NON_ICON),
    ),
)
def test_icon_field_classification_is_exact(
    category: str,
    key: str,
    value_type: str,
    expected: IconFieldDisposition,
) -> None:
    decision = classify_icon_field(
        category,
        key,
        key,
        value_type,
        ObjectSourceKind.BINARY,
    )
    assert decision.disposition is expected


def test_materialization_retains_the_selected_icon_source_and_wts_location() -> None:
    merged = merge_object_candidates((_ability_with_wts_icon(),), {})[0]
    assert merged.icon == r"ReplaceableTextures\CommandButtons\BTNStorm.blp"
    assert merged.icon_field_evidence == GameObjectFieldEvidence(
        key="aart",
        label="图标 - 普通",
        value=r"ReplaceableTextures\CommandButtons\BTNStorm.blp",
        source="war3map.w3a",
        source_priority=40,
        value_type="icon",
        raw_value="TRIGSTR_7",
        value_source="war3map.wts#STRING 7",
    )


def _ability_with_wts_icon() -> ObjectCandidate:
    return ObjectCandidate(
        category="技能",
        obj_id="A001",
        base_id="AHbz",
        is_custom=True,
        ext="w3a",
        fields=(
            ObjectFieldValue(
                key="aart",
                label="图标 - 普通",
                value=r"ReplaceableTextures\CommandButtons\BTNStorm.blp",
                source="war3map.w3a",
                source_kind=ObjectSourceKind.BINARY,
                value_source="war3map.wts#STRING 7",
                value_type="icon",
                raw_value="TRIGSTR_7",
            ),
        ),
        refs=(),
    )
```

- [ ] **Step 2: Run the tests and verify the false fields currently become `display:icon`**

Run: `uv run python -m pytest -q tests/test_icon_field_evidence.py tests/test_object_candidate_merge.py tests/test_object_pipeline_priority.py`

Expected: FAIL because `bgsc`/`dfil` are still display aliases and selected WTS provenance is not retained.

- [ ] **Step 3: Add the closed eligibility model and exact category/key table**

```python
class IconFieldDisposition(StrEnum):
    ELIGIBLE = "eligible"
    FILTERED_NON_ICON = "filtered_non_icon_field"
    NOT_AN_ICON_FIELD = "not_an_icon_field"


@dataclass(frozen=True, slots=True)
class IconFieldDecision:
    disposition: IconFieldDisposition
    canonical_key: str
    detail: str = ""


_KNOWN_KEYS: Final = {
    "单位": frozenset(("uico",)),
    "物品": frozenset(("iico",)),
    "技能": frozenset(("aart", "art")),
    "科技": frozenset(("gar1",)),
    "增益": frozenset(("fart",)),
    "效果": frozenset(("fart",)),
}
_LEGACY_FALSE_ALIASES: Final = frozenset(
    ("aical", "bgsc", "dfil", "gico", "researchart")
)
```

`classify_icon_field()` must normalize `binary:`/`field:` and an explicit numeric level, accept `base:图标` only for bundled `ObjectSourceKind.BASE`, and return `FILTERED_NON_ICON` for `model`, `real`, or a legacy false alias before considering eligibility. It accepts either a category-specific key above or a field whose trusted metadata type is exactly `icon` in that same category; it must not infer eligibility from label substrings or from a string-valued field outside the closed key table.

- [ ] **Step 4: Route field selection through eligibility and retain the winning evidence**

```python
def select_object_field(
    selected: dict[str, ObjectFieldValue],
    value: ObjectFieldValue,
    category: str,
) -> None:
    identity = _field_identity(value, category)
    if not identity.startswith("display:"):
        label = value.label.casefold()
        if value.source_kind is ObjectSourceKind.BASE:
            if any(
                existing.source_kind is not ObjectSourceKind.BASE
                and existing.label.casefold() == label
                for existing in selected.values()
            ):
                return
        else:
            for existing_identity, existing in tuple(selected.items()):
                if (
                    existing.source_kind is ObjectSourceKind.BASE
                    and existing.label.casefold() == label
                ):
                    del selected[existing_identity]
    previous = selected.get(identity)
    if previous is None or _field_rank(value, identity, category) > _field_rank(
        previous,
        identity,
        category,
    ):
        selected[identity] = value


selected_icon = selected.get("display:icon")
icon = "" if selected_icon is None else selected_icon.value.split(",", 1)[0].strip()
icon_evidence = (
    None
    if selected_icon is None
    else _materialized_evidence((selected_icon,), category)[0]
)
```

Delete `bgsc`, `dfil`, `aical`, and `gico` from `_DISPLAY_ALIASES`, remove the unused `ICON_FIELDS` constant, pass `category` through both materialization call sites and `_field_rank()`, and copy `ObjectFieldValue.value_source` into every `GameObjectFieldEvidence`.

- [ ] **Step 5: Re-run focused tests and static checks**

Run: `uv run python -m pytest -q tests/test_icon_field_evidence.py tests/test_object_candidate_merge.py tests/test_object_pipeline_priority.py tests/test_item_relation_resilience.py`

Run: `uv run --with ruff ruff check w3xtool/icon_field_evidence.py w3xtool/map_data.py w3xtool/object_field_selection.py w3xtool/object_materialization.py tests/test_icon_field_evidence.py`

Run: `uv run --with basedpyright basedpyright --level error w3xtool/icon_field_evidence.py w3xtool/map_data.py w3xtool/object_field_selection.py w3xtool/object_materialization.py`

- [ ] **Step 6: Commit the independently testable eligibility change**

```bash
git add w3xtool/icon_field_evidence.py w3xtool/map_data.py w3xtool/object_field_selection.py w3xtool/object_materialization.py w3xtool/object_candidates.py tests/test_icon_field_evidence.py tests/test_object_candidate_merge.py tests/test_object_pipeline_priority.py
git commit -m "fix: retain exact icon field evidence"
```

---

### Task 2: Strict icon paths, lookup layers, and immutable gap index

**Files:**
- Create: `w3xtool/icon_evidence_models.py`
- Create: `w3xtool/icon_path_evidence.py`
- Create: `w3xtool/icon_evidence_builder.py`
- Modify: `w3xtool/icon_resources.py:13-241`
- Modify: `w3xtool/game_data_source.py:18-118`
- Modify: `w3xtool/classic_mpq_source.py:76-101`
- Modify: `w3xtool/casc_source.py:48-65`
- Modify: `w3xtool/casclib_source.py:53-78`
- Modify: `w3xtool/trusted_icon_cache.py:52-158`
- Modify: `w3xtool/map_data.py:67-112`
- Test: `tests/test_icon_path_evidence.py`
- Test: `tests/test_icon_evidence_builder.py`
- Test: `tests/test_icon_resources.py`
- Test: `tests/test_game_data_source.py`
- Test: `tests/test_casc_source.py`
- Test: `tests/test_trusted_icon_cache.py`

**Interfaces:**
- Produces: `IconGapReason`, `IconDiagnosticFlag`, `IconResolutionLayer`, `IconArchiveLayer`, `IconLookupAttempt`, `ResolvedIconEvidence`, `UnresolvedIconEvidence`, `FilteredIconEvidence`, `IconCandidateKind`, `IconCandidateEvidence`, and `IconEvidenceIndex`.
- Produces: `IconPathPlan = plan_icon_path(raw: str)` and `build_icon_evidence_index(md, archives, game_source)`.
- Produces: `merge_icon_evidence_indexes(indexes) -> IconEvidenceIndex` and appends `MapData.icon_evidence` with `empty_icon_evidence_index()` as its default factory.
- Adds: exact `has_exact_file(name)` / `read_exact_file(name)` methods to each client data source; existing browsing `has_file()` may retain suffix/basename behavior.
- Produces: `HistoricalIconEvidenceSet(available, resources)` and replaces `TrustedIconEvidenceSource.cached_icons_for()` with `historical_icons_for() -> HistoricalIconEvidenceSet`, so an absent same-map evidence file is distinguishable from a verified historical miss.

- [ ] **Step 1: Write failing path and strict-source tests**

```python
def test_path_plan_preserves_original_normalized_and_attempt_order() -> None:
    plan = plan_icon_path('  "ReplaceableTextures/CommandButtons/BTNHero"  ')
    assert plan.original == '  "ReplaceableTextures/CommandButtons/BTNHero"  '
    assert plan.normalized == r"ReplaceableTextures\CommandButtons\BTNHero"
    assert plan.candidates == (
        r"ReplaceableTextures\CommandButtons\BTNHero",
        r"ReplaceableTextures\CommandButtons\BTNHero.blp",
        r"ReplaceableTextures\CommandButtons\BTNHero.tga",
        r"ReplaceableTextures\CommandButtons\BTNHero.dds",
    )


def test_directory_exact_lookup_does_not_use_suffix_or_basename(tmp_path: Path) -> None:
    _write(tmp_path / "deep" / "Icons" / "BTNHero.blp", b"BLP1")
    source = DirectoryDataSource(str(tmp_path))
    assert source.has_file("BTNHero.blp")
    assert not source.has_exact_file("BTNHero.blp")
    assert source.has_exact_file(r"deep\Icons\BTNHero.blp")


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
```

- [ ] **Step 2: Run the path/source tests and confirm exact methods and structured plans are absent**

Run: `uv run python -m pytest -q tests/test_icon_path_evidence.py tests/test_game_data_source.py tests/test_casc_source.py`

Expected: FAIL on missing `plan_icon_path()` and `has_exact_file()`.

- [ ] **Step 3: Define closed icon evidence variants**

```python
class IconGapReason(StrEnum):
    INVALID_REFERENCE = "invalid_reference"
    NAMED_RESOURCE_MISSING = "named_resource_missing"
    ANONYMOUS_PAYLOAD_UNBOUND = "anonymous_payload_unbound"
    CLIENT_SOURCE_UNAVAILABLE = "client_source_unavailable"
    HISTORICAL_CLIENT_MISS = "historical_client_miss"
    ARCHIVE_NAME_UNAVAILABLE = "archive_name_unavailable"
    ARCHIVE_BLOCK_DAMAGED = "archive_block_damaged"


class IconDiagnosticFlag(StrEnum):
    CLIENT_NOT_PROVIDED = "client_not_provided"
    HISTORICAL_EVIDENCE_CHECKED = "historical_evidence_checked"
    ANONYMOUS_BLP_PRESENT = "anonymous_blp_present"
    ARCHIVE_HAS_RAW_BLOCK = "archive_has_raw_block"
    ARCHIVE_HAS_DAMAGED_BLOCK = "archive_has_damaged_block"
    ARCHIVE_HAS_RESTRICTED_BLOCK = "archive_has_restricted_block"


class IconResolutionLayer(StrEnum):
    CURRENT_MAP = "current_map"
    CAMPAIGN_ROOT = "campaign_root"
    CLIENT = "client"
    SAME_MAP_HISTORY = "same_map_history"
    TRUSTED_CACHE = "trusted_cache"


class IconCandidateKind(StrEnum):
    EXACT_OTHER_MAP_PATH = "exact_other_map_path"
    ANONYMOUS_HASH_MATCH = "anonymous_hash_match"


@dataclass(frozen=True, slots=True)
class HistoricalIconEvidenceSet:
    available: bool
    resources: tuple[NamedIconResource, ...]


@dataclass(frozen=True, slots=True)
class IconCandidateEvidence:
    kind: IconCandidateKind
    requested_map_sha256: str
    requested_path: str
    anonymous_map_sha256: str
    anonymous_block_index: int | None
    candidate_map_sha256: str
    candidate_path: str
    content_sha256: str
    adopted: bool = False


type IconEvidenceRow = (
    ResolvedIconEvidence | UnresolvedIconEvidence | FilteredIconEvidence
)


@dataclass(frozen=True, slots=True)
class IconEvidenceIndex:
    resolved: tuple[ResolvedIconEvidence, ...]
    unresolved: tuple[UnresolvedIconEvidence, ...]
    filtered: tuple[FilteredIconEvidence, ...]
    anonymous: tuple[AnonymousIconResource, ...]
    anonymous_read_failure_count: int
    candidates: tuple[IconCandidateEvidence, ...]
    _by_object: Mapping[tuple[str, str], tuple[IconEvidenceRow, ...]]

    @classmethod
    def build(
        cls,
        resolved: Iterable[ResolvedIconEvidence] = (),
        unresolved: Iterable[UnresolvedIconEvidence] = (),
        filtered: Iterable[FilteredIconEvidence] = (),
        anonymous: Iterable[AnonymousIconResource] = (),
        anonymous_read_failure_count: int = 0,
        candidates: Iterable[IconCandidateEvidence] = (),
    ) -> IconEvidenceIndex:
        ordered_resolved = tuple(sorted(resolved, key=_resolved_key))
        ordered_unresolved = tuple(sorted(unresolved, key=_unresolved_key))
        ordered_filtered = tuple(sorted(filtered, key=_filtered_key))
        ordered_anonymous = tuple(sorted(anonymous, key=_anonymous_key))
        ordered_candidates = tuple(sorted(candidates, key=_candidate_key))
        grouped: dict[tuple[str, str], list[IconEvidenceRow]] = {}
        for row in (*ordered_resolved, *ordered_unresolved, *ordered_filtered):
            reference = row.reference
            grouped.setdefault(
                (reference.category, reference.object_id),
                [],
            ).append(row)
        return cls(
            ordered_resolved,
            ordered_unresolved,
            ordered_filtered,
            ordered_anonymous,
            anonymous_read_failure_count,
            ordered_candidates,
            MappingProxyType(
                {identity: tuple(rows) for identity, rows in grouped.items()}
            ),
        )

    def for_object(self, category: str, object_id: str) -> tuple[IconEvidenceRow, ...]:
        return self._by_object.get((category, object_id), ())
```

Define the five referenced sort-key helpers in the same module from stable map digest/path/object/field/block values; none may use object identity or filesystem iteration order. `IconObjectReference` must add trailing fields named `base_id`, `map_path`, `map_sha256`, `map_scope`, `field_key`, `field_label`, `field_type`, `field_source`, and `wts_source` while retaining its original first three positional fields. Task 2 initializes `candidates=()`; Task 8 constructs only non-adopted batch-wide candidates and rebuilds the aggregate immutable index.

- [ ] **Step 4: Implement reversible path planning and the fixed main-reason precedence**

`plan_icon_path()` must trim only outer whitespace and one paired quote layer, normalize `/` to `\`, strip meaningless leading separators, canonicalize only known namespace casing, reject absolute/traversal/control-character paths, accept extensionless values and `.blp`/`.tga`/`.dds`, and reject other leaf extensions. Deduplicate candidate paths case-insensitively in original/BLP/TGA/DDS order.

The exact main-reason priority is:

```python
_GAP_REASON_PRIORITY: Final = (
    IconGapReason.INVALID_REFERENCE,
    IconGapReason.ARCHIVE_BLOCK_DAMAGED,
    IconGapReason.ARCHIVE_NAME_UNAVAILABLE,
    IconGapReason.ANONYMOUS_PAYLOAD_UNBOUND,
    IconGapReason.HISTORICAL_CLIENT_MISS,
    IconGapReason.CLIENT_SOURCE_UNAVAILABLE,
    IconGapReason.NAMED_RESOURCE_MISSING,
)
```

- [ ] **Step 5: Write failing layer-order, historical-match, and no-fuzzy-promotion tests**

```python
def test_resolution_uses_map_client_history_cache_order() -> None:
    index = build_icon_evidence_index(md, archives, source_with_all_layers)
    row = index.resolved[0]
    assert row.layer is IconResolutionLayer.CURRENT_MAP
    assert tuple(attempt.layer for attempt in row.attempts) == (
        IconResolutionLayer.CURRENT_MAP,
    )


def test_same_map_history_must_match_current_requested_path() -> None:
    index = build_icon_evidence_index(md, (), history_with_unrelated_icon)
    assert not index.resolved
    assert index.unresolved[0].reason is IconGapReason.HISTORICAL_CLIENT_MISS


def test_basename_and_cross_map_candidates_never_resolve() -> None:
    index = build_icon_evidence_index(md_for(r"Custom\BTN.blp"), (), basename_source)
    assert not index.resolved
    assert index.unresolved[0].reference.normalized_path == r"Custom\BTN.blp"
```

- [ ] **Step 6: Run the new builder tests and confirm the legacy resolver lacks layer evidence**

Run: `uv run python -m pytest -q tests/test_icon_evidence_builder.py tests/test_icon_resources.py tests/test_trusted_icon_cache.py`

Expected: FAIL because `resolve_named_icon()` returns only a resource/`None`, historical rows are appended after global lookup, and unrelated cached rows can be exported.

- [ ] **Step 7: Build the index once in strict layer order**

```python
def build_icon_evidence_index(
    md: MapData,
    archives: tuple[IconArchiveLayer, ...],
    game_source: GameDataSource | None,
) -> IconEvidenceIndex:
    references, filtered = collect_icon_field_references(md)
    history = _history_for(md, game_source)
    resolved: list[ResolvedIconEvidence] = []
    unresolved: list[UnresolvedIconEvidence] = []
    for reference in references:
        outcome = _resolve_reference(reference, archives, game_source, history)
        match outcome:
            case ResolvedIconEvidence() as row:
                resolved.append(row)
            case UnresolvedIconEvidence() as row:
                unresolved.append(row)
            case unreachable:
                assert_never(unreachable)
    anonymous, failures = collect_anonymous_icon_evidence(md, archives)
    return IconEvidenceIndex.build(
        resolved,
        unresolved,
        filtered,
        anonymous,
        failures,
    )
```

Map/campaign archives use their exact member lookup. If `game_source` is not a `TrustedIconEvidenceSource`, its exact methods represent a real client and are queried before history. If it is a `TrustedIconEvidenceSource`, it is never mislabeled as `CLIENT`: first query `historical_icons_for(map_sha256)` by exact requested path and use `available` to distinguish `HISTORICAL_CLIENT_MISS` from unavailable history, then query the trusted payload table by exact global virtual path as `TRUSTED_CACHE`. Current object/field references replace historical object labels on a history hit; historical provenance remains in the lookup attempts.

- [ ] **Step 8: Re-run icon tests and static gates**

Run: `uv run python -m pytest -q tests/test_icon_path_evidence.py tests/test_icon_evidence_builder.py tests/test_icon_resources.py tests/test_game_data_source.py tests/test_casc_source.py tests/test_casclib_source.py tests/test_classic_mpq_source.py tests/test_trusted_icon_cache.py`

Run: `uv run --with ruff ruff check w3xtool/icon_evidence_models.py w3xtool/icon_path_evidence.py w3xtool/icon_evidence_builder.py w3xtool/icon_resources.py w3xtool/game_data_source.py w3xtool/trusted_icon_cache.py`

Run: `uv run --with basedpyright basedpyright --level error w3xtool/icon_evidence_models.py w3xtool/icon_path_evidence.py w3xtool/icon_evidence_builder.py w3xtool/icon_resources.py w3xtool/game_data_source.py w3xtool/trusted_icon_cache.py`

- [ ] **Step 9: Commit the strict evidence index**

```bash
git add w3xtool/icon_evidence_models.py w3xtool/icon_path_evidence.py w3xtool/icon_evidence_builder.py w3xtool/icon_resources.py w3xtool/game_data_source.py w3xtool/classic_mpq_source.py w3xtool/casc_source.py w3xtool/casclib_source.py w3xtool/trusted_icon_cache.py w3xtool/map_data.py tests/test_icon_path_evidence.py tests/test_icon_evidence_builder.py tests/test_icon_resources.py tests/test_game_data_source.py tests/test_casc_source.py tests/test_trusted_icon_cache.py
git commit -m "feat: index strict icon resolution evidence"
```

---

### Task 3: Per-map icon gap reports and reconciled publication

**Files:**
- Create: `w3xtool/icon_evidence_exports.py`
- Modify: `w3xtool/batch_map_icons.py:27-145`
- Modify: `w3xtool/batch_icon_export.py:24-254`
- Modify: `w3xtool/batch_map_processing.py:24-184`
- Modify: `w3xtool/batch_reports.py:31-224`
- Modify: `w3xtool/batch_map_result.py:11-59`
- Modify: `w3xtool/batch_manifest_models.py:10-68`
- Modify: `w3xtool/batch_report_validation.py:22-118`
- Test: `tests/test_icon_evidence_exports.py`
- Test: `tests/test_batch_map_icons.py`
- Test: `tests/test_batch_map_processing.py`
- Test: `tests/test_batch_reports.py`
- Test: `tests/test_batch_manifest.py`
- Modify test fixture: `tests/batch_publication_fixture.py:21-105`

**Interfaces:**
- Produces: `BatchIconEvidence(exports, index)` from `export_map_icons()`.
- Produces: `UNRESOLVED_ICON_HEADER`, `format_unresolved_icon_tsv(index)`, and `format_icon_integrity(index, exports)`.
- Extends: `IconExportRecord.resolution_layer: IconResolutionLayer | None` as a trailing compatibility field and adds the `解析层` column to `ICON_REPORT_HEADER`.
- Adds required map report: `图标未解析.tsv`.
- Separates: valid reference occurrences, resolved reference occurrences, filtered fields, normalized named-gap rows, unresolved reference occurrences, anonymous payloads/read failures, original write failures, and PNG failures.

- [ ] **Step 1: Write failing lossless gap-export and count-reconciliation tests**

```python
def test_unresolved_report_has_one_path_row_with_every_reference() -> None:
    report = format_unresolved_icon_tsv(index_with_two_object_references())
    table = read_tsv_text(report)
    assert len(table.rows) == 1
    row = table.rows[0]
    assert table.value(row, "规范路径") == r"Icons\Missing.blp"
    assert table.value(row, "主原因") == "historical_client_miss"
    references = json.loads(table.value(row, "引用集合"))
    assert {(item["category"], item["rawcode"]) for item in references} == {
        ("技能", "A001"),
        ("物品", "I001"),
    }


def test_map_publication_reconciles_gap_rows_and_split_failures(tmp_path: Path) -> None:
    result = process_fixture_map(tmp_path)
    output = tmp_path / "output" / result.output_directory
    gaps = read_tsv(output / "图标未解析.tsv")
    assert len(gaps.rows) == result.unresolved_icon_count
    assert result.original_write_failure_count == 0
    assert result.png_failure_count == 0
```

- [ ] **Step 2: Run focused tests and verify the batch currently returns only an unresolved integer**

Run: `uv run python -m pytest -q tests/test_icon_evidence_exports.py tests/test_batch_map_icons.py tests/test_batch_map_processing.py tests/test_batch_manifest.py`

Expected: FAIL because no gap table or structured count fields exist.

- [ ] **Step 3: Render complete unresolved rows and split integrity lines**

```python
UNRESOLVED_ICON_HEADER: Final = (
    "地图路径",
    "地图SHA256",
    "子地图",
    "原始路径集合",
    "规范路径",
    "尝试路径",
    "主原因",
    "诊断标志",
    "查询证据",
    "对象分类",
    "Rawcode",
    "引用数",
    "引用集合",
)
```

`引用集合` is a compact JSON array. Each object has exactly these keys: `category`, `rawcode`, `base`, `name`, `field`, `label`, `type`, `source`, `wts`, `map`, `scope`; objects are emitted in stable sort order and the parser rejects missing/extra/duplicate identities. `format_icon_integrity()` must print explicit zero-valued lines for every split counter and must never label named gaps as write failures.

- [ ] **Step 4: Make icon export consume the immutable index**

```python
@dataclass(frozen=True, slots=True)
class BatchIconEvidence:
    exports: tuple[IconExportRecord, ...]
    index: IconEvidenceIndex


def export_map_icons(
    root: MapData,
    maps: tuple[MapData, ...],
    stage: Path,
    game_source: GameDataSource | None,
) -> BatchIconEvidence:
    records: list[IconExportRecord] = []
    named_indexes: dict[tuple[str, str], int] = {}
    indexes: list[IconEvidenceIndex] = []
    with ExitStack() as stack:
        opened = tuple(
            (item, stack.enter_context(open_map_source(item))) for item in maps
        )
        root_archive = opened[0][1]
        for item, archive in opened:
            layers = [
                IconArchiveLayer(
                    IconResolutionLayer.CURRENT_MAP,
                    archive,
                    item.path,
                )
            ]
            if item is not root:
                layers.append(
                    IconArchiveLayer(
                        IconResolutionLayer.CAMPAIGN_ROOT,
                        root_archive,
                        root.path,
                    )
                )
            index = build_icon_evidence_index(item, tuple(layers), game_source)
            item.icon_evidence = index
            indexes.append(index)
            for row in index.resolved:
                _merge_resolved_icon(records, named_indexes, stage, row)
            records.extend(
                export_anonymous_icon(str(stage), resource)
                for resource in index.anonymous
            )
    return BatchIconEvidence(
        canonicalize_icon_paths(stage, tuple(records)),
        merge_icon_evidence_indexes(tuple(indexes)),
    )
```

`_merge_resolved_icon()` calls `export_named_icon()` with the `ResolvedIconEvidence`, keys duplicates by `(normalized path casefold, content SHA-256)`, and replaces only the `objects` tuple with the stable union of exact field references. Remove the separate `source_digest` argument because each map ledger carries its own digest.

- [ ] **Step 5: Require and validate `图标未解析.tsv`**

Add it to `REQUIRED_MAP_REPORTS`; parse it through the standard TSV decoder; verify its row count equals `MapBatchResult.unresolved_icon_count`, every reason is an `IconGapReason`, every row has a nonempty normalized path and reference set, and no row appears in the resolved named index for the same map/path.
Update `tests.batch_publication_fixture.write_empty_publication()` to write the canonical empty `图标未解析.tsv` and the split zero counters so every later resume/global fixture remains manifest-valid.

- [ ] **Step 6: Re-run per-map publication and manifest tests**

Run: `uv run python -m pytest -q tests/test_icon_evidence_exports.py tests/test_batch_map_icons.py tests/test_batch_map_processing.py tests/test_batch_reports.py tests/test_batch_manifest.py tests/test_batch_icon_export.py`

- [ ] **Step 7: Commit the per-map report slice**

```bash
git add w3xtool/icon_evidence_exports.py w3xtool/batch_map_icons.py w3xtool/batch_icon_export.py w3xtool/batch_map_processing.py w3xtool/batch_reports.py w3xtool/batch_map_result.py w3xtool/batch_manifest_models.py w3xtool/batch_report_validation.py tests/batch_publication_fixture.py tests/test_icon_evidence_exports.py tests/test_batch_map_icons.py tests/test_batch_map_processing.py tests/test_batch_reports.py tests/test_batch_manifest.py
git commit -m "feat: publish structured icon gap reports"
```

---

### Task 4: Exact text identities and priority-based current-value selection

**Files:**
- Create: `w3xtool/object_text_selection.py`
- Modify: `w3xtool/object_text_roles.py:10-134`
- Modify: `w3xtool/object_text_evidence.py:13-182`
- Modify: `w3xtool/object_text_models.py:12-104`
- Modify: `w3xtool/object_text_index.py:1-279`
- Modify: `w3xtool/object_text_exports.py:10-69`
- Modify: `w3xtool/object_text_presentation.py:8-49`
- Modify: `w3xtool/batch_item_reports.py:18-88`
- Modify: `w3xtool/batch_report_validation.py:42-75`
- Test: `tests/test_object_text_roles.py`
- Test: `tests/test_object_text_index.py`
- Test: `tests/test_object_text_pipeline.py`
- Test: `tests/test_object_text_priority.py`
- Test: `tests/test_batch_item_report_processing.py`
- Modify test fixture: `tests/batch_map_processing_fixture.py:100-155`

**Interfaces:**
- Extends: `TextRoleMatch(role, level, semantic_field)`.
- Changes: `TextIdentity` to `(category, object_id, semantic_field, role, level)`.
- Adds: `TextSourcePriority`, `TextSelectionReason`, `TextEvidence.semantic_field`, and `TextEvidence.source_priority`.
- Adds to `ObjectTextRecord`: `semantic_field`, `source_priority`, `is_current`, and `selection_reason`.
- Produces: `select_text_identity(identity, map_values, client_values, cache_values, client_text_available)` in the new module.

- [ ] **Step 1: Write failing exact-role tests for the known false-conflict fields**

```python
@pytest.mark.parametrize(
    ("key", "label", "semantic_field"),
    (
        ("ResearchArt", "图标 - 学习", "researchart"),
        ("Researchbuttonpos", "按钮位置 - 学习", "researchbuttonpos"),
        ("Researchhotkey", "热键 - 学习", "researchhotkey"),
        ("Orderoff", "关闭命令", "orderoff"),
    ),
)
def test_control_fields_keep_their_own_string_identity(
    key: str,
    label: str,
    semantic_field: str,
) -> None:
    assert classify_text_field("技能", key, label, "string") == TextRoleMatch(
        semantic_field,
        None,
        semantic_field,
    )


def test_untip_is_the_only_exact_close_tip_alias() -> None:
    assert classify_text_field("技能", "Untip", "提示工具 - 关闭", "string") == (
        TextRoleMatch("关闭提示", None, "untip")
    )
```

- [ ] **Step 2: Run role tests and confirm substring fallback misclassifies research/off fields**

Run: `uv run python -m pytest -q tests/test_object_text_roles.py`

Expected: FAIL because `_is_learn_*` and `_is_close_*` currently classify by substrings.

- [ ] **Step 3: Replace substring fallback with exact semantic aliases**

```python
_SEMANTIC_FIELDS: Final = {
    "tip": ("基础提示", "tip"),
    "utip": ("基础提示", "tip"),
    "atp1": ("基础提示", "tip"),
    "ubertip": ("扩展提示", "ubertip"),
    "utub": ("扩展提示", "ubertip"),
    "aub1": ("扩展提示", "ubertip"),
    "researchtip": ("学习提示", "researchtip"),
    "aret": ("学习提示", "researchtip"),
    "researchubertip": ("学习扩展提示", "researchubertip"),
    "arut": ("学习扩展提示", "researchubertip"),
    "untip": ("关闭提示", "untip"),
    "aut1": ("关闭提示", "untip"),
    "unubertip": ("关闭扩展提示", "unubertip"),
    "auu1": ("关闭扩展提示", "unubertip"),
}
```

Add the existing name, proper-name, suffix, revive, awaken, editor-description, and Buff keys to this exact mapping. Exact normalized labels may map only when the whole normalized label equals a closed alias. Unknown metadata-confirmed strings use their normalized raw key for both role and semantic field.

- [ ] **Step 4: Write failing source-priority and true-conflict tests**

```python
def test_text_strings_win_over_binary_and_slk_without_losing_originals() -> None:
    rows = _index_with_name_sources().for_object("单位", "H001")
    current = tuple(row for row in rows if row.is_current)
    assert [(row.raw_value, row.source_priority) for row in current] == [
        ("地图文本名称", int(TextSourcePriority.MAP_TEXT_STRINGS))
    ]
    assert {row.raw_value for row in rows} == {
        "地图文本名称",
        "地图二进制名称",
        "地图SLK名称",
    }
    assert all(
        row.selection_reason is TextSelectionReason.LOWER_PRIORITY
        for row in rows
        if not row.is_current
    )


def test_only_same_field_level_and_priority_can_conflict() -> None:
    rows = _index_with_two_binary_ubertips_and_one_slk_value().records
    conflicts = tuple(row for row in rows if row.state is ObjectTextState.SOURCE_CONFLICT)
    assert {row.raw_value for row in conflicts} == {"二进制甲", "二进制乙"}
    assert {row.source_priority for row in conflicts} == {
        int(TextSourcePriority.MAP_BINARY)
    }
    assert next(row for row in rows if row.raw_value == "SLK旧值").conflict_group == ""


def _index_with_name_sources() -> ObjectTextIndex:
    obj = GameObject("单位", "w3u", "H001", "Hpal", "测试英雄", True)
    candidates = (
        _text_candidate(
            "单位",
            "H001",
            "Hpal",
            _text_field(
                "unam",
                "名称",
                "地图文本名称",
                "war3map.wts",
                ObjectSourceKind.TEXT_STRINGS,
            ),
        ),
        _text_candidate(
            "单位",
            "H001",
            "Hpal",
            _text_field(
                "unam",
                "名称",
                "地图二进制名称",
                "war3map.w3u",
                ObjectSourceKind.BINARY,
            ),
        ),
        _text_candidate(
            "单位",
            "H001",
            "Hpal",
            _text_field(
                "unam",
                "名称",
                "地图SLK名称",
                "Units\\UnitData.slk",
                ObjectSourceKind.SLK,
            ),
        ),
    )
    return build_object_text_index(
        (obj,),
        candidates,
        (),
        EMPTY_DESCRIPTION_CACHE,
        client_text_available=False,
    )


def _index_with_two_binary_ubertips_and_one_slk_value() -> ObjectTextIndex:
    obj = GameObject("技能", "w3a", "A001", "AHbz", "测试技能", True)
    candidates = (
        _text_candidate(
            "技能",
            "A001",
            "AHbz",
            _text_field(
                "aub1:1",
                "提示工具 - 扩展的 (等级1)",
                "二进制甲",
                "war3map.w3a#record1",
                ObjectSourceKind.BINARY,
            ),
        ),
        _text_candidate(
            "技能",
            "A001",
            "AHbz",
            _text_field(
                "aub1:1",
                "提示工具 - 扩展的 (等级1)",
                "二进制乙",
                "war3map.w3a#record2",
                ObjectSourceKind.BINARY,
            ),
        ),
        _text_candidate(
            "技能",
            "A001",
            "AHbz",
            _text_field(
                "aub1:1",
                "提示工具 - 扩展的 (等级1)",
                "SLK旧值",
                "Units\\AbilityData.slk",
                ObjectSourceKind.SLK,
            ),
        ),
    )
    return build_object_text_index(
        (obj,),
        candidates,
        (),
        EMPTY_DESCRIPTION_CACHE,
        client_text_available=False,
    )


def _text_candidate(
    category: str,
    object_id: str,
    base_id: str,
    field: ObjectFieldValue,
) -> ObjectCandidate:
    ext = "w3u" if category == "单位" else "w3a"
    return ObjectCandidate(category, object_id, base_id, True, ext, (field,), ())


def _text_field(
    key: str,
    label: str,
    value: str,
    source: str,
    source_kind: ObjectSourceKind,
) -> ObjectFieldValue:
    return ObjectFieldValue(
        key,
        label,
        value,
        source,
        source_kind,
        value_type="string",
    )
```

- [ ] **Step 5: Run priority tests and confirm map sources are currently conflated**

Run: `uv run python -m pytest -q tests/test_object_text_priority.py tests/test_object_text_index.py tests/test_object_text_pipeline.py`

Expected: FAIL because map strings/function/binary/SLK share tiers and lower-priority rows are discarded.

- [ ] **Step 6: Move selection out of the 249-pure-LOC index module**

```python
class TextSourcePriority(IntEnum):
    TRUSTED_CACHE = 100
    CLIENT = 200
    MAP_ANONYMOUS = 300
    MAP_SLK = 400
    MAP_FUNCTION_TEXT = 500
    MAP_BINARY = 600
    MAP_TEXT_STRINGS = 700


class TextSelectionReason(StrEnum):
    HIGHEST_PRIORITY_VALUE = "最高优先级唯一值"
    SAME_PRIORITY_CONFLICT = "同优先级来源冲突"
    LOWER_PRIORITY = "低优先级证据"
    EXPLICIT_EMPTY = "作者明确清空"
    PLACEHOLDER_SKIPPED = "作者未定义占位"
    NO_SOURCE = "无可用来源"
```

`select_text_identity()` must retain every unique evidence row, choose the highest priority containing a non-placeholder value, treat `""` as explicit empty rather than a placeholder, allow fixed nonempty placeholders to fall through, mark every lower tier `is_current=False`, and create a conflict only when distinct raw values share the exact identity and priority. A map explicit empty must block client/cache when no higher map value exists.

- [ ] **Step 7: Add lossless TSV columns and name-based validation**

Insert `规范字段身份`, `证据优先级`, `是否当前值`, and `选择原因` into `OBJECT_TEXT_REPORT_HEADER`. Update validation to locate columns by header name rather than fixed indexes. `description_counts` continues to count all evidence rows; knowledge status in Task 7 will inspect current rows only.

- [ ] **Step 8: Re-run complete text tests and enforce the LOC ceiling**

Run: `uv run python -m pytest -q tests/test_object_text_roles.py tests/test_object_text_index.py tests/test_object_text_pipeline.py tests/test_object_text_priority.py tests/test_batch_item_report_processing.py tests/test_batch_reports.py`

Run: `awk '!/^[[:space:]]*$/ && !/^[[:space:]]*#/' w3xtool/object_text_index.py | wc -l`

Expected: PASS and at most 200 pure LOC in `object_text_index.py`; `object_text_selection.py` is at most 250 pure LOC.

- [ ] **Step 9: Commit the exact text selector**

```bash
git add w3xtool/object_text_selection.py w3xtool/object_text_roles.py w3xtool/object_text_evidence.py w3xtool/object_text_models.py w3xtool/object_text_index.py w3xtool/object_text_exports.py w3xtool/object_text_presentation.py w3xtool/batch_item_reports.py w3xtool/batch_report_validation.py tests/batch_map_processing_fixture.py tests/test_object_text_roles.py tests/test_object_text_index.py tests/test_object_text_pipeline.py tests/test_object_text_priority.py tests/test_batch_item_report_processing.py
git commit -m "fix: select text by exact field priority"
```

---

### Task 5: Fail-closed historical description-cache migration

**Files:**
- Create: `w3xtool/description_cache_migration_models.py`
- Create: `w3xtool/description_cache_migration_rows.py`
- Create: `w3xtool/description_cache_publication.py`
- Create: `w3xtool/description_cache_migration.py`
- Create: `w3xtool/trusted_description_cache.py`
- Create: `w3xtool/description_cache_cli.py`
- Modify: `w3xtool/description_cache_models.py:10-93`
- Modify: `w3xtool/description_cache_schema.py:8-42`
- Modify: `w3xtool/description_cache.py:11-124`
- Modify: `main.py:15-76`
- Test: `tests/test_description_cache_migration.py`
- Test: `tests/test_description_cache_publication.py`
- Test: `tests/test_trusted_description_cache.py`
- Test: `tests/test_description_cache.py`

**Interfaces:**
- Produces CLI: `uv run main.py description-cache migrate --legacy-output ROOT --legacy-cache FILE --output ROOT`.
- Produces: `DescriptionCacheMigrationOptions`, `DescriptionCacheRejectionReason`, `DescriptionCacheRejection`, and `DescriptionCacheMigrationResult`.
- Produces: `migrate_description_cache(options) -> DescriptionCacheMigrationResult`.
- Produces: `VerifiedDescriptionCache(cache, manifest_sha256, content_sha256)` and `load_trusted_description_cache(root) -> VerifiedDescriptionCache`.
- Owns: `.w3xray-trusted-description-cache`, `可信描述缓存.tsv`, `来源清单.tsv`, `可信缓存迁移拒绝.tsv`, and `内容清单.json`.

- [ ] **Step 1: Write failing migration acceptance/rejection tests using exact legacy schemas**

```python
def test_migration_accepts_only_exact_base_client_fill(tmp_path: Path) -> None:
    legacy_output, legacy_cache = _legacy_inputs(
        tmp_path,
        cache_row=_candidate(base_id="ratf", role="扩展提示", raw="原版说明"),
        report_row=_legacy_client_fill(
            object_id="ratf",
            base_id="ratf",
            raw_description="原版说明",
            readable_description="原版说明",
            description_source="base:ratf",
        ),
    )
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(
            legacy_output=legacy_output,
            legacy_cache=legacy_cache,
            output=tmp_path / "trusted",
        )
    )
    assert result.accepted_count == 1
    assert result.rejected_count == 0
    verified = load_trusted_description_cache(tmp_path / "trusted")
    assert verified.cache.lookup("物品", "ratf", "扩展提示", None)[0].raw_value == (
        "原版说明"
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        ("custom_object", DescriptionCacheRejectionReason.NOT_BASE_OBJECT),
        ("source_digest", DescriptionCacheRejectionReason.SOURCE_MAP_UNKNOWN),
        ("source_label", DescriptionCacheRejectionReason.SOURCE_LABEL_MISMATCH),
        ("readable", DescriptionCacheRejectionReason.READABLE_MISMATCH),
        ("report_value", DescriptionCacheRejectionReason.SOURCE_ROW_MISSING),
    ),
)
def test_migration_rejects_unproved_rows(
    tmp_path: Path,
    mutation: str,
    reason: DescriptionCacheRejectionReason,
) -> None:
    options = _mutated_legacy_inputs(tmp_path, mutation)
    result = migrate_description_cache(options)
    assert result.accepted_count == 0
    assert {row.reason for row in result.rejections} == {reason}


_SOURCE_DIGEST = "a" * 64
_LEGACY_RELATIVE = "地图/001_fixture_aaaaaaaa"


def _candidate(
    *,
    base_id: str,
    role: str,
    raw: str,
    source_digest: str = _SOURCE_DIGEST,
    readable: str | None = None,
) -> tuple[str, ...]:
    return (
        "物品",
        base_id,
        role,
        "",
        raw,
        readable_text(raw) if readable is None else readable,
        source_digest,
        "",
    )


def _legacy_client_fill(
    *,
    object_id: str,
    base_id: str,
    raw_description: str,
    readable_description: str,
    description_source: str,
    custom: bool = False,
) -> tuple[str, ...]:
    return (
        "物品",
        object_id,
        base_id,
        "测试物品",
        "是" if custom else "否",
        "",
        "",
        "",
        "",
        raw_description,
        readable_description,
        description_source,
        "客户端补全",
    )


def _legacy_inputs(
    tmp_path: Path,
    *,
    cache_row: tuple[str, ...],
    report_row: tuple[str, ...],
) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    legacy_output = tmp_path / "legacy-output"
    map_output = legacy_output / _LEGACY_RELATIVE
    map_output.mkdir(parents=True)
    report = map_output / "对象描述.tsv"
    report.write_text(
        format_tsv_rows((LEGACY_DESCRIPTION_HEADER, report_row)),
        encoding="utf-8",
        newline="",
    )
    state = {
        "schema_version": 1,
        "results": [
            {
                "source": {
                    "path": "/maps/source.w3x",
                    "size": 3,
                    "mtime_ns": 4,
                    "sha256": _SOURCE_DIGEST,
                },
                "display_name": "source",
                "output_directory": _LEGACY_RELATIVE,
                "stage": "published",
                "state": "部分完成",
                "first_error": "",
                "object_count": 1,
                "description_counts": [["客户端补全", 1]],
                "named_icon_count": 0,
                "anonymous_icon_count": 0,
                "original_written_count": 0,
                "png_written_count": 0,
                "icon_failure_count": 0,
                "restricted_block_count": 0,
                "elapsed_ms": 1,
            }
        ],
    }
    (legacy_output / "批量提取状态.json").write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    source_value = f"{report}#base:{cache_row[1]}"
    completed_cache_row = (*cache_row[:7], source_value)
    legacy_cache = tmp_path / "legacy-cache.tsv"
    legacy_cache.write_text(
        format_tsv_rows((LEGACY_CACHE_HEADER, completed_cache_row)),
        encoding="utf-8",
        newline="",
    )
    return legacy_output, legacy_cache


def _mutated_legacy_inputs(
    tmp_path: Path,
    mutation: str,
) -> DescriptionCacheMigrationOptions:
    candidate = _candidate(base_id="ratf", role="扩展提示", raw="原版说明")
    report = _legacy_client_fill(
        object_id="ratf",
        base_id="ratf",
        raw_description="原版说明",
        readable_description="原版说明",
        description_source="base:ratf",
    )
    if mutation == "custom_object":
        candidate = _candidate(
            base_id="I001",
            role="扩展提示",
            raw="自定义说明",
        )
        report = _legacy_client_fill(
            object_id="I001",
            base_id="I001",
            raw_description="自定义说明",
            readable_description="自定义说明",
            description_source="base:I001",
            custom=True,
        )
    elif mutation == "source_digest":
        candidate = _candidate(
            base_id="ratf",
            role="扩展提示",
            raw="原版说明",
            source_digest="b" * 64,
        )
    elif mutation == "source_label":
        report = _legacy_client_fill(
            object_id="ratf",
            base_id="ratf",
            raw_description="原版说明",
            readable_description="原版说明",
            description_source="map:ratf",
        )
    elif mutation == "readable":
        candidate = _candidate(
            base_id="ratf",
            role="扩展提示",
            raw="原版说明",
            readable="错误可读值",
        )
    elif mutation == "report_value":
        report = _legacy_client_fill(
            object_id="ratf",
            base_id="ratf",
            raw_description="其他说明",
            readable_description="其他说明",
            description_source="base:ratf",
        )
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    legacy_output, legacy_cache = _legacy_inputs(
        tmp_path,
        cache_row=candidate,
        report_row=report,
    )
    return DescriptionCacheMigrationOptions(
        legacy_output=legacy_output,
        legacy_cache=legacy_cache,
        output=tmp_path / "trusted",
    )
```

- [ ] **Step 2: Run migration tests and verify no explicit migration boundary exists**

Run: `uv run python -m pytest -q tests/test_description_cache_migration.py`

Expected: FAIL because current code only harvests the active output and cannot parse schema-1 state plus the schema-2 candidate table.

- [ ] **Step 3: Define stable rejection reasons and exact legacy headers**

```python
class DescriptionCacheRejectionReason(StrEnum):
    INVALID_IDENTITY = "invalid_identity"
    NOT_BASE_OBJECT = "not_base_object"
    UNSUPPORTED_ROLE = "unsupported_role"
    SOURCE_MAP_UNKNOWN = "source_map_unknown"
    SOURCE_PATH_ESCAPE = "source_path_escape"
    SOURCE_REPORT_MISSING = "source_report_missing"
    SOURCE_ROW_MISSING = "source_row_missing"
    SOURCE_LABEL_MISMATCH = "source_label_mismatch"
    READABLE_MISMATCH = "readable_mismatch"
    TSV_ROUND_TRIP_MISMATCH = "tsv_round_trip_mismatch"
    CONFLICTING_VALUE = "conflicting_value"


LEGACY_CACHE_HEADER: Final = (
    "分类",
    "基础ID",
    "文本角色",
    "等级/变体",
    "原始全文",
    "可读全文",
    "来源地图SHA256",
    "来源路径",
)
LEGACY_DESCRIPTION_HEADER: Final = (
    "分类",
    "对象ID",
    "基础ID",
    "名称",
    "自定义",
    "等级",
    "原始提示",
    "可读提示",
    "提示来源",
    "原始说明",
    "可读说明",
    "说明来源",
    "完整性状态",
)
```

Malformed JSON/TSV structure, wrong headers, duplicate state identities, symlinked roots/files, changing files, and overlapping input/output roots raise `DescriptionCacheMigrationError` before publication. Semantically invalid candidate rows produce rejection rows and do not abort other candidates.

- [ ] **Step 4: Parse and verify every candidate against schema-1 state and its source report**

For each candidate, perform these exact checks in order: base object exists in `BASE_OBJECTS` with matching category; rawcode/role/level syntax is valid; source digest has exactly one schema-1 result; source report resolves strictly below `legacy_output`; the report has one matching base-object row; the role selects the matching raw/readable/source triplet; source equals `base:<base_id>`; `readable_text(raw)` equals candidate readable text; `format_tsv_rows()` plus `decode_tsv_cell()` round-trips every candidate cell. Group surviving candidates by `(category, base_id, role, level)` and reject the whole group as `CONFLICTING_VALUE` when it contains multiple raw values.

- [ ] **Step 5: Write failing owned-cache tamper and atomic-replacement tests**

```python
def test_trusted_cache_rejects_source_manifest_tampering(tmp_path: Path) -> None:
    root = _published_cache(tmp_path)
    source_manifest = root / "来源清单.tsv"
    source_manifest.write_bytes(source_manifest.read_bytes() + b"tamper")
    with pytest.raises(TrustedDescriptionCacheError, match="hash mismatch"):
        load_trusted_description_cache(root)


def test_failed_replacement_keeps_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _published_cache(tmp_path, raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = _legacy_inputs(
        tmp_path / "replacement",
        cache_row=_candidate(base_id="ratf", role="扩展提示", raw="second"),
        report_row=_legacy_client_fill(
            object_id="ratf",
            base_id="ratf",
            raw_description="second",
            readable_description="second",
            description_source="base:ratf",
        ),
    )
    monkeypatch.setattr(publication, "_replace_stage", _raise_os_error)
    with pytest.raises(DescriptionCachePublicationError):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(
                legacy_output=legacy_output,
                legacy_cache=legacy_cache,
                output=root,
            )
        )
    assert load_trusted_description_cache(root) == before


def _published_cache(tmp_path: Path, *, raw: str = "原版说明") -> Path:
    legacy_output, legacy_cache = _legacy_inputs(
        tmp_path,
        cache_row=_candidate(base_id="ratf", role="扩展提示", raw=raw),
        report_row=_legacy_client_fill(
            object_id="ratf",
            base_id="ratf",
            raw_description=raw,
            readable_description=readable_text(raw),
            description_source="base:ratf",
        ),
    )
    root = tmp_path / "trusted"
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
    )
    assert result.accepted_count == 1
    return root


def _raise_os_error(*_args: object, **_kwargs: object) -> None:
    raise OSError("replace failed")
```

- [ ] **Step 6: Publish and validate the owned cache atomically**

```python
TRUSTED_DESCRIPTION_CACHE_MARKER: Final = ".w3xray-trusted-description-cache"
TRUSTED_DESCRIPTION_CACHE_SCHEMA: Final = 1
TRUSTED_DESCRIPTION_CACHE_FILES: Final = (
    "可信描述缓存.tsv",
    "来源清单.tsv",
    "可信缓存迁移拒绝.tsv",
)


@dataclass(frozen=True, slots=True)
class VerifiedDescriptionCache:
    cache: DescriptionCache
    manifest_sha256: str
    content_sha256: str
```

Write the three TSV payloads into a sibling stage directory, hash each into `内容清单.json`, compute `content_sha256` from the sorted `(name,size,sha256)` tuples, write a marker binding schema and manifest SHA-256, validate the stage through `load_trusted_description_cache()`, then atomically replace only a nonexistent or correctly owned destination. The loader must rehash all cache files and every regular source path listed in `来源清单.tsv`, reject symlinks/escapes, verify candidate source-row digests, and return no partial cache on failure.

- [ ] **Step 7: Add the typed CLI boundary and stable exit codes**

```python
def run_description_cache_cli(argv: tuple[str, ...]) -> int:
    options = parse_description_cache_cli_options(argv)
    result = migrate_description_cache(options)
    print(
        f"可信描述缓存迁移完成：接受 {result.accepted_count}，"
        f"拒绝 {result.rejected_count} -> {options.output}"
    )
    return 0
```

`parse_description_cache_cli_options()` accepts exactly the `migrate` action and the three required, nonrepeating path options. It returns code 2 for parse/preflight/trust errors without a traceback and code 0 for a partially accepted, structurally valid migration.

- [ ] **Step 8: Run cache tests and static gates**

Run: `uv run python -m pytest -q tests/test_description_cache_migration.py tests/test_description_cache_publication.py tests/test_trusted_description_cache.py tests/test_description_cache.py tests/test_cli_options.py`

Run: `uv run --with ruff ruff check w3xtool/description_cache_migration_models.py w3xtool/description_cache_migration_rows.py w3xtool/description_cache_publication.py w3xtool/description_cache_migration.py w3xtool/trusted_description_cache.py w3xtool/description_cache_cli.py main.py`

Run: `uv run --with basedpyright basedpyright --level error w3xtool/description_cache_migration_models.py w3xtool/description_cache_migration_rows.py w3xtool/description_cache_publication.py w3xtool/description_cache_migration.py w3xtool/trusted_description_cache.py w3xtool/description_cache_cli.py main.py`

- [ ] **Step 9: Commit the migration boundary**

```bash
git add main.py w3xtool/description_cache_migration_models.py w3xtool/description_cache_migration_rows.py w3xtool/description_cache_publication.py w3xtool/description_cache_migration.py w3xtool/trusted_description_cache.py w3xtool/description_cache_cli.py w3xtool/description_cache_models.py w3xtool/description_cache_schema.py w3xtool/description_cache.py tests/test_description_cache_migration.py tests/test_description_cache_publication.py tests/test_trusted_description_cache.py tests/test_description_cache.py
git commit -m "feat: migrate trusted description evidence"
```

---

### Task 6: Explicit cache input and dependency-bound batch execution

**Files:**
- Delete: `w3xtool/batch_description_cache.py`
- Delete: `w3xtool/description_cache_batch.py`
- Modify: `w3xtool/batch_configuration.py:12-120`
- Modify: `w3xtool/batch_cli.py:24-211`
- Modify: `w3xtool/batch_runner.py:43-157`
- Modify: `w3xtool/batch_dependencies.py:22-105`
- Modify: `w3xtool/batch_execution_request.py:13-79`
- Modify: `w3xtool/description_cache.py:11-124`
- Modify: `w3xtool/load_context.py:17-59`
- Modify: `w3xtool/gui_external_data.py:37-132`
- Modify: `w3xtool/gui_topbar.py:80-88`
- Modify: `w3xtool/gui_loader.py:79-181`
- Modify: `w3xtool/gui_loader_runner.py:30-96`
- Test: `tests/test_batch_cli.py`
- Test: `tests/test_batch_dependencies.py`
- Test: `tests/test_batch_description_cache.py`
- Test: `tests/test_description_cache_manifest_binding.py`
- Test: `tests/test_batch_runner.py`
- Test: `tests/test_batch_resume_runner.py`
- Test: `tests/test_gui_description_cache.py`
- Test: `tests/test_map_relation_loading.py`

**Interfaces:**
- Adds: `BatchOptions.description_cache_path: str | None` and CLI `--description-cache ROOT`.
- Changes: `fingerprint_dependencies(source, options, description_cache_manifest_sha256)`.
- Changes: GUI cache selection from a TSV file to an owned cache directory.
- Removes: automatic harvesting/publication of description evidence from the active output root.
- Sets: `BATCH_EXTRACTION_REVISION = 5`; the dependency fingerprint binds the verified description-cache manifest and schema-5 icon/text report contracts.

- [ ] **Step 1: Write failing CLI, root-safety, and fingerprint tests**

```python
def test_batch_cli_accepts_owned_description_cache_root() -> None:
    options = parse_batch_cli_options(
        ("/maps", "--description-cache", "/trusted/descriptions")
    )
    assert options.description_cache_path == "/trusted/descriptions"
    assert options.to_batch_options().description_cache_path == (
        "/trusted/descriptions"
    )


def test_description_cache_manifest_changes_dependency_fingerprint() -> None:
    first = fingerprint_dependencies(source, options, "a" * 64)
    second = fingerprint_dependencies(source, options, "b" * 64)
    assert first != second


def test_schema_five_uses_extraction_revision_five() -> None:
    assert BATCH_EXTRACTION_REVISION == 5


def test_batch_preflight_rejects_an_invalid_explicit_cache(tmp_path: Path) -> None:
    options = BatchOptions(
        source_directory=str(_maps(tmp_path)),
        output_root=str(tmp_path / "output"),
        description_cache_path=str(tmp_path / "not-owned"),
    )
    with pytest.raises(BatchConfigurationError, match="description cache"):
        run_batch(options)


def _maps(tmp_path: Path) -> Path:
    root = tmp_path / "Maps"
    root.mkdir()
    (root / "sample.w3x").write_bytes(b"map")
    return root
```

- [ ] **Step 2: Run batch cache tests and confirm current code auto-builds from output**

Run: `uv run python -m pytest -q tests/test_batch_cli.py tests/test_batch_dependencies.py tests/test_batch_description_cache.py tests/test_batch_runner.py`

Expected: FAIL because there is no explicit option and `_run_batch_locked()` calls `build_and_publish_description_cache(output_root)`.

- [ ] **Step 3: Normalize and validate the explicit cache root**

Append `description_cache_path` to `BatchOptions`/`BatchCliOptions`, parse it through the existing closed `_ValueOption` match, expand it to an absolute path, and reject a symlink, missing root, overlap with source/output, or a root that fails `load_trusted_description_cache()`. `None` selects `EMPTY_DESCRIPTION_CACHE` with the fixed identity `sha256(b"w3xray:no-description-cache")`.

- [ ] **Step 4: Load once before workers and propagate only immutable entries**

```python
verified = (
    empty_verified_description_cache()
    if normalized.description_cache_path is None
    else load_trusted_description_cache(normalized.description_cache_path)
)
context = replace(
    build_map_load_context(game_data_path=normalized.game_data_path),
    description_cache=verified.cache,
)
cache_text = format_description_cache_tsv(verified.cache)
cache_identity = verified.manifest_sha256
```

Use `cache_identity` for attempt/reuse fingerprints and set `BATCH_EXTRACTION_REVISION` to `5`. `MapExecutionRequest` continues to serialize entries/diagnostics only; the parent owns trust verification. Global publication may retain `cache_text` as the exact run snapshot, but it must not promote newly published map rows into that cache.

- [ ] **Step 5: Remove the automatic cache builders and update GUI selection**

Delete the two automatic-builder modules, remove `build_description_cache_from_batch` from `description_cache.py`, and remove all deleted imports/exports. Convert their tests into assertions that a second run does not alter the explicit cache root and that no-cache runs remain empty. Repurpose `test_description_cache_manifest_binding.py` to exercise the owned-cache source-manifest/hash binding through `load_trusted_description_cache()`. `on_pick_description_cache()` must call `filedialog.askdirectory()`, validate through the same loader, persist the root only after validation, and show the manifest prefix plus entry count.

- [ ] **Step 6: Re-run execution, GUI, and resume tests**

Run: `uv run python -m pytest -q tests/test_batch_cli.py tests/test_batch_dependencies.py tests/test_batch_description_cache.py tests/test_description_cache_manifest_binding.py tests/test_batch_runner.py tests/test_batch_resume_runner.py tests/test_batch_execution.py tests/test_gui_description_cache.py tests/test_map_relation_loading.py`

- [ ] **Step 7: Commit explicit cache consumption**

```bash
git add -A w3xtool/batch_description_cache.py w3xtool/description_cache_batch.py w3xtool/batch_configuration.py w3xtool/batch_cli.py w3xtool/batch_runner.py w3xtool/batch_dependencies.py w3xtool/batch_execution_request.py w3xtool/description_cache.py w3xtool/load_context.py w3xtool/gui_external_data.py w3xtool/gui_topbar.py w3xtool/gui_loader.py w3xtool/gui_loader_runner.py tests/test_batch_cli.py tests/test_batch_dependencies.py tests/test_batch_description_cache.py tests/test_description_cache_manifest_binding.py tests/test_batch_runner.py tests/test_batch_resume_runner.py tests/test_gui_description_cache.py tests/test_map_relation_loading.py
git commit -m "feat: bind batch runs to explicit description cache"
```

---

### Task 7: Schema-5 three-axis state and split counters

**Files:**
- Create: `w3xtool/batch_status.py`
- Create: `w3xtool/batch_result_parser.py`
- Modify: `w3xtool/batch_models.py:9-76`
- Modify: `w3xtool/batch_map_result.py:11-59`
- Modify: `w3xtool/batch_map_processing.py:78-151`
- Modify: `w3xtool/batch_map_attempt.py:156-235`
- Modify: `w3xtool/batch_state_io.py:13-98`
- Modify: `w3xtool/batch_state_parser.py:14-153`
- Modify: `w3xtool/batch_reports.py:120-173`
- Modify: `w3xtool/batch_manifest_models.py:38-68`
- Modify: `w3xtool/batch_manifest_io.py:78-186`
- Modify: `w3xtool/batch_manifest_validation.py:43-74`
- Modify: `w3xtool/batch_resume.py:100-151`
- Modify: `w3xtool/batch_map_retirement.py:45-123`
- Modify: `w3xtool/acceptance_batch.py:94-128`
- Modify: `w3xtool/batch_cli.py:164-201`
- Modify test fixture: `tests/batch_publication_fixture.py:61-105`
- Test: `tests/test_batch_status.py`
- Test: `tests/test_batch_result_parser.py`
- Test: `tests/test_batch_state_reports.py`
- Test: `tests/test_batch_manifest.py`
- Test: `tests/test_batch_global_publication.py`
- Test: `tests/test_batch_execution.py`
- Test: `tests/test_batch_resume.py`
- Test: `tests/test_batch_resume_loading.py`
- Test: `tests/test_batch_resume_runner.py`
- Test: `tests/test_batch_runner.py`
- Test: `tests/test_batch_map_retirement.py`
- Test: `tests/test_batch_cli.py`
- Test: `tests/test_acceptance_runner.py`

**Interfaces:**
- Sets: `BATCH_SCHEMA_VERSION = 5`.
- Produces: `PublicationResult`, `ArchiveIntegrity`, `KnowledgeEvidence`, and `KnowledgeGapReason`.
- Produces: `derive_batch_axes(publication, *, raw_blocks, damaged_blocks, restricted_blocks, icon_gaps, current_text_states, relation_partial_count, unresolved_endpoint_count, icon_diagnostics=()) -> BatchAxes` and `derive_legacy_map_state(axes) -> MapBatchState`.
- Moves: exact result-key parsing and result semantic validation from `batch_state_parser.py` to `batch_result_parser.py`; `parse_state_json()` retains root JSON/schema/identity validation and delegates each row to `parse_map_batch_result()`.
- Extends `MapBatchResult` with authoritative axes and split icon/archive counters; retains `state` as a one-schema compatibility value.

- [ ] **Step 1: Write failing independent-axis tests**

```python
def test_published_map_with_icon_gap_is_not_a_publication_failure() -> None:
    axes = derive_batch_axes(
        publication=PublicationResult.PUBLISHED,
        raw_blocks=0,
        damaged_blocks=0,
        restricted_blocks=0,
        icon_gaps=1,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
    assert axes.publication is PublicationResult.PUBLISHED
    assert axes.archive is ArchiveIntegrity.COMPLETE
    assert axes.knowledge is KnowledgeEvidence.PARTIAL
    assert axes.knowledge_reasons == (KnowledgeGapReason.ICON_UNBOUND,)
    assert derive_legacy_map_state(axes) is MapBatchState.PARTIAL


def test_archive_damage_does_not_change_knowledge_axis() -> None:
    axes = derive_batch_axes(
        publication=PublicationResult.PUBLISHED,
        raw_blocks=0,
        damaged_blocks=3,
        restricted_blocks=0,
        icon_gaps=0,
        current_text_states=(ObjectTextState.MAP_VALUE,),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
    assert axes.archive is ArchiveIntegrity.DAMAGED_BLOCKS
    assert axes.knowledge is KnowledgeEvidence.COMPLETE
```

- [ ] **Step 2: Run state tests and confirm the legacy combined precedence cannot express them**

Run: `uv run python -m pytest -q tests/test_batch_status.py tests/test_batch_state_reports.py`

Expected: FAIL because only `MapBatchState` and a combined `icon_failure_count` exist.

- [ ] **Step 3: Define the axes, reason order, and archive precedence**

```python
class PublicationResult(StrEnum):
    PUBLISHED = "已发布"
    FAILED = "失败"
    CANCELLED = "取消"


class ArchiveIntegrity(StrEnum):
    COMPLETE = "完整"
    RAW_BLOCKS = "存在原始块"
    DAMAGED_BLOCKS = "存在损坏块"
    RESTRICTED_BLOCKS = "存在受限块"


class KnowledgeEvidence(StrEnum):
    COMPLETE = "完整"
    PARTIAL = "部分"


class KnowledgeGapReason(StrEnum):
    CLIENT_MISSING = "缺少客户端"
    ICON_UNBOUND = "图标未绑定"
    RELATION_PARTIAL = "关系部分"
    TRUE_SOURCE_CONFLICT = "真正来源冲突"
    ENDPOINT_UNRESOLVED = "端点未解析"


@dataclass(frozen=True, slots=True)
class BatchAxes:
    publication: PublicationResult
    archive: ArchiveIntegrity
    knowledge: KnowledgeEvidence
    knowledge_reasons: tuple[KnowledgeGapReason, ...]


def derive_batch_axes(
    publication: PublicationResult,
    *,
    raw_blocks: int,
    damaged_blocks: int,
    restricted_blocks: int,
    icon_gaps: int,
    current_text_states: tuple[ObjectTextState, ...],
    relation_partial_count: int,
    unresolved_endpoint_count: int,
    icon_diagnostics: tuple[IconDiagnosticFlag, ...] = (),
) -> BatchAxes:
    archive = _derive_archive_integrity(
        raw_blocks,
        damaged_blocks,
        restricted_blocks,
    )
    reasons = _derive_knowledge_reasons(
        icon_gaps,
        icon_diagnostics,
        current_text_states,
        relation_partial_count,
        unresolved_endpoint_count,
    )
    knowledge = (
        KnowledgeEvidence.PARTIAL if reasons else KnowledgeEvidence.COMPLETE
    )
    return BatchAxes(publication, archive, knowledge, reasons)
```

Archive precedence is damaged, restricted, raw, complete. Knowledge reasons are emitted in enum declaration order. `CLIENT_MISSING` comes only from a current `SOURCE_UNAVAILABLE` row or an icon diagnostic explicitly saying the client source is unavailable; `TRUE_SOURCE_CONFLICT` comes only from current conflict rows; author placeholders and lower-priority differences do not make knowledge partial.

- [ ] **Step 4: Add authoritative result fields and derive legacy compatibility**

Add these persisted fields after the existing required counters:

```python
publication_result: PublicationResult
archive_integrity: ArchiveIntegrity
knowledge_evidence: KnowledgeEvidence
knowledge_gap_reasons: tuple[KnowledgeGapReason, ...]
raw_block_count: int
damaged_block_count: int
valid_icon_reference_count: int
resolved_icon_reference_count: int
filtered_icon_field_count: int
unresolved_icon_count: int
unresolved_icon_reference_count: int
anonymous_read_failure_count: int
original_write_failure_count: int
png_failure_count: int
```

`unresolved_icon_count` is the number of per-map normalized-path rows in `图标未解析.tsv`; `unresolved_icon_reference_count` preserves the field-reference multiplicity, and `valid_icon_reference_count == resolved_icon_reference_count + unresolved_icon_reference_count`. `icon_failure_count` remains serialized for one schema cycle but equals only `anonymous_read_failure_count + original_write_failure_count + png_failure_count`; named evidence gaps are represented by the two unresolved counters. Terminal results set publication `FAILED`/`CANCELLED`, archive complete, knowledge partial only when evidence analysis ran and found a reason, and no published path.

- [ ] **Step 5: Update strict JSON/manifest parsing and semantic validation**

Require exact schema-5 key sets; parse every enum and nonnegative counter; ensure published results use `PublicationResult.PUBLISHED`; ensure failed/cancelled states have no output/manifest; ensure `knowledge_evidence` is partial iff reasons are nonempty; ensure `state == derive_legacy_map_state(axes)`; and reconcile all new manifest summary counters against the required reports.

Change `format_retry_tsv()` and CLI exit counts to use `publication_result`: published maps with partial knowledge are successful and absent from `失败与重试.tsv`; only failed/cancelled publication results are retry/exit failures. Resume still reuses every manifest-valid `PUBLISHED` result regardless of the compatibility `state` value.
Update `require_authoritative_batch()` and retirement selection the same way: authoritative map directories are selected by `PublicationResult.PUBLISHED`, never by whether the knowledge axis is complete.

- [ ] **Step 6: Re-run state, manifest, wire, resume, and CLI tests**

Run: `uv run python -m pytest -q tests/test_batch_status.py tests/test_batch_result_parser.py tests/test_batch_state_reports.py tests/test_batch_manifest.py tests/test_batch_global_publication.py tests/test_batch_execution.py tests/test_batch_resume.py tests/test_batch_resume_loading.py tests/test_batch_resume_runner.py tests/test_batch_runner.py tests/test_batch_map_retirement.py tests/test_batch_cli.py tests/test_acceptance_runner.py`

Run: `awk '!/^[[:space:]]*$/ && !/^[[:space:]]*#/' w3xtool/batch_state_parser.py | wc -l`

Expected: PASS and at most 170 pure LOC in `batch_state_parser.py`; `batch_result_parser.py` is at most 250 pure LOC.

- [ ] **Step 7: Commit schema-5 state semantics**

```bash
git add w3xtool/batch_status.py w3xtool/batch_result_parser.py w3xtool/batch_models.py w3xtool/batch_map_result.py w3xtool/batch_map_processing.py w3xtool/batch_map_attempt.py w3xtool/batch_state_io.py w3xtool/batch_state_parser.py w3xtool/batch_reports.py w3xtool/batch_manifest_models.py w3xtool/batch_manifest_io.py w3xtool/batch_manifest_validation.py w3xtool/batch_resume.py w3xtool/batch_map_retirement.py w3xtool/acceptance_batch.py w3xtool/batch_cli.py tests/batch_publication_fixture.py tests/test_batch_status.py tests/test_batch_result_parser.py tests/test_batch_state_reports.py tests/test_batch_manifest.py tests/test_batch_global_publication.py tests/test_batch_execution.py tests/test_batch_resume.py tests/test_batch_resume_loading.py tests/test_batch_resume_runner.py tests/test_batch_runner.py tests/test_batch_map_retirement.py tests/test_batch_cli.py tests/test_acceptance_runner.py
git commit -m "feat: split batch status into three axes"
```

---

### Task 8: Global icon evidence, candidate reports, and authoritative reconciliation

**Files:**
- Create: `w3xtool/icon_candidate_bindings.py`
- Create: `w3xtool/batch_global_evidence_models.py`
- Create: `w3xtool/batch_global_evidence.py`
- Create: `w3xtool/batch_global_evidence_reports.py`
- Create: `w3xtool/batch_global_payloads.py`
- Modify: `w3xtool/batch_global_models.py:10-65`
- Modify: `w3xtool/batch_global_publication.py:52-224`
- Modify: `w3xtool/batch_global_validation.py:32-119`
- Modify: `w3xtool/batch_checkpoint_publication.py:11-29`
- Modify: `w3xtool/batch_global_reports.py:9-75`
- Modify: `w3xtool/acceptance_batch.py:42-90`
- Test: `tests/test_icon_candidate_bindings.py`
- Test: `tests/test_batch_global_evidence.py`
- Test: `tests/test_batch_global_publication.py`
- Test: `tests/test_batch_state_reports.py`
- Test: `tests/test_batch_e2e.py`

**Interfaces:**
- Produces: `GlobalIconGap`, `GlobalResolvedIcon`, `GlobalAnonymousIcon`, and `GlobalEvidenceIndex`.
- Produces: `build_icon_candidate_bindings(evidence) -> tuple[IconCandidateEvidence, ...]` with only `exact_other_map_path` and `anonymous_hash_match` candidates and `adopted=False`.
- Produces: `collect_global_evidence(output_root, state) -> GlobalEvidenceIndex`; it reads only manifest-verified map publications selected by the supplied state.
- Produces: `format_global_icon_gaps_tsv()`, `parse_global_icon_gaps_tsv()`, `format_icon_candidates_tsv()`, `parse_icon_candidates_tsv()`, `format_icon_gap_statistics()`, and `format_axis_status_tsv()`.
- Produces: `GlobalPayloadBundle(payloads, evidence) = build_global_payloads(output_root, state, cache_text, diagnostics_text)`.
- Adds global payloads: `图标缺口汇总.tsv`, `图标候选绑定.tsv`, `图标缺口统计.txt`, and `三轴状态汇总.tsv`.
- Extends: `GlobalGeneration.evidence: GlobalEvidenceIndex`; GUI and acceptance load this already-validated index instead of reparsing compatibility mirrors.

- [ ] **Step 1: Write failing candidate tests that prove suggestions never resolve a gap**

```python
def test_exact_path_in_another_map_is_only_a_non_adopted_candidate() -> None:
    gap = GlobalIconGap(
        map_path="/maps/a.w3x",
        map_sha256="a" * 64,
        map_scope="root",
        normalized_path=r"Custom\BTNBlade.blp",
        reason=IconGapReason.NAMED_RESOURCE_MISSING,
        diagnostics=(),
        object_categories=("物品",),
        rawcodes=("I001",),
        references=(
            IconObjectReference(
                category="物品",
                object_id="I001",
                object_name="测试装备",
                base_id="ratf",
                map_path="/maps/a.w3x",
                map_sha256="a" * 64,
                map_scope="root",
                field_key="iico",
                field_label="图标",
                field_type="icon",
                field_source="war3map.w3t",
                wts_source="",
            ),
        ),
        reference_count=1,
    )
    resolved = GlobalResolvedIcon(
        map_path="/maps/b.w3x",
        map_sha256="b" * 64,
        normalized_path=r"Custom\BTNBlade.blp",
        layer=IconResolutionLayer.CURRENT_MAP,
        content_sha256="c" * 64,
        source_path="/maps/b.w3x",
    )
    evidence = GlobalEvidenceIndex.build((gap,), (resolved,), (), ())

    candidates = build_icon_candidate_bindings(evidence)

    assert len(candidates) == 1
    assert candidates[0].kind is IconCandidateKind.EXACT_OTHER_MAP_PATH
    assert candidates[0].adopted is False
    assert evidence.gaps == (gap,)


def test_anonymous_hash_match_has_no_unproved_requested_path() -> None:
    resolved = GlobalResolvedIcon(
        "/maps/b.w3x",
        "b" * 64,
        r"Custom\BTNBlade.blp",
        IconResolutionLayer.CURRENT_MAP,
        "c" * 64,
        "/maps/b.w3x",
    )
    anonymous = GlobalAnonymousIcon(
        "/maps/a.w3x",
        "a" * 64,
        17,
        "c" * 64,
        "/maps/a.w3x#block17",
    )
    evidence = GlobalEvidenceIndex.build((), (resolved,), (anonymous,), ())

    candidate = build_icon_candidate_bindings(evidence)[0]

    assert candidate.kind is IconCandidateKind.ANONYMOUS_HASH_MATCH
    assert candidate.requested_path == ""
    assert candidate.anonymous_block_index == 17
    assert candidate.adopted is False
```

- [ ] **Step 2: Run candidate tests and confirm no batch-wide candidate model exists**

Run: `uv run python -m pytest -q tests/test_icon_candidate_bindings.py`

Expected: FAIL on missing global evidence models and candidate builder.

- [ ] **Step 3: Implement closed candidate rules and deterministic global models**

```python
@dataclass(frozen=True, slots=True)
class GlobalEvidenceIndex:
    gaps: tuple[GlobalIconGap, ...]
    resolved: tuple[GlobalResolvedIcon, ...]
    anonymous: tuple[GlobalAnonymousIcon, ...]
    candidates: tuple[IconCandidateEvidence, ...]

    @classmethod
    def build(
        cls,
        gaps: Iterable[GlobalIconGap],
        resolved: Iterable[GlobalResolvedIcon],
        anonymous: Iterable[GlobalAnonymousIcon],
        candidates: Iterable[IconCandidateEvidence],
    ) -> GlobalEvidenceIndex:
        return cls(
            tuple(sorted(gaps, key=_gap_key)),
            tuple(sorted(resolved, key=_resolved_key)),
            tuple(sorted(anonymous, key=_anonymous_key)),
            tuple(sorted(candidates, key=_candidate_key)),
        )
```

`EXACT_OTHER_MAP_PATH` requires an exact case-folded normalized path, a different source-map digest, and a candidate resolution layer of `CURRENT_MAP` or `CAMPAIGN_ROOT`. `ANONYMOUS_HASH_MATCH` requires an exact SHA-256 match between an anonymous payload and a named payload; it leaves `requested_path` empty unless an independently exact path match exists. Self-matches, client/history/cache rows, empty digests, duplicate candidates, basename-only matches, and suffix-only matches are excluded.

`GlobalIconGap` stores map path/digest/scope, normalized path, enum reason/diagnostics, sorted categories/rawcodes, the complete `IconObjectReference` tuple parsed from canonical JSON, and its exact reference count. `GlobalResolvedIcon` and `GlobalAnonymousIcon` retain source map identity, content SHA-256, source path, and resolution layer or block index respectively.

- [ ] **Step 4: Write failing verified-aggregation and report-reconciliation tests**

```python
def test_global_evidence_reads_only_verified_map_publications(tmp_path: Path) -> None:
    state, first, second = _publish_two_empty_maps(tmp_path)
    evidence = collect_global_evidence(tmp_path, state)
    assert len(evidence.gaps) == sum(
        result.unresolved_icon_count for result in state.results
    )
    assert {row.map_sha256 for row in evidence.gaps} <= {
        first.source.sha256,
        second.source.sha256,
    }


def test_global_gap_rows_reconcile_paths_references_and_axes(tmp_path: Path) -> None:
    state, _first, _second = _publish_two_empty_maps(tmp_path)
    cache_text = format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE)
    bundle = build_global_payloads(tmp_path, state, cache_text, "")
    gaps = parse_global_icon_gaps_tsv(bundle.payloads["图标缺口汇总.tsv"])
    assert len(gaps) == sum(
        result.unresolved_icon_count for result in state.results
    )
    assert sum(row.reference_count for row in gaps) == sum(
        result.unresolved_icon_reference_count for result in state.results
    )
    assert bundle.payloads["三轴状态汇总.tsv"] == format_axis_status_tsv(state)


def _publish_two_empty_maps(
    output_root: Path,
) -> tuple[BatchState, MapBatchResult, MapBatchResult]:
    first_source = SourceFingerprint("/maps/a.w3x", 1, 1, "a" * 64)
    second_source = SourceFingerprint("/maps/b.w3x", 1, 1, "b" * 64)
    first = publish_empty_result(1, first_source, str(output_root))
    second = publish_empty_result(2, second_source, str(output_root))
    return BatchState(BATCH_SCHEMA_VERSION, (first, second)), first, second
```

The helper publishes real manifest-bound map directories through `tests.batch_publication_fixture.publish_empty_result()`; it must not bypass `verify_map_publication()` by constructing loose report files.
At this point the shared fixture is schema-5 authoritative: `write_empty_publication()` writes the canonical empty `图标未解析.tsv`, the split zero-valued `图标完整性.txt`, and every pre-existing required report before finalizing the manifest; `empty_result()` carries `PUBLISHED / COMPLETE / COMPLETE` axes and all split counters at zero. The aggregation tests must fail if any one of those required reports is omitted.

- [ ] **Step 5: Run aggregation tests and confirm global publication has only five legacy payloads**

Run: `uv run python -m pytest -q tests/test_batch_global_evidence.py tests/test_batch_global_publication.py tests/test_batch_e2e.py`

Expected: FAIL because `GLOBAL_PAYLOAD_NAMES` has no icon-gap or axis reports and `publish_global_generation()` never reads verified map evidence.

- [ ] **Step 6: Collect the global index from exact published reports**

```python
def collect_global_evidence(
    output_root: str | Path,
    state: BatchState,
) -> GlobalEvidenceIndex:
    root = Path(output_root)
    gaps: list[GlobalIconGap] = []
    resolved: list[GlobalResolvedIcon] = []
    anonymous: list[GlobalAnonymousIcon] = []
    for result in state.results:
        if result.publication_result is not PublicationResult.PUBLISHED:
            continue
        destination = safe_destination(root, result.output_directory)
        if destination is None:
            raise GlobalEvidenceError("unsafe map output directory")
        directory = Path(destination)
        validation = verify_map_publication(directory, result)
        if not validation.valid:
            raise GlobalEvidenceError(
                f"invalid map publication: {validation.code}"
            )
        gaps.extend(read_global_gap_rows(directory, result))
        named_rows, anonymous_rows = read_global_icon_rows(directory, result)
        resolved.extend(named_rows)
        anonymous.extend(anonymous_rows)
    base = GlobalEvidenceIndex.build(gaps, resolved, anonymous, ())
    candidates = build_icon_candidate_bindings(base)
    return GlobalEvidenceIndex.build(gaps, resolved, anonymous, candidates)
```

Both readers use the standard unlimited-field TSV decoder, exact headers, name-based columns, and the source digest from `MapBatchResult`; they reject malformed references, unknown enums, duplicate map/path gap rows, non-hex hashes, adopted candidates, and any count mismatch before global staging begins.

- [ ] **Step 7: Render canonical gap, candidate, statistics, and axis payloads**

```python
GLOBAL_ICON_GAP_HEADER: Final = (
    "地图路径",
    "地图SHA256",
    "子地图",
    "规范路径",
    "主原因",
    "诊断标志",
    "对象分类",
    "Rawcode",
    "引用数",
    "引用集合",
)
GLOBAL_ICON_CANDIDATE_HEADER: Final = (
    "候选类型",
    "请求地图SHA256",
    "请求路径",
    "匿名地图SHA256",
    "匿名块编号",
    "候选地图SHA256",
    "候选路径",
    "内容SHA256",
    "是否采用",
)
AXIS_STATUS_HEADER: Final = (
    "源路径",
    "地图名",
    "SHA256",
    "发布结果",
    "档案完整性",
    "知识证据完整性",
    "知识缺口原因",
    "有效图标引用",
    "已解析图标引用",
    "已过滤非图标字段",
    "具名未解析路径",
    "具名未解析引用",
    "关系部分",
    "受限块",
    "损坏块",
    "原始块",
)
```

`图标缺口统计.txt` emits explicit sections in this order: totals, primary reason, top-level namespace, extension, object category, and map. Every zero-valued enum reason is present. Prefix and extension grouping derives only from `normalized_path`; it never changes a path or candidate decision.

- [ ] **Step 8: Move global payload construction out of the near-limit publication module**

```python
@dataclass(frozen=True, slots=True)
class GlobalPayloadBundle:
    payloads: Mapping[str, str]
    evidence: GlobalEvidenceIndex


def build_global_payloads(
    output_root: str | Path,
    state: BatchState,
    cache_text: str,
    diagnostics_text: str,
) -> GlobalPayloadBundle:
    evidence = collect_global_evidence(output_root, state)
    payloads = {
        "批量提取汇总.tsv": format_batch_summary_tsv(state),
        "批量提取状态.json": format_batch_state_json(state),
        "失败与重试.tsv": format_retry_tsv(state),
        "可信描述缓存.tsv": cache_text,
        "批量诊断.jsonl": diagnostics_text,
        "图标缺口汇总.tsv": format_global_icon_gaps_tsv(evidence),
        "图标候选绑定.tsv": format_icon_candidates_tsv(evidence),
        "图标缺口统计.txt": format_icon_gap_statistics(evidence, state),
        "三轴状态汇总.tsv": format_axis_status_tsv(state),
    }
    return GlobalPayloadBundle(MappingProxyType(payloads), evidence)
```

`batch_global_publication.py` calls this before creating the stage and uses the returned mapping for manifest, pointer, and compatibility mirrors. This extraction keeps the publication module below 250 pure LOC. A failed map result contributes an axis row but no map-report evidence.

- [ ] **Step 9: Make global validation reconstruct and reconcile the same index**

Add all four names to `GLOBAL_PAYLOAD_NAMES`. Validation parses both TSV evidence payloads, rejects `是否采用 != 否`, rebuilds `GlobalEvidenceIndex`, re-renders all four reports byte-for-byte, and checks path/reference totals against the parsed schema-5 state. Return that index in `GlobalGeneration.evidence`. `require_authoritative_batch()` additionally verifies that the generation index equals a fresh `collect_global_evidence()` result from the exact manifest-bound map directories.

- [ ] **Step 10: Re-run global, state, end-to-end, and static gates**

Run: `uv run python -m pytest -q tests/test_icon_candidate_bindings.py tests/test_batch_global_evidence.py tests/test_batch_global_publication.py tests/test_batch_state_reports.py tests/test_batch_e2e.py tests/test_batch_resume_loading.py tests/test_batch_map_retirement_safety.py`

Run: `uv run --with ruff ruff check w3xtool/icon_candidate_bindings.py w3xtool/batch_global_evidence_models.py w3xtool/batch_global_evidence.py w3xtool/batch_global_evidence_reports.py w3xtool/batch_global_payloads.py w3xtool/batch_global_models.py w3xtool/batch_global_publication.py w3xtool/batch_global_validation.py`

Run: `uv run --with basedpyright basedpyright --level error w3xtool/icon_candidate_bindings.py w3xtool/batch_global_evidence_models.py w3xtool/batch_global_evidence.py w3xtool/batch_global_evidence_reports.py w3xtool/batch_global_payloads.py w3xtool/batch_global_models.py w3xtool/batch_global_publication.py w3xtool/batch_global_validation.py`

Run: `awk '!/^[[:space:]]*$/ && !/^[[:space:]]*#/' w3xtool/batch_global_publication.py | wc -l`

Expected: all tests/static gates PASS and `batch_global_publication.py` is at most 190 pure LOC.

- [ ] **Step 11: Commit authoritative global evidence**

```bash
git add w3xtool/icon_candidate_bindings.py w3xtool/batch_global_evidence_models.py w3xtool/batch_global_evidence.py w3xtool/batch_global_evidence_reports.py w3xtool/batch_global_payloads.py w3xtool/batch_global_models.py w3xtool/batch_global_publication.py w3xtool/batch_global_validation.py w3xtool/batch_checkpoint_publication.py w3xtool/batch_global_reports.py w3xtool/acceptance_batch.py tests/test_icon_candidate_bindings.py tests/test_batch_global_evidence.py tests/test_batch_global_publication.py tests/test_batch_state_reports.py tests/test_batch_e2e.py
git commit -m "feat: publish reconciled global icon evidence"
```

---

### Task 9: GUI icon-gap workspace, complete-text controls, and three-axis batch view

**Files:**
- Create: `w3xtool/icon_evidence_query.py`
- Create: `w3xtool/icon_evidence_presentation.py`
- Create: `w3xtool/gui_icon_gap_layout.py`
- Create: `w3xtool/gui_icon_gaps.py`
- Create: `w3xtool/gui_batch_status_layout.py`
- Create: `w3xtool/gui_batch_status.py`
- Create: `w3xtool/gui_object_text_controls.py`
- Modify: `w3xtool/icons.py:47-138`
- Modify: `w3xtool/gui_loader.py:48-272`
- Modify: `w3xtool/gui.py:12-106`
- Modify: `w3xtool/gui_shell.py:35-213`
- Modify: `w3xtool/gui_module_refresh.py:20-92`
- Modify: `w3xtool/gui_object_detail.py:18-89`
- Modify: `w3xtool/object_text_presentation.py:8-48`
- Modify: `w3xtool/gui_acceptance.py:22-43`
- Test: `tests/test_icon_evidence_query.py`
- Test: `tests/test_gui_icon_gaps.py`
- Test: `tests/test_gui_batch_status.py`
- Test: `tests/test_gui_object_presentation.py`
- Test: `tests/test_gui_layout.py`
- Test: `tests/test_gui_loader.py`
- Test: `tests/test_gui_loader_runner.py`
- Test: `tests/test_acceptance_runner.py`

**Interfaces:**
- Produces: `IconGapViewRow`, `IconGapFilter`, `map_icon_gap_rows(index)`, `global_icon_gap_rows(index)`, and `filter_icon_gap_rows(rows, criteria)`.
- Produces: `format_icon_gap_evidence(row)` and `format_object_icon_evidence_section(md, obj)`.
- Adds GUI tabs: `图标缺口` and `批量状态`; both use existing bounded GUI worker registration and Tk-main-thread callbacks.
- Adds: `PreparedIconResolver.build_evidence_index(md) -> IconEvidenceIndex` and `IconResolver.build_evidence_index(md) -> IconEvidenceIndex`; normal GUI loads populate `MapData.icon_evidence` through the same strict builder as batch processing while `get_image()` remains a browsing-only decoder.
- Produces: `ObjectTextView.CURRENT` / `ObjectTextView.ALL`, `records_for_text_view()`, and `format_complete_text_section(md, obj, view)`.
- Produces: `BatchStatusRow`, `BatchStatusSnapshot`, `load_batch_status(root)`, and `batch_status_rows(state)` from a validated global generation.

- [ ] **Step 1: Write failing pure query tests for map gaps and non-adopted candidates**

```python
def test_icon_gap_filter_matches_reason_category_rawcode_and_path() -> None:
    rows = (
        IconGapViewRow(
            row_id="gap:a",
            map_path="/maps/a.w3x",
            map_sha256="a" * 64,
            reason="historical_client_miss",
            category="物品",
            rawcode="I001",
            path=r"Custom\BTNBlade.blp",
            archive_status="存在原始块",
            reference_count=2,
            candidate=False,
            adopted=False,
            object_identity=("物品", "I001"),
            detail="完整字段证据",
        ),
    )
    criteria = IconGapFilter(
        query="BTNBlade I001",
        reason="historical_client_miss",
        category="物品",
        archive_status="存在原始块",
        show_candidates=False,
    )
    assert filter_icon_gap_rows(rows, criteria) == rows


def test_candidate_filter_never_changes_gap_rows_or_adoption() -> None:
    candidate = IconGapViewRow(
        "candidate:a",
        "/maps/a.w3x",
        "a" * 64,
        "exact_other_map_path",
        "",
        "",
        r"Custom\BTNBlade.blp",
        "",
        0,
        True,
        False,
        None,
        "候选未采用",
    )
    shown = filter_icon_gap_rows(
        (candidate,),
        IconGapFilter("", "全部", "全部", "全部", True),
    )
    assert shown == (candidate,)
    assert shown[0].adopted is False
```

- [ ] **Step 2: Run pure query tests and confirm no icon-gap presentation layer exists**

Run: `uv run python -m pytest -q tests/test_icon_evidence_query.py`

Expected: FAIL on missing view-row/query modules.

- [ ] **Step 3: Implement immutable row projections and exact filtering**

```python
@dataclass(frozen=True, slots=True)
class IconGapFilter:
    query: str
    reason: str
    category: str
    archive_status: str
    show_candidates: bool


def filter_icon_gap_rows(
    rows: Iterable[IconGapViewRow],
    criteria: IconGapFilter,
) -> tuple[IconGapViewRow, ...]:
    compiled = compile_query(criteria.query.strip())
    visible: list[IconGapViewRow] = []
    for row in rows:
        if row.candidate is not criteria.show_candidates:
            continue
        if criteria.reason != "全部" and row.reason != criteria.reason:
            continue
        if criteria.category != "全部" and row.category != criteria.category:
            continue
        if (
            criteria.archive_status != "全部"
            and row.archive_status != criteria.archive_status
        ):
            continue
        blob = " ".join(
            (row.map_path, row.reason, row.category, row.rawcode, row.path, row.detail)
        )
        if criteria.query and compiled.score(blob) is None:
            continue
        visible.append(row)
    return tuple(visible)
```

`map_icon_gap_rows()` expands each unresolved reference into a searchable row without discarding its path-level reason. `global_icon_gap_rows()` emits gap rows plus separate candidate rows with `candidate=True`, `adopted=False`, and an empty object identity unless the global report retained one exact current-map reference.

- [ ] **Step 4: Write failing GUI-load tests for the strict evidence index**

```python
class FakeEvidenceResolver:
    def __init__(self, index: IconEvidenceIndex) -> None:
        self.index = index
        self.evidence_calls: list[MapData] = []

    def build_evidence_index(self, md: MapData) -> IconEvidenceIndex:
        self.evidence_calls.append(md)
        return self.index

    def get_image(self, _path: str) -> None:
        return None

    def close(self) -> None:
        return None


def test_default_icon_resolver_builds_map_evidence_before_returning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = MapData(str(tmp_path / "map.w3x"), "map")
    expected = IconEvidenceIndex.build()
    resolver = FakeEvidenceResolver(expected)
    monkeypatch.setattr(gui_loader, "IconResolver", lambda *_args, **_kwargs: resolver)

    loaded = gui_loader.build_icon_resolver(md, None, None)

    assert loaded is resolver
    assert md.icon_evidence is expected
    assert resolver.evidence_calls == [md]
```

The fake retains the existing resolver protocol and makes the evidence call observable without opening an archive.

- [ ] **Step 5: Add strict evidence construction to the existing resolver lifecycle**

`IconResolver.build_evidence_index(md)` wraps its current-map archive as `CURRENT_MAP`, each campaign extra archive as `CAMPAIGN_ROOT`, and its explicit game source as the client layer, then calls `build_icon_evidence_index()`. It never calls browsing `get_image()`, `_load()`, basename fallback, or process-global `_games()`. Extend `PreparedIconResolver` and every loader-test resolver double with the same method. `prepare_map_view()` always creates/loads a resolver and calls `build_evidence_index(md)` because the gap tab is independent of the optional object-browser module; it retains the resolver only when object browsing is enabled and otherwise closes it immediately after assigning `MapData.icon_evidence`. A custom `resolver_loader` follows the same protocol in both modes. Failure is isolated by the existing worker boundary and leaves the shared empty index.

- [ ] **Step 6: Write failing current/all text and exact-copy presentation tests**

```python
def test_complete_text_current_view_excludes_only_lower_priority_rows() -> None:
    current = _text_record(
        "地图当前值",
        700,
        True,
        TextSelectionReason.HIGHEST_PRIORITY_VALUE,
        1,
        "war3map.w3a",
    )
    lower = _text_record(
        "SLK旧值",
        400,
        False,
        TextSelectionReason.LOWER_PRIORITY,
        2,
        "Units\\AbilityData.slk",
    )
    md, obj = _map_with_text_records((current, lower))
    current = format_complete_text_section(md, obj, ObjectTextView.CURRENT)
    all_evidence = format_complete_text_section(md, obj, ObjectTextView.ALL)
    assert "地图当前值" in current
    assert "SLK旧值" not in current
    assert "地图当前值" in all_evidence
    assert "SLK旧值" in all_evidence
    assert "低优先级证据" in all_evidence


def test_copy_text_payload_preserves_raw_newlines_tabs_and_color_codes() -> None:
    raw = "|cffff0000第一行|r\n第二行\t字段"
    md, obj = _map_with_text_records(
        (
            _text_record(
                raw,
                700,
                True,
                TextSelectionReason.HIGHEST_PRIORITY_VALUE,
                1,
                "war3map.w3a",
            ),
        )
    )
    payload = format_complete_text_section(md, obj, ObjectTextView.ALL)
    assert "|cffff0000第一行|r\n第二行\t字段" in payload
    assert "第一行\n第二行\t字段" in payload


def _text_record(
    raw: str,
    priority: int,
    is_current: bool,
    reason: TextSelectionReason,
    ordinal: int,
    source_path: str,
) -> ObjectTextRecord:
    return ObjectTextRecord(
        category="技能",
        object_id="A001",
        base_id="AHbz",
        object_name="暴风雪",
        is_custom=True,
        role="扩展提示",
        field_key="aub1",
        field_label="提示工具 - 扩展",
        level=1,
        raw_value=raw,
        readable_value=readable_text(raw),
        source_kind="地图文本字符串" if priority == 700 else "地图SLK",
        source_path=source_path,
        state=ObjectTextState.MAP_VALUE,
        placeholder=False,
        conflict_group="",
        evidence_ordinal=ordinal,
        semantic_field="ubertip",
        source_priority=priority,
        is_current=is_current,
        selection_reason=reason,
    )


def _map_with_text_records(
    records: tuple[ObjectTextRecord, ...],
) -> tuple[MapData, GameObject]:
    obj = GameObject("技能", "w3a", "A001", "AHbz", "暴风雪", True)
    md = MapData("map.w3x", "map", object_texts=ObjectTextIndex.build(records))
    return md, obj
```

The helper creates `ObjectTextIndex` records with explicit `is_current`, `selection_reason`, raw/readable values, and priorities; it does not mock the formatter.

- [ ] **Step 7: Implement text-view selection and complete detail controls**

```python
class ObjectTextView(StrEnum):
    CURRENT = "当前文本"
    ALL = "全部证据"


def records_for_text_view(
    records: tuple[ObjectTextRecord, ...],
    view: ObjectTextView,
) -> tuple[ObjectTextRecord, ...]:
    if view is ObjectTextView.ALL:
        return records
    return tuple(record for record in records if record.is_current)
```

Add a segmented `当前文本 / 全部证据` control and a `复制完整文本` button above the existing scrollable detail box. `_show_detail()` stores the exact selected object, then one `_render_selected_object_detail()` path renders summary, strict icon evidence, the selected complete-text view, all fields, references, and item relations. The copy button places exactly `format_complete_text_section(md, obj, selected_view)` on the clipboard; it does not read a visible selection or a truncated preview.

- [ ] **Step 8: Build the searchable icon-gap tab and object navigation**

The layout contains search, reason/category/archive filters, an `未解析 / 候选（未采用）` segmented control, a horizontally and vertically scrollable tree, a full evidence textbox with existing copy-all context action, and an `打开对象` button. Double-click and the button resolve only `row.object_identity` through `obj_identity_index`, switch to `对象编辑器`, select its category, and call `_show_detail()`. Candidate rows are styled separately, display `未采用`, and expose no mutation command.

- [ ] **Step 9: Write failing validated batch-status tests**

```python
def test_batch_status_rows_expose_three_independent_axes() -> None:
    source = SourceFingerprint("/maps/a.w3x", 1, 1, "a" * 64)
    result = replace(
        empty_result(source, "地图/001_a"),
        publication_result=PublicationResult.PUBLISHED,
        archive_integrity=ArchiveIntegrity.COMPLETE,
        knowledge_evidence=KnowledgeEvidence.PARTIAL,
        knowledge_gap_reasons=(KnowledgeGapReason.ICON_UNBOUND,),
        unresolved_icon_count=1,
        unresolved_icon_reference_count=1,
        valid_icon_reference_count=1,
    )

    rows = batch_status_rows(BatchState(BATCH_SCHEMA_VERSION, (result,)))

    assert rows[0].publication == "已发布"
    assert rows[0].archive == "完整"
    assert rows[0].knowledge == "部分"
    assert rows[0].knowledge_reasons == ("图标未绑定",)


def test_batch_status_loader_uses_a_validated_generation(tmp_path: Path) -> None:
    source = SourceFingerprint("/maps/a.w3x", 1, 1, "a" * 64)
    result = publish_empty_result(1, source, str(tmp_path))
    state = BatchState(BATCH_SCHEMA_VERSION, (result,))
    cache_text = format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE)
    generation = publish_global_generation(tmp_path, state, cache_text, "")

    snapshot = load_batch_status(tmp_path)

    assert snapshot.generation.generation_id == generation.generation_id
    assert snapshot.rows[0].publication == "已发布"


def test_batch_status_loader_rejects_an_invalid_current_pointer(tmp_path: Path) -> None:
    (tmp_path / ".w3xray-global").mkdir()
    with pytest.raises(BatchStatusLoadError, match="validated generation"):
        load_batch_status(tmp_path)
```

The loader test first publishes the matching manifest-bound empty map reports and then calls the real global publication API; the pure row test covers the independent partial-knowledge combination without weakening publication validation.

- [ ] **Step 10: Build the batch-status tab on the shared GUI worker host**

```python
@dataclass(frozen=True, slots=True)
class BatchStatusSnapshot:
    root: Path
    generation: GlobalGeneration
    rows: tuple[BatchStatusRow, ...]


def load_batch_status(root: str | Path) -> BatchStatusSnapshot:
    selected = Path(root).expanduser()
    if selected.is_symlink():
        raise BatchStatusLoadError("batch output root is a symlink")
    normalized = selected.resolve(strict=True)
    generation = load_current_generation(normalized)
    if generation is None:
        raise BatchStatusLoadError("validated generation is unavailable")
    return BatchStatusSnapshot(
        normalized,
        generation,
        batch_status_rows(generation.state),
    )
```

The tab's `选择批量结果` action uses `askdirectory()`, starts worker group `batch-status`, and posts a typed success/error payload through `_post_gui_worker()`. The tree columns are map, publication, archive, knowledge, reasons, unresolved paths/references, filtered fields, relation-partial count, raw/damaged/restricted blocks. On success, the same generation evidence populates the icon-gap tab's batch-wide rows; changing back to current-map scope restores `MapData.icon_evidence` rows.

- [ ] **Step 11: Wire the two tabs without growing the shell into a controller**

Add `IconGapGuiMixin` and `BatchStatusGuiMixin` to `App`, initialize their state through explicit hooks, add `图标缺口` and `批量状态` to `editor_tab_labels`, and delegate only `_build_icon_gap_tab()` / `_build_batch_status_tab()` from `gui_shell.py`. `ModuleRefreshMixin` calls `_refresh_icon_gaps()` after map load. `run_gui_acceptance()` continues iterating `editor_tab_labels`, so both tabs become mandatory source/packaged acceptance surfaces.

- [ ] **Step 12: Run GUI, query, loader, acceptance, and static gates**

Run: `uv run python -m pytest -q tests/test_icon_evidence_query.py tests/test_gui_icon_gaps.py tests/test_gui_batch_status.py tests/test_gui_object_presentation.py tests/test_gui_layout.py tests/test_gui_loader.py tests/test_gui_loader_runner.py tests/test_acceptance_runner.py`

Run: `uv run --with ruff ruff check w3xtool/icon_evidence_query.py w3xtool/icon_evidence_presentation.py w3xtool/gui_icon_gap_layout.py w3xtool/gui_icon_gaps.py w3xtool/gui_batch_status_layout.py w3xtool/gui_batch_status.py w3xtool/gui_object_text_controls.py w3xtool/icons.py w3xtool/gui_loader.py w3xtool/gui.py w3xtool/gui_shell.py w3xtool/gui_module_refresh.py w3xtool/gui_object_detail.py w3xtool/object_text_presentation.py`

Run: `uv run --with basedpyright basedpyright --level error w3xtool/icon_evidence_query.py w3xtool/icon_evidence_presentation.py w3xtool/gui_icon_gap_layout.py w3xtool/gui_icon_gaps.py w3xtool/gui_batch_status_layout.py w3xtool/gui_batch_status.py w3xtool/gui_object_text_controls.py w3xtool/icons.py w3xtool/gui_loader.py w3xtool/gui_object_detail.py w3xtool/object_text_presentation.py`

Expected: PASS; every new GUI module is at most 250 pure LOC and `gui_shell.py` remains at most 240 pure LOC.

- [ ] **Step 13: Commit the complete GUI evidence surfaces**

```bash
git add w3xtool/icon_evidence_query.py w3xtool/icon_evidence_presentation.py w3xtool/gui_icon_gap_layout.py w3xtool/gui_icon_gaps.py w3xtool/gui_batch_status_layout.py w3xtool/gui_batch_status.py w3xtool/gui_object_text_controls.py w3xtool/icons.py w3xtool/gui_loader.py w3xtool/gui.py w3xtool/gui_shell.py w3xtool/gui_module_refresh.py w3xtool/gui_object_detail.py w3xtool/object_text_presentation.py w3xtool/gui_acceptance.py tests/test_icon_evidence_query.py tests/test_gui_icon_gaps.py tests/test_gui_batch_status.py tests/test_gui_object_presentation.py tests/test_gui_layout.py tests/test_gui_loader.py tests/test_gui_loader_runner.py tests/test_acceptance_runner.py
git commit -m "feat: expose icon and text evidence in GUI"
```

---

### Task 10: Integrity snapshots, release metadata, workflow, and operator documentation

**Files:**
- Create: `w3xtool/integrity_snapshot_models.py`
- Create: `w3xtool/integrity_snapshot.py`
- Create: `w3xtool/integrity_snapshot_io.py`
- Create: `w3xtool/integrity_cli.py`
- Create: `tests/test_integrity_snapshot.py`
- Create: `tests/test_integrity_cli.py`
- Modify: `main.py:15-76`
- Modify: `w3xtool/__init__.py:1-4`
- Modify: `w3xtool/quality_gate.py:10-170`
- Modify: `tests/test_quality_gate.py:12-139`
- Modify: `tests/test_release_metadata.py:10-74`
- Modify: `tests/test_posix_package_assets.py:11-86`
- Modify: `pyproject.toml:1-45`
- Modify: `uv.lock`
- Modify: `.github/workflows/posix-package.yml:5-13`
- Modify: `README.md`
- Modify: `docs/batch-icon-description-extraction.md`
- Modify: `AGENTS.md`
- Modify: `AGENTS.d/runtime.md`
- Modify: `AGENTS.d/testing.md`

**Interfaces:**
- Produces CLI: `uv run main.py integrity snapshot --root LABEL=PATH [--root LABEL=PATH] --output FILE`.
- Produces CLI: `uv run main.py integrity verify --snapshot FILE`.
- Produces: `SnapshotRoot`, `IntegrityEntry`, `IntegrityRoot`, `IntegritySnapshot`, `IntegrityDifference`, `build_integrity_snapshot(roots)`, `format_integrity_snapshot()`, `parse_integrity_snapshot()`, and `compare_integrity_snapshot(expected, actual)`.
- Sets project/runtime/release documentation to `0.1.4`; schema/revision documentation to `5`.
- Keeps all generated acceptance output outside the repository and all four input roots read-only.

- [ ] **Step 1: Write failing deterministic snapshot and mutation tests**

```python
def test_integrity_snapshot_records_path_size_mtime_and_content(tmp_path: Path) -> None:
    root = tmp_path / "maps"
    root.mkdir()
    source = root / "a.w3x"
    source.write_bytes(b"map")
    os.utime(source, ns=(1_700_000_000_000_000_000,) * 2)

    snapshot = build_integrity_snapshot((SnapshotRoot("maps", root),))

    entry = snapshot.roots[0].entries[0]
    assert entry.relative_path == "a.w3x"
    assert entry.size == 3
    assert entry.mtime_ns == 1_700_000_000_000_000_000
    assert entry.sha256 == hashlib.sha256(b"map").hexdigest()
    assert parse_integrity_snapshot(format_integrity_snapshot(snapshot)) == snapshot


def test_integrity_comparison_reports_content_and_metadata_changes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    root.mkdir()
    source = root / "report.tsv"
    source.write_text("first", encoding="utf-8")
    before = build_integrity_snapshot((SnapshotRoot("history", root),))
    source.write_text("other", encoding="utf-8")
    after = build_integrity_snapshot((SnapshotRoot("history", root),))

    differences = compare_integrity_snapshot(before, after)

    assert differences[0].code == "file_changed"
    assert differences[0].root_label == "history"
    assert differences[0].relative_path == "report.tsv"
```

- [ ] **Step 2: Run snapshot tests and confirm no reusable tree-integrity API exists**

Run: `uv run python -m pytest -q tests/test_integrity_snapshot.py`

Expected: FAIL on missing snapshot models and builder.

- [ ] **Step 3: Implement stable no-follow tree hashing**

```python
def build_integrity_snapshot(
    roots: tuple[SnapshotRoot, ...],
) -> IntegritySnapshot:
    if not roots:
        raise IntegritySnapshotError("at least one root is required")
    labels: set[str] = set()
    root_paths: list[Path] = []
    normalized_roots: list[IntegrityRoot] = []
    for item in roots:
        if not item.label or item.label in labels:
            raise IntegritySnapshotError("root labels must be unique and nonempty")
        labels.add(item.label)
        root = item.path.expanduser().resolve(strict=True)
        if item.path.is_symlink() or not root.is_dir():
            raise IntegritySnapshotError(f"unsafe root: {item.path}")
        if any(
            root == previous
            or root.is_relative_to(previous)
            or previous.is_relative_to(root)
            for previous in root_paths
        ):
            raise IntegritySnapshotError("snapshot roots overlap")
        root_paths.append(root)
        entries = _scan_integrity_root(root)
        normalized_roots.append(
            IntegrityRoot(
                item.label,
                str(root),
                entries,
                sum(entry.size for entry in entries),
                _tree_sha256(entries),
            )
        )
    return IntegritySnapshot(
        INTEGRITY_SNAPSHOT_SCHEMA,
        tuple(sorted(normalized_roots, key=lambda value: value.label)),
    )
```

`_scan_integrity_root()` uses `os.walk(..., followlinks=False)`, rejects every symlink and non-regular file, sorts directory/file names by `(casefold, original)`, hashes through `sha256_regular_file()`, and compares `lstat()` device/inode/size/mtime before and after hashing. `_tree_sha256()` hashes canonical JSON tuples of relative path, size, mtime-ns, and file SHA-256. The parser requires exact keys, schema `1`, absolute nonoverlapping roots, safe relative paths, nonnegative integers, lowercase hashes, unique case-folded paths, exact file/byte totals, and a recomputed tree digest.

- [ ] **Step 4: Write failing CLI safety and exit-code tests**

```python
def test_integrity_cli_snapshots_then_verifies_exact_roots(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "maps"
    root.mkdir()
    (root / "a.w3x").write_bytes(b"map")
    snapshot = tmp_path / "before.json"
    assert run_integrity_cli(
        ("snapshot", "--root", f"maps={root}", "--output", str(snapshot))
    ) == 0
    assert run_integrity_cli(("verify", "--snapshot", str(snapshot))) == 0
    assert "完整性验证通过" in capsys.readouterr().out


def test_integrity_cli_returns_one_for_a_changed_input(tmp_path: Path) -> None:
    root = tmp_path / "history"
    root.mkdir()
    source = root / "state.json"
    source.write_text("first", encoding="utf-8")
    snapshot = tmp_path / "before.json"
    assert run_integrity_cli(
        ("snapshot", "--root", f"history={root}", "--output", str(snapshot))
    ) == 0
    source.write_text("second", encoding="utf-8")
    assert run_integrity_cli(("verify", "--snapshot", str(snapshot))) == 1
```

Parse/schema/path errors return `2`; a valid snapshot with differences returns `1`; exact equality returns `0`. Snapshot publication uses `write_text_safely()` in the output file's parent, rejects an output inside any snapshotted root, and never deletes or normalizes an input.

- [ ] **Step 5: Add the two explicit `integrity` actions to `main.py`**

Retain the `description-cache` dispatch introduced in Task 5, and add the sibling `integrity` dispatch using `run_integrity_cli()` before legacy map CLI handling. Both receive `tuple(sys.argv[2:])`; both own their typed diagnostics and process exit codes. No command searches for user directories implicitly.

- [ ] **Step 6: Run integrity CLI tests and focused static gates**

Run: `uv run python -m pytest -q tests/test_integrity_snapshot.py tests/test_integrity_cli.py tests/test_cli_options.py`

Run: `uv run --with ruff ruff check w3xtool/integrity_snapshot_models.py w3xtool/integrity_snapshot.py w3xtool/integrity_snapshot_io.py w3xtool/integrity_cli.py main.py`

Run: `uv run --with basedpyright basedpyright --level error w3xtool/integrity_snapshot_models.py w3xtool/integrity_snapshot.py w3xtool/integrity_snapshot_io.py w3xtool/integrity_cli.py main.py`

- [ ] **Step 7: Write failing version, workflow, and quality-gate assertions**

Set the release test constant and expected asset names to `0.1.4`; set the POSIX workflow test to require `default: v0.1.4`; extend `test_quality_gate_covers_audit_gap_core_modules()` with every new hand-written Python module and focused test from Tasks 1–10. Run these tests before changing metadata:

Run: `uv run python -m pytest -q tests/test_release_metadata.py tests/test_posix_package_assets.py tests/test_quality_gate.py`

Expected: FAIL on `0.1.3`, the old workflow input default, and missing strict paths.

- [ ] **Step 8: Update version authorities and regenerate the lockfile**

Change `pyproject.toml` and `w3xtool/__init__.py` to `0.1.4`, change `.github/workflows/posix-package.yml`'s manual default to `v0.1.4`, then run:

Run: `uv lock`

Expected: the editable `w3xray` package in `uv.lock` is exactly `0.1.4` and no unrelated dependency version changes are introduced.

- [ ] **Step 9: Update the maintained quality authority**

Remove the Task 6 deleted `w3xtool/batch_description_cache.py` and `w3xtool/description_cache_batch.py` paths, then add all created/modified Python modules and their focused tests from this plan to `STRICT_PATHS`. Preserve one sorted duplicate-free tuple and all three commands (`ruff check`, `ruff format --check`, `basedpyright --level error`). Do not add new files to `tool.basedpyright.ignore`.

- [ ] **Step 10: Document schema 5 commands and evidence semantics**

Update README release assets to `0.1.4` and document:

```text
uv run main.py description-cache migrate --legacy-output <schema-1-root> --legacy-cache <schema-2-cache.tsv> --output <owned-cache-root>
uv run main.py batch <maps-root> --output <v5-root> --game-data <client-or-trusted-icon-root> --description-cache <owned-cache-root>
uv run main.py integrity snapshot --root maps=<maps-root> --root legacy-v1=<root> --root legacy-v2=<root> --root legacy-v4=<root> --output <before.json>
uv run main.py integrity verify --snapshot <before.json>
```

Explain the four new global reports, `图标未解析.tsv`, current/all text views, candidate non-adoption, and the publication/archive/knowledge axes. Update `docs/batch-icon-description-extraction.md` from current schema 4 behavior to the schema 5 contracts without rewriting historical observed counts as if they were v5 results. Update `AGENTS.md` orientation/commands and keep it under 120 lines; update `AGENTS.d/runtime.md` and `AGENTS.d/testing.md` with only verified commands, read-only roots, output roots, required reports, and acceptance invariants.

- [ ] **Step 11: Re-run metadata, docs, quality, and focused integration tests**

Run: `uv run python -m pytest -q tests/test_integrity_snapshot.py tests/test_integrity_cli.py tests/test_release_metadata.py tests/test_posix_package_assets.py tests/test_quality_gate.py tests/test_batch_dependencies.py tests/test_batch_e2e.py tests/test_acceptance_runner.py`

Run: `uv run w3xray-quality`

Expected: PASS; `git diff --check` reports no whitespace errors, `AGENTS.md` is at most 120 lines, and no generated output directory is tracked.

- [ ] **Step 12: Commit the operator and release boundary**

```bash
git add main.py w3xtool/integrity_snapshot_models.py w3xtool/integrity_snapshot.py w3xtool/integrity_snapshot_io.py w3xtool/integrity_cli.py w3xtool/__init__.py w3xtool/quality_gate.py tests/test_integrity_snapshot.py tests/test_integrity_cli.py tests/test_quality_gate.py tests/test_release_metadata.py tests/test_posix_package_assets.py pyproject.toml uv.lock .github/workflows/posix-package.yml README.md docs/batch-icon-description-extraction.md AGENTS.md AGENTS.d/runtime.md AGENTS.d/testing.md
git commit -m "feat: add schema five integrity acceptance tools"
```

---

### Task 11: Full regression, cache migration, 39-map v5 publication, and reuse proof

**Files:**
- Create: `tests/test_real_map_schema5_acceptance.py`
- Modify: `tests/test_real_map_item_relation_acceptance.py:1-150`
- Modify: `w3xtool/quality_gate.py:10-190`
- Modify: `tests/test_quality_gate.py:45-130`
- Test inputs, read-only: `/Users/zhongerbing/Desktop/Maps`
- Historical evidence, read-only: `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output`
- Historical evidence, read-only: `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2`
- Historical evidence, read-only: `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v4`
- Existing trusted icon input, read-only: `/Users/zhongerbing/Documents/xm/war3_xg/trusted-icon-cache-classic`
- New owned cache output: `/Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5`
- New batch output: `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v5`
- Integrity evidence output: `/Users/zhongerbing/Documents/xm/war3_xg/schema5-input-integrity.json`
- Cache integrity evidence output: `/Users/zhongerbing/Documents/xm/war3_xg/schema5-cache-integrity.json`

**Interfaces:**
- Adds an opt-in real-data acceptance module gated by `W3XRAY_MAPS_ROOT`, `W3XRAY_V4_OUTPUT`, `W3XRAY_V5_OUTPUT`, and `W3XRAY_DESCRIPTION_CACHE`.
- Reuses `require_authoritative_batch()`, the standard TSV decoder, trusted-cache loader, schema-5 state models, and integrity CLI; it does not implement parallel acceptance-only parsers.
- Requires first-run progress to contain 39 `processed` results and the immediate identical run to contain 39 `reused` results.
- Produces no tracked generated data; the cache, batch output, logs, and integrity snapshot remain outside the repository.

- [ ] **Step 1: Write the opt-in real-data assertions before running the new batch**

```python
pytestmark = pytest.mark.skipif(
    not all(os.environ.get(name) for name in _ENV_NAMES),
    reason=(
        "set W3XRAY_MAPS_ROOT/W3XRAY_V4_OUTPUT/"
        "W3XRAY_V5_OUTPUT/W3XRAY_DESCRIPTION_CACHE"
    ),
)


@dataclass(frozen=True, slots=True)
class Schema5Context:
    maps: tuple[Path, ...]
    authority: AuthoritativeBatch
    generation: GlobalGeneration
    results: tuple[MapBatchResult, ...]
    v4_by_digest: Mapping[str, Path]
    new_by_digest: Mapping[str, Path]
    description_cache: VerifiedDescriptionCache


@pytest.fixture(scope="module")
def schema5_context() -> Schema5Context:
    maps_root = Path(os.environ["W3XRAY_MAPS_ROOT"])
    v4_root = Path(os.environ["W3XRAY_V4_OUTPUT"])
    v5_root = Path(os.environ["W3XRAY_V5_OUTPUT"])
    maps = tuple(
        sorted(
            (
                path
                for path in maps_root.rglob("*")
                if path.is_file()
                and path.suffix.casefold() in {".w3x", ".w3m", ".w3n"}
            ),
            key=lambda path: str(path).casefold(),
        )
    )
    authority = require_authoritative_batch(v5_root)
    generation = authority.generation
    results = generation.state.results
    v4_summary = read_tsv(v4_root / "批量提取汇总.tsv")
    v4_by_digest = {
        v4_summary.value(row, "SHA256"):
        v4_root / v4_summary.value(row, "输出目录")
        for row in v4_summary.rows
    }
    new_by_digest = {
        result.source.sha256: directory
        for result, directory in authority.publications
    }
    cache = load_trusted_description_cache(
        Path(os.environ["W3XRAY_DESCRIPTION_CACHE"])
    )
    return Schema5Context(
        maps,
        authority,
        generation,
        results,
        MappingProxyType(v4_by_digest),
        MappingProxyType(new_by_digest),
        cache,
    )


def test_schema_five_publishes_all_sources_with_independent_axes(
    schema5_context: Schema5Context,
) -> None:
    context = schema5_context
    assert BATCH_SCHEMA_VERSION == 5
    assert len(context.maps) == len(context.authority.publications) == 39
    assert all(
        result.publication_result is PublicationResult.PUBLISHED
        for result, _directory in context.authority.publications
    )
    assert all(result.original_write_failure_count == 0 for result in context.results)
    assert all(result.png_failure_count == 0 for result in context.results)
    assert {path.name for path in context.generation.directory.iterdir()} == {
        *GLOBAL_PAYLOAD_NAMES,
        GLOBAL_MANIFEST_NAME,
    }


def test_every_gap_has_a_reason_and_no_filtered_field_leaks_back_in(
    schema5_context: Schema5Context,
) -> None:
    gap_count = 0
    reference_count = 0
    for result, directory in schema5_context.authority.publications:
        table = read_tsv(directory / "图标未解析.tsv")
        assert len(table.rows) == result.unresolved_icon_count
        for row in table.rows:
            reason = table.value(row, "主原因")
            references = table.value(row, "引用集合")
            assert reason in {value.value for value in IconGapReason}
            assert table.value(row, "规范路径")
            assert references
            parsed_references = json.loads(references)
            assert len(parsed_references) == int(table.value(row, "引用数"))
            assert all(
                reference["field"].casefold() not in {"dfil", "bgsc"}
                for reference in parsed_references
            )
            assert all(
                reference["type"].casefold() not in {"model", "real"}
                for reference in parsed_references
            )
            reference_count += len(parsed_references)
        gap_count += len(table.rows)
    assert gap_count == len(schema5_context.authority.generation.evidence.gaps)
    assert reference_count == sum(
        result.unresolved_icon_reference_count
        for result in schema5_context.results
    )


def test_old_false_conflicts_are_reclassified_without_losing_text(
    schema5_context: Schema5Context,
) -> None:
    old_conflicts = 0
    new_current_conflicts = 0
    for digest, new_directory in schema5_context.new_by_digest.items():
        old = read_tsv(schema5_context.v4_by_digest[digest] / "对象完整描述.tsv")
        new = read_tsv(new_directory / "对象完整描述.tsv")
        old_conflicts += sum(
            old.value(row, "状态") == ObjectTextState.SOURCE_CONFLICT.value
            for row in old.rows
        )
        new_current_conflicts += sum(
            new.value(row, "状态")
            == ObjectTextState.SOURCE_CONFLICT.value
            and new.value(row, "是否当前值") == "是"
            for row in new.rows
        )
        assert not missing_complete_text_rows(old, new)
    assert old_conflicts == 55_634
    assert new_current_conflicts == 0


def missing_complete_text_rows(old: TsvTable, new: TsvTable) -> tuple[str, ...]:
    available = {
        (
            new.value(row, "分类"),
            new.value(row, "对象ID"),
            new.value(row, "字段键"),
            new.value(row, "等级/变体"),
            new.value(row, "原始全文"),
        )
        for row in new.rows
    }
    missing = []
    for row in old.rows:
        if (
            old.value(row, "状态")
            == ObjectTextState.SOURCE_UNAVAILABLE.value
            and old.value(row, "原始全文") == ""
        ):
            continue
        identity = (
            old.value(row, "分类"),
            old.value(row, "对象ID"),
            old.value(row, "字段键"),
            old.value(row, "等级/变体"),
            old.value(row, "原始全文"),
        )
        if identity not in available:
            missing.append(":".join(identity[:4]))
    return tuple(missing)
```

The same module also asserts: all four added object-text columns exist; readable text equals `readable_text(raw)`; every lower-priority row is non-current with an empty conflict group; every current identity has one value unless it is a proven same-priority conflict; physical newlines/tabs/quotes/formula prefixes round-trip; all levels are retained; every candidate has `是否采用=否`; global/per-map gap and axis counts reconcile; relation exports still equal the immutable relation index; cache accepted/rejected counts equal its three manifest-bound TSVs; every published original icon matches its SHA-256 and every PNG starts with the PNG magic bytes.
Add both real-data modules to `STRICT_PATHS` and the quality-gate coverage assertion so Ruff and basedpyright check them even when their environment-gated runtime cases skip.

- [ ] **Step 2: Verify the real-data contract fails before schema-5 publication exists**

Run:

```bash
W3XRAY_MAPS_ROOT=/Users/zhongerbing/Desktop/Maps \
W3XRAY_V4_OUTPUT=/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v4 \
W3XRAY_V5_OUTPUT=/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v5 \
W3XRAY_DESCRIPTION_CACHE=/Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5 \
uv run python -m pytest -q \
  tests/test_real_map_schema5_acceptance.py::test_schema_five_publishes_all_sources_with_independent_axes
```

Expected: FAIL because the owned description cache and authoritative schema-5 generation do not exist yet; the acceptance test must not silently skip when all four variables are explicitly supplied.

- [ ] **Step 3: Run the new tests without environment variables and verify safe skipping**

Run: `uv run python -m pytest -q tests/test_real_map_schema5_acceptance.py tests/test_real_map_item_relation_acceptance.py tests/test_quality_gate.py`

Expected: PASS with the real-data cases skipped because the four environment variables are absent.

- [ ] **Step 4: Commit the real-data acceptance contract**

```bash
git add tests/test_real_map_schema5_acceptance.py tests/test_real_map_item_relation_acceptance.py w3xtool/quality_gate.py tests/test_quality_gate.py
git commit -m "test: define schema five real-map acceptance"
```

- [ ] **Step 5: Run every focused test lane from Tasks 1–10**

Run: `uv run python -m pytest -q tests/test_icon_field_evidence.py tests/test_icon_path_evidence.py tests/test_icon_evidence_builder.py tests/test_icon_evidence_exports.py tests/test_icon_candidate_bindings.py tests/test_object_text_roles.py tests/test_object_text_priority.py tests/test_object_text_index.py tests/test_description_cache_migration.py tests/test_description_cache_publication.py tests/test_trusted_description_cache.py tests/test_batch_cli.py tests/test_batch_dependencies.py tests/test_batch_status.py tests/test_batch_result_parser.py tests/test_batch_global_evidence.py tests/test_batch_global_publication.py tests/test_gui_icon_gaps.py tests/test_gui_batch_status.py tests/test_gui_object_presentation.py tests/test_integrity_snapshot.py tests/test_integrity_cli.py`

Expected: PASS with no skipped test in this focused lane.

- [ ] **Step 6: Run the maintained static gate and complete repository suite**

Run: `uv run w3xray-quality`

Run: `uv run w3xray-test`

Expected: both commands PASS; only platform/real-data tests with documented unavailable prerequisites may skip.

- [ ] **Step 7: Capture the immutable before-run snapshot of all inputs**

Run:

```bash
uv run main.py integrity snapshot \
  --root maps=/Users/zhongerbing/Desktop/Maps \
  --root legacy-v1=/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output \
  --root legacy-v2=/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2 \
  --root legacy-v4=/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v4 \
  --output /Users/zhongerbing/Documents/xm/war3_xg/schema5-input-integrity.json
```

Expected: four roots are recorded; the maps root contains 39 map/campaign files; every root has a nonzero deterministic tree SHA-256. Abort acceptance if either new output path already exists without the tool's correct ownership marker; never delete or overwrite an unowned directory.

- [ ] **Step 8: Migrate and verify the historical trusted description cache**

First require the intended new cache root to be absent:

Run: `test ! -e /Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5`

Run:

```bash
uv run main.py description-cache migrate \
  --legacy-output /Users/zhongerbing/Documents/xm/war3_xg/map-extract-output \
  --legacy-cache /Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2/可信描述缓存.tsv \
  --output /Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5
```

Then load the cache through the public verifier:

Run: `uv run python -c 'from w3xtool.trusted_description_cache import load_trusted_description_cache; c=load_trusted_description_cache("/Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5"); print(len(c.cache.entries), c.manifest_sha256, c.content_sha256)'`

Run:

```bash
uv run main.py integrity snapshot \
  --root description-cache=/Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5 \
  --output /Users/zhongerbing/Documents/xm/war3_xg/schema5-cache-integrity.json
```

Expected: migration exits `0`, accepted plus rejected equals the 3,043 legacy candidates, all three digests are lowercase SHA-256, and a second load returns the same immutable cache.

- [ ] **Step 9: Smoke-test exact smallest and largest maps in private copies**

Run:

```bash
SMOKE_ROOT="$(mktemp -d /tmp/w3xray-schema5-smoke.XXXXXX)"
mkdir -p "$SMOKE_ROOT/small" "$SMOKE_ROOT/large"
cp /Users/zhongerbing/Desktop/Maps/dz/rpg/BFAAEE0242CEE0A218514B5B83598991.w3x "$SMOKE_ROOT/small/"
cp /Users/zhongerbing/Desktop/Maps/dz/rpg/C0562022DB31F58AB6EBC69850DE3E46.w3x "$SMOKE_ROOT/large/"
uv run main.py batch "$SMOKE_ROOT/small" \
  --output "$SMOKE_ROOT/small-output" \
  --game-data /Users/zhongerbing/Documents/xm/war3_xg/trusted-icon-cache-classic \
  --description-cache /Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5 \
  --minimum-free-bytes 0
uv run main.py batch "$SMOKE_ROOT/large" \
  --output "$SMOKE_ROOT/large-output" \
  --game-data /Users/zhongerbing/Documents/xm/war3_xg/trusted-icon-cache-classic \
  --description-cache /Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5 \
  --minimum-free-bytes 0
```

Expected: each private lane has one `已发布` result, valid per-map/global manifests, all required schema-5 reports, zero original/PNG write failures, and no stage/backup/transaction/quarantine leftovers.

Run: `uv run main.py integrity verify --snapshot /Users/zhongerbing/Documents/xm/war3_xg/schema5-input-integrity.json`

Run: `uv run main.py integrity verify --snapshot /Users/zhongerbing/Documents/xm/war3_xg/schema5-cache-integrity.json`

Expected: both verifiers exit `0` after smoke processing.

- [ ] **Step 10: Run the complete 39-map schema-5 publication**

First require the intended v5 root to be absent:

Run: `test ! -e /Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v5`

Run:

```bash
uv run main.py batch /Users/zhongerbing/Desktop/Maps \
  --output /Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v5 \
  --game-data /Users/zhongerbing/Documents/xm/war3_xg/trusted-icon-cache-classic \
  --description-cache /Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5 \
  --minimum-free-bytes 0 \
  | tee /Users/zhongerbing/Documents/xm/war3_xg/schema5-first-run.log
```

Run: `test "$(grep -c ' processed ' /Users/zhongerbing/Documents/xm/war3_xg/schema5-first-run.log)" -eq 39`

Expected: exit `0`; 39/39 publication results are `已发布`; failed/cancelled/original-write/PNG-failure counts are zero; the three-axis distribution and every remaining static evidence reason are present without being relabeled as write failure.

- [ ] **Step 11: Run the opt-in schema-5 and relation acceptance against real output**

Run:

```bash
W3XRAY_MAPS_ROOT=/Users/zhongerbing/Desktop/Maps \
W3XRAY_V4_OUTPUT=/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v4 \
W3XRAY_V5_OUTPUT=/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v5 \
W3XRAY_DESCRIPTION_CACHE=/Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5 \
W3XRAY_OLD_OUTPUT=/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output \
W3XRAY_NEW_OUTPUT=/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v5 \
uv run python -m pytest -q \
  tests/test_real_map_schema5_acceptance.py \
  tests/test_real_map_item_relation_acceptance.py
```

Expected: PASS with no skip; the test reports 55,634 old conflict rows reclassified with zero lost original rows, no non-icon field in unresolved reports, and exact global/per-map/status/cache/relation reconciliation.

- [ ] **Step 12: Re-run with identical inputs and prove 39 safe reuses**

Run:

```bash
uv run main.py batch /Users/zhongerbing/Desktop/Maps \
  --output /Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v5 \
  --game-data /Users/zhongerbing/Documents/xm/war3_xg/trusted-icon-cache-classic \
  --description-cache /Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5 \
  --minimum-free-bytes 0 \
  | tee /Users/zhongerbing/Documents/xm/war3_xg/schema5-reuse-run.log
```

Run: `test "$(grep -c ' reused ' /Users/zhongerbing/Documents/xm/war3_xg/schema5-reuse-run.log)" -eq 39`

Run: `test "$(grep -c ' processed ' /Users/zhongerbing/Documents/xm/war3_xg/schema5-reuse-run.log)" -eq 0`

Run: `test "$(grep -Ec ' failed | cancelled ' /Users/zhongerbing/Documents/xm/war3_xg/schema5-reuse-run.log)" -eq 0`

Expected: exit `0`; zero `processed`, `failed`, or `cancelled` progress rows; state/results/manifests remain equal; exactly 39 authoritative map directories remain; no stage, backup, transaction, or quarantine path remains.

- [ ] **Step 13: Verify every source and historical output byte/metadata identity**

Run:

```bash
uv run main.py integrity verify \
  --snapshot /Users/zhongerbing/Documents/xm/war3_xg/schema5-input-integrity.json
uv run main.py integrity verify \
  --snapshot /Users/zhongerbing/Documents/xm/war3_xg/schema5-cache-integrity.json
```

Expected: both commands exit `0`, with no differences across `maps`, `legacy-v1`, `legacy-v2`, `legacy-v4`, or the newly owned trusted-description cache.

- [ ] **Step 14: Run final repository checks and inspect tracked scope**

Run: `uv run w3xray-quality`

Run: `uv run w3xray-test`

Run: `git diff --check`

Run: `git status --short`

Expected: all gates PASS; generated v5/cache/log/integrity evidence is outside the repository; the working tree contains no uncommitted plan-generated or acceptance-generated file.

---

## Plan self-review result

- Spec coverage: Tasks 1–3 cover field eligibility, strict lookup, structured reasons, per-map reports, and split icon failures; Tasks 4–6 cover exact text identity, source priority, lossless variants, trusted migration, and dependency binding; Tasks 7–8 cover schema 5 axes and global evidence; Task 9 covers GUI search/navigation/current-all/copy; Tasks 10–11 cover versioning, integrity, full regression, real migration, 39-map publication, reuse, and source proof.
- Evidence boundary: no task promotes basename, suffix, visual, anonymous, cross-map custom, or unbound legacy text evidence; all candidate rows remain explicitly unadopted.
- Dependency order: every interface consumed by a later task is introduced earlier; schema 5 and revision 5 precede global/GUI/real acceptance.
- Repo accuracy: every `Modify`/`Delete` path exists; every direct `MapBatchResult` constructor and both authoritative resume loaders are included in Task 7; every newly referenced test helper has a complete definition.
- Shared fixtures and GUI lifecycle: the empty publication fixture writes every schema-5 required report before Task 8 aggregation, and strict icon evidence is built even when the optional object browser is disabled.
- Module size: selection, result parsing, global payload construction, GUI layouts, integrity I/O, and migration/publication are split before edits can exceed the 250-pure-LOC ceiling.
- Generated data: all acceptance outputs are outside the repository and all source/historical inputs are snapshotted and verified read-only.

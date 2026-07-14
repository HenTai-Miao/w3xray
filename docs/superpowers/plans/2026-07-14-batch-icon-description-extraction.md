# Batch Icon and Description Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a resumable, read-only batch command that extracts every provable named or anonymous Warcraft III icon as BLP and PNG and exports source-aware object descriptions for all maps below a selected directory.

**Architecture:** Add a layered classic-MPQ implementation of the existing `GameDataSource` protocol, then build focused description and icon domain modules above the existing `MapData`, extraction ledger, archive-source, BLP decoder, and safe-output boundaries. A sequential batch runner fingerprints each source, processes one map at a time into a staging directory, atomically publishes complete per-map artifacts, and rewrites deterministic global state and TSV reports after every map.

**Tech Stack:** Python 3.14, existing pure-Python MPQ reader, Pillow/BLP decoder, frozen dataclasses and `StrEnum`, pytest, uv, ruff, basedpyright.

## Global Constraints

- Recursively scan `.w3x`, `.w3m`, and `.w3n` sources in stable path order; process only one top-level source at a time.
- Keep every source map and classic MPQ read-only; write only below the explicitly selected output root.
- Classic lookup priority is exactly `War3Patch.mpq`, `War3xLocal.mpq`, `War3x.mpq`, then `war3.mpq`.
- Export original BLP before PNG conversion and preserve original BLP when decoding fails.
- Name anonymous BLP evidence exactly `block_XXXXXX_<sha256-prefix-8>.blp` and never infer an original path or object association.
- Preserve raw Warcraft description markup and export a separately cleaned value; never synthesize missing text.
- Description states are exactly `地图原值`, `客户端补全`, `地图明确清空`, and `源数据缺失`.
- A map-level icon failure must not stop later icons; a map-level failure must not stop later maps.
- Resume only when size, mtime-ns, SHA-256, output schema, and required published files all match an earlier complete result.
- Use existing safe-output and archive-source boundaries; reject path traversal, symlink parents, output collisions, and source/output overlap.
- Do not execute maps, scripts, historical executables, or DLLs and do not add runtime decryption, injection, or process-memory reads.
- Keep each new hand-written Python module below 250 pure lines and preserve unrelated staged and unstaged changes.

---

### Task 1: Read-only layered classic MPQ game-data source

**Files:**
- Create: `w3xtool/classic_mpq_source.py`
- Modify: `w3xtool/game_data_source.py`
- Test: `tests/test_classic_mpq_source.py`
- Test: `tests/test_game_data_source.py`

**Interfaces:**
- Consumes: `MPQArchive(path: str)`, whose instances expose `has_file`, `read_file`, and idempotent `close`.
- Produces: `classic_mpq_paths(root: str) -> tuple[str, ...]`, `is_classic_mpq_install(root: str) -> bool`, and `ClassicMpqDataSource(root: str)` implementing `GameDataSource`.
- Changes: `probe_game_data_path()` returns `GameDataProbe(kind="classic_mpq", backend="mpq")` before the generic extracted-directory probe; `open_game_data_source()` opens `ClassicMpqDataSource` for that kind.

- [ ] **Step 1: Write failing priority, missing-member, close, and probe tests**

```python
def test_classic_source_reads_the_highest_priority_archive(tmp_path: Path) -> None:
    # Given
    archives = {
        "War3Patch.mpq": FakeArchive({"Units\\HumanUnitStrings.txt": b"patch"}),
        "War3x.mpq": FakeArchive({"Units\\HumanUnitStrings.txt": b"expansion"}),
        "war3.mpq": FakeArchive({"Units\\HumanUnitStrings.txt": b"base"}),
    }
    for name in archives:
        (tmp_path / name).touch()

    # When
    source = ClassicMpqDataSource(str(tmp_path), archive_factory=lambda path: archives[Path(path).name])

    # Then
    assert source.read_file("Units/HumanUnitStrings.txt") == b"patch"
    source.close()


def test_game_data_probe_prefers_classic_mpqs_over_generic_files(tmp_path: Path) -> None:
    # Given
    (tmp_path / "war3.mpq").write_bytes(b"container")

    # When
    probe = probe_game_data_path(str(tmp_path))

    # Then
    assert (probe.kind, probe.is_readable, probe.backend) == ("classic_mpq", True, "mpq")
```

- [ ] **Step 2: Run the tests and confirm the new imports/classification fail**

Run: `uv run python -m pytest -q tests/test_classic_mpq_source.py tests/test_game_data_source.py`

Expected: FAIL because `w3xtool.classic_mpq_source` does not exist and classic directories are currently reported as `extracted_dir`.

- [ ] **Step 3: Implement the layered source and integrate probe/open ordering**

```python
CLASSIC_MPQ_NAMES: Final = (
    "War3Patch.mpq",
    "War3xLocal.mpq",
    "War3x.mpq",
    "war3.mpq",
)


def classic_mpq_paths(root: str) -> tuple[str, ...]:
    return tuple(
        os.path.join(root, name)
        for name in CLASSIC_MPQ_NAMES
        if os.path.isfile(os.path.join(root, name))
    )


@final
class ClassicMpqDataSource:
    def __init__(self, root: str, *, archive_factory: ArchiveFactory = MPQArchive) -> None:
        paths = classic_mpq_paths(root)
        if not paths or not any(Path(path).name.casefold() == "war3.mpq" for path in paths):
            raise FileNotFoundError(root)
        self.root = root
        self._archives = tuple(archive_factory(path) for path in paths)
        self._closed = False

    def has_file(self, name: str) -> bool:
        return any(archive.has_file(_member_name(name)) for archive in self._archives)

    def read_file(self, name: str) -> bytes:
        member = _member_name(name)
        for archive in self._archives:
            if archive.has_file(member):
                return archive.read_file(member)
        raise FileNotFoundError(name)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for archive in self._archives:
            archive.close()
```

- [ ] **Step 4: Run focused tests, lint, and type-check**

Run: `uv run python -m pytest -q tests/test_classic_mpq_source.py tests/test_game_data_source.py tests/test_load_context.py tests/test_object_text_sources.py`

Expected: PASS.

Run: `uv run --with ruff ruff check w3xtool/classic_mpq_source.py w3xtool/game_data_source.py tests/test_classic_mpq_source.py tests/test_game_data_source.py`

Expected: no errors.

Run: `uv run --with basedpyright basedpyright --level error w3xtool/classic_mpq_source.py w3xtool/game_data_source.py`

Expected: 0 errors.

- [ ] **Step 5: Commit the classic data-source slice**

```bash
git add w3xtool/classic_mpq_source.py w3xtool/game_data_source.py tests/test_classic_mpq_source.py tests/test_game_data_source.py
git commit -m "feat: read classic Warcraft MPQ data"
```

### Task 2: Source-aware description field selection

**Files:**
- Create: `w3xtool/batch_descriptions.py`
- Create: `tests/test_batch_descriptions.py`

**Interfaces:**
- Consumes: `GameObject.field_values`, `GameObject.field_labels`, and `GameObject.field_sources`; `clean_text(raw: str) -> str`.
- Produces: `DescriptionState(StrEnum)`, frozen `DescriptionRecord`, and `audit_object_descriptions(objects: Iterable[GameObject]) -> tuple[DescriptionRecord, ...]`.
- Field order: abilities `atp1:<level>`/`aub1:<level>` then `atp1`/`aub1`; upgrades `gtp1:<level>`/`gub1:<level>` then unlevelled keys; units `utip`/`utub`; items `utip`/`utub` with `ides` as description fallback; buffs `ftip`/`fube`; display aliases are final fallbacks.

- [ ] **Step 1: Write failing tests for all four states, level retention, and cleaning**

```python
def test_audit_preserves_raw_levels_and_cleans_markup() -> None:
    # Given
    item = game_object(
        category="技能",
        field_values={"atp1:1": "一级", "aub1:1": "|cffffcc00伤害|r|n100", "aub1:2": ""},
        field_sources={"atp1:1": "war3map.w3a", "aub1:1": "war3map.w3a", "aub1:2": "war3map.w3a"},
    )

    # When
    records = audit_object_descriptions((item,))

    # Then
    assert [(record.level, record.raw_description, record.readable_description, record.state) for record in records] == [
        (1, "|cffffcc00伤害|r|n100", "伤害\n100", DescriptionState.MAP_VALUE),
        (2, "", "", DescriptionState.MAP_EXPLICIT_EMPTY),
    ]
```

```python
def test_audit_marks_inherited_client_text_without_fabricating_missing_text() -> None:
    # Given
    inherited = game_object(field_values={"display:description": "客户端说明"}, field_sources={"display:description": "base:A000"})
    missing = game_object(obj_id="A001", field_values={}, field_sources={})

    # When
    records = audit_object_descriptions((inherited, missing))

    # Then
    assert records[0].state is DescriptionState.CLIENT_FILL
    assert records[1].state is DescriptionState.SOURCE_MISSING
    assert records[1].raw_description == records[1].readable_description == ""
```

- [ ] **Step 2: Run the new tests and verify the module is absent**

Run: `uv run python -m pytest -q tests/test_batch_descriptions.py`

Expected: FAIL because `w3xtool.batch_descriptions` does not exist.

- [ ] **Step 3: Implement typed records and category-specific field selection**

```python
class DescriptionState(StrEnum):
    MAP_VALUE = "地图原值"
    CLIENT_FILL = "客户端补全"
    MAP_EXPLICIT_EMPTY = "地图明确清空"
    SOURCE_MISSING = "源数据缺失"


@dataclass(frozen=True, slots=True)
class DescriptionRecord:
    category: str
    object_id: str
    base_id: str
    object_name: str
    is_custom: bool
    level: int | None
    raw_tip: str
    readable_tip: str
    tip_source: str
    raw_description: str
    readable_description: str
    description_source: str
    state: DescriptionState


def audit_object_descriptions(objects: Iterable[GameObject]) -> tuple[DescriptionRecord, ...]:
    records = tuple(record for item in objects for record in _records_for_object(item))
    return tuple(sorted(records, key=_record_sort_key))
```

Implementation rules inside `_records_for_object`: retain every explicit numeric level present in either tip or description keys; choose map fields before `base:<id>` sources; treat a selected empty map field as explicit empty; call `clean_text` only for readable columns; emit one unlevelled missing record when no candidate key exists.

- [ ] **Step 4: Run focused checks**

Run: `uv run python -m pytest -q tests/test_batch_descriptions.py tests/test_object_extraction_integrity.py tests/test_object_pipeline.py`

Expected: PASS.

Run: `uv run --with ruff ruff check w3xtool/batch_descriptions.py tests/test_batch_descriptions.py && uv run --with basedpyright basedpyright --level error w3xtool/batch_descriptions.py`

Expected: no errors and 0 type errors.

- [ ] **Step 5: Commit the description audit slice**

```bash
git add w3xtool/batch_descriptions.py tests/test_batch_descriptions.py
git commit -m "feat: audit object description sources"
```

### Task 3: Named and anonymous icon resource discovery

**Files:**
- Create: `w3xtool/icon_resources.py`
- Create: `tests/test_icon_resources.py`

**Interfaces:**
- Consumes: `GameObject.icon`, `GameDataSource`, `MapArchiveReader`, `ExtractionLedger.entries`, and `MapArchiveReader.read_block_anon(block)`.
- Produces: frozen `IconReference`, `NamedIconResource`, and `AnonymousIconResource`; `collect_icon_references(objects)`, `resolve_named_icon(reference_path, map_archives, game_source)`, and `iter_anonymous_blps(archive, ledger)`.
- Named resource provenance values are archive source paths, never guessed labels; anonymous resources carry only block index, bytes, SHA-256, and ledger source/state.

- [ ] **Step 1: Write failing tests for normalization, deduplication, provenance, and anonymous evidence**

```python
def test_named_icon_collection_deduplicates_paths_and_keeps_all_references() -> None:
    # Given
    objects = (
        game_object(category="单位", obj_id="H001", icon="ReplaceableTextures/CommandButtons/BTNHero.blp"),
        game_object(category="技能", obj_id="A001", icon="replaceabletextures\\commandbuttons\\BTNHero.blp"),
    )

    # When
    references = collect_icon_references(objects)

    # Then
    assert len(references) == 1
    assert {(ref.category, ref.object_id) for ref in references[0].objects} == {("单位", "H001"), ("技能", "A001")}
```

```python
def test_anonymous_blp_name_uses_block_and_payload_digest() -> None:
    # Given
    archive = FakeArchive(blocks={17: b"BLP1payload"})
    ledger = ledger_with_entry(block_index=17, internal_path="__unknown__/block_000017.blp")

    # When
    resources = tuple(iter_anonymous_blps(archive, ledger))

    # Then
    digest = hashlib.sha256(b"BLP1payload").hexdigest()
    assert resources[0].basename == f"block_000017_{digest[:8]}"
    assert resources[0].original_path is None
```

- [ ] **Step 2: Run tests and confirm the module is absent**

Run: `uv run python -m pytest -q tests/test_icon_resources.py`

Expected: FAIL because `w3xtool.icon_resources` does not exist.

- [ ] **Step 3: Implement streaming resource collection without PIL caching**

```python
@dataclass(frozen=True, slots=True)
class IconObjectReference:
    category: str
    object_id: str
    object_name: str


@dataclass(frozen=True, slots=True)
class IconReference:
    requested_path: str
    normalized_path: str
    objects: tuple[IconObjectReference, ...]


@dataclass(frozen=True, slots=True)
class AnonymousIconResource:
    block_index: int
    payload: bytes
    sha256: str
    basename: str
    original_path: None = None
```

`resolve_named_icon` must try the exact path and extension-normalized `.blp`, `.tga`, and `.dds` candidates against each map/campaign archive in order, then the classic client source. It returns raw bytes and provenance even when the payload is not a decodable BLP. `iter_anonymous_blps` must use only ledger entries whose block index is known, whose internal path/peek identifies BLP, and whose payload begins with `BLP1` or `BLP2`; duplicate block indexes are read once.

- [ ] **Step 4: Run focused tests, lint, and types**

Run: `uv run python -m pytest -q tests/test_icon_resources.py tests/test_icons.py tests/test_extraction_ledger.py`

Expected: PASS.

Run: `uv run --with ruff ruff check w3xtool/icon_resources.py tests/test_icon_resources.py && uv run --with basedpyright basedpyright --level error w3xtool/icon_resources.py`

Expected: no errors and 0 type errors.

- [ ] **Step 5: Commit the icon discovery slice**

```bash
git add w3xtool/icon_resources.py tests/test_icon_resources.py
git commit -m "feat: discover named and anonymous icons"
```

### Task 4: Safe BLP and PNG publication

**Files:**
- Create: `w3xtool/batch_icon_export.py`
- Create: `tests/test_batch_icon_export.py`

**Interfaces:**
- Consumes: resources from `icon_resources`, `decode_blp(data: bytes)`, and `write_bytes_safely(root, name, data)`.
- Produces: `IconExportState(StrEnum)`, frozen `IconExportRecord`, `export_named_icon(...) -> IconExportRecord`, and `export_anonymous_icon(...) -> IconExportRecord`.
- Writes below a per-map staging root: `图标/原始/具名`, `图标/原始/匿名`, `图标/PNG/具名`, and `图标/PNG/匿名`.

- [ ] **Step 1: Write failing original-first, decode-failure, traversal, and collision tests**

```python
def test_export_keeps_original_when_png_decode_fails(tmp_path: Path) -> None:
    # Given
    resource = anonymous_resource(block_index=9, payload=b"BLP1broken")

    # When
    record = export_anonymous_icon(str(tmp_path), resource)

    # Then
    assert (tmp_path / "图标/原始/匿名" / f"{resource.basename}.blp").read_bytes() == b"BLP1broken"
    assert record.original_written is True
    assert record.png_written is False
    assert record.state is IconExportState.PNG_FAILED
```

```python
def test_named_export_cannot_escape_the_output_root(tmp_path: Path) -> None:
    # Given
    resource = named_resource(requested_path="../../outside.blp", payload=b"BLP1broken")

    # When
    record = export_named_icon(str(tmp_path), resource)

    # Then
    assert record.state is IconExportState.UNSAFE_PATH
    assert not (tmp_path.parent / "outside.blp").exists()
```

- [ ] **Step 2: Run tests and confirm the module is absent**

Run: `uv run python -m pytest -q tests/test_batch_icon_export.py`

Expected: FAIL because `w3xtool.batch_icon_export` does not exist.

- [ ] **Step 3: Implement original-first safe writes and bounded PNG encoding**

```python
def _png_bytes(payload: bytes) -> bytes | None:
    image = decode_blp(payload)
    if image is None:
        return None
    try:
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    finally:
        image.close()
```

For named resources, derive a safe relative member path from the normalized requested path. If two normalized names map to the same cleaned destination but contain different bytes, append `_<sha8>` before the suffix. Do not write PNG unless the original result status is `WRITTEN`; store the exact safe-write error and continue.

- [ ] **Step 4: Run focused safety and decoder checks**

Run: `uv run python -m pytest -q tests/test_batch_icon_export.py tests/test_archive_output_safety.py tests/test_export_safety.py tests/test_blp.py`

Expected: PASS.

Run: `uv run --with ruff ruff check w3xtool/batch_icon_export.py tests/test_batch_icon_export.py && uv run --with basedpyright basedpyright --level error w3xtool/batch_icon_export.py`

Expected: no errors and 0 type errors.

- [ ] **Step 5: Commit the publication slice**

```bash
git add w3xtool/batch_icon_export.py tests/test_batch_icon_export.py
git commit -m "feat: export original and png icons safely"
```

### Task 5: Deterministic per-map and global reports

**Files:**
- Create: `w3xtool/batch_models.py`
- Create: `w3xtool/batch_reports.py`
- Create: `tests/test_batch_reports.py`

**Interfaces:**
- Consumes: description and icon records from Tasks 2 and 4 plus extraction-ledger counts.
- Produces: `MapBatchState(StrEnum)`, frozen `SourceFingerprint`, `MapBatchResult`, `BatchState`; `format_icon_index_tsv`, `format_description_tsv`, `format_map_summary`, `format_icon_completeness`, `format_description_completeness`, `format_batch_summary_tsv`, `format_retry_tsv`, `format_batch_state_json`, and `parse_batch_state_json`.
- JSON schema version is `1`; TSV newlines and cells are escaped deterministically.

- [ ] **Step 1: Write failing serialization and status-aggregation tests**

```python
def test_description_tsv_keeps_raw_and_readable_columns_separate() -> None:
    # Given
    record = description_record(raw_description="|cffff0000说明|r|n第二行", readable_description="说明\n第二行")

    # When
    report = format_description_tsv((record,))

    # Then
    assert "原始说明\t可读说明\t说明来源\t完整性状态" in report
    assert "|cffff0000说明|r\\n第二行\t说明\\n第二行" in report
```

```python
def test_batch_state_json_round_trips_source_fingerprint() -> None:
    # Given
    state = BatchState(schema_version=1, results=(map_result(source_sha256="a" * 64),))

    # When
    restored = parse_batch_state_json(format_batch_state_json(state))

    # Then
    assert restored == state
```

- [ ] **Step 2: Run tests and confirm report modules are absent**

Run: `uv run python -m pytest -q tests/test_batch_reports.py`

Expected: FAIL because the new modules do not exist.

- [ ] **Step 3: Implement typed state, exact Chinese statuses, and stable formatting**

```python
class MapBatchState(StrEnum):
    COMPLETE = "完整"
    PARTIAL = "部分完成"
    RESTRICTED = "受限"
    FAILED = "失败"


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    path: str
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class MapBatchResult:
    source: SourceFingerprint
    display_name: str
    output_directory: str
    stage: str
    state: MapBatchState
    first_error: str
    object_count: int
    description_counts: tuple[tuple[str, int], ...]
    named_icon_count: int
    anonymous_icon_count: int
    original_written_count: int
    png_written_count: int
    icon_failure_count: int
    restricted_block_count: int
    elapsed_ms: int
```

`format_*` functions must sort by category/object/level or normalized icon path/block index, replace literal tabs with spaces, encode embedded CR/LF as `\n`, and always terminate text reports with one newline. Map status aggregation follows the spec: structural/report publication errors are failed; blocked encrypted evidence is restricted; any missing description/raw-only/decode/read failure is partial; otherwise complete.

- [ ] **Step 4: Run report checks**

Run: `uv run python -m pytest -q tests/test_batch_reports.py tests/test_extraction_ledger.py tests/test_extraction_completeness.py`

Expected: PASS.

Run: `uv run --with ruff ruff check w3xtool/batch_models.py w3xtool/batch_reports.py tests/test_batch_reports.py && uv run --with basedpyright basedpyright --level error w3xtool/batch_models.py w3xtool/batch_reports.py`

Expected: no errors and 0 type errors.

- [ ] **Step 5: Commit report and state types**

```bash
git add w3xtool/batch_models.py w3xtool/batch_reports.py tests/test_batch_reports.py
git commit -m "feat: format extraction completeness reports"
```

### Task 6: Sequential resumable batch runner

**Files:**
- Modify: `w3xtool/map_directory.py`
- Create: `w3xtool/batch_runner.py`
- Create: `tests/test_batch_runner.py`

**Interfaces:**
- Consumes: `build_map_load_context(game_data_path=...)`, `load_map(path, load_context=...)`, `open_map_source(md)`, Tasks 2–5, `write_text_safely`, and source hashing from `map_archive_open.source_sha256`.
- Produces: `scan_map_sources(directory: str) -> tuple[str, ...]`, frozen `BatchOptions`, and `run_batch(options: BatchOptions) -> BatchState`.
- Defaults: output root `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output/`; adjacent classic data path is inferred from the nearest ancestor containing `war3.mpq` unless `game_data_path` is explicit.

- [ ] **Step 1: Write failing scan, continuation, resume, and source-integrity tests**

```python
def test_scan_map_sources_includes_campaigns_in_stable_path_order(tmp_path: Path) -> None:
    # Given
    for name in ("z.w3n", "A.w3x", "nested/b.w3m"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    # When
    sources = scan_map_sources(str(tmp_path))

    # Then
    assert tuple(Path(path).relative_to(tmp_path).as_posix() for path in sources) == ("A.w3x", "nested/b.w3m", "z.w3n")
```

```python
def test_batch_continues_after_one_map_fails_and_does_not_modify_sources(tmp_path: Path) -> None:
    # Given
    good = write_fake_map(tmp_path / "good.w3x")
    bad = write_fake_map(tmp_path / "bad.w3x")
    before = {path: (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) for path in (good, bad)}

    # When
    state = run_batch(batch_options(tmp_path, loader=loader_failing_only_for(bad)))

    # Then
    assert [result.state for result in state.results] == [MapBatchState.FAILED, MapBatchState.COMPLETE]
    assert {path: (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) for path in (good, bad)} == before
```

```python
def test_resume_skips_only_unchanged_published_success(tmp_path: Path) -> None:
    # Given
    options = batch_options(tmp_path)
    first = run_batch(options)

    # When
    second = run_batch(options)

    # Then
    assert second.results == first.results
    assert options.loader_call_count() == 1
```

- [ ] **Step 2: Run tests and confirm scan/runner APIs fail**

Run: `uv run python -m pytest -q tests/test_batch_runner.py`

Expected: FAIL because `.w3n` scan and `batch_runner` do not exist.

- [ ] **Step 3: Implement source scanning and one-map-at-a-time orchestration**

```python
MAP_SOURCE_EXTENSIONS: Final = frozenset({".w3x", ".w3m", ".w3n"})


@dataclass(frozen=True, slots=True)
class BatchOptions:
    source_directory: str
    output_root: str
    game_data_path: str | None = None
    retry_failed: bool = True


def run_batch(options: BatchOptions) -> BatchState:
    _reject_overlapping_roots(options)
    previous = _read_previous_state(options.output_root)
    results: list[MapBatchResult] = []
    for index, path in enumerate(scan_map_sources(options.source_directory), start=1):
        fingerprint = fingerprint_source(path)
        reusable = _reusable_result(previous, fingerprint, options.output_root)
        result = reusable if reusable is not None else _process_one_map(index, fingerprint, options)
        results.append(result)
        _publish_global_reports(options.output_root, BatchState(1, tuple(results)))
    return BatchState(1, tuple(results))
```

`_process_one_map` must create a uniquely owned sibling staging directory, build one shared client context, call `load_map`, flatten root and campaign child objects while preserving the child archive provenance, stream named then anonymous icon exports, write all five required per-map reports, close every `MapData` in `finally`, then atomically rename staging to the SHA-addressed final directory. At the top-level map boundary only, catch named load/archive/report/output exceptions into a failed result and continue. Resume validation must open no source map beyond fingerprint hashing and must verify all required report files exist below a non-symlink published directory.

- [ ] **Step 4: Run integration and safety tests**

Run: `uv run python -m pytest -q tests/test_batch_runner.py tests/test_map_data_compat.py tests/test_archive_output_safety.py tests/test_security_closeout.py`

Expected: PASS.

Run: `uv run --with ruff ruff check w3xtool/map_directory.py w3xtool/batch_runner.py tests/test_batch_runner.py && uv run --with basedpyright basedpyright --level error w3xtool/map_directory.py w3xtool/batch_runner.py`

Expected: no errors and 0 type errors.

- [ ] **Step 5: Commit the runner slice**

```bash
git add w3xtool/map_directory.py w3xtool/batch_runner.py tests/test_batch_runner.py
git commit -m "feat: run resumable sequential map extraction"
```

### Task 7: Batch CLI and observable end-to-end scenarios

**Files:**
- Create: `w3xtool/batch_cli.py`
- Modify: `main.py`
- Create: `tests/test_batch_cli.py`
- Create: `tests/test_batch_e2e.py`

**Interfaces:**
- Consumes: `BatchOptions` and `run_batch`.
- Produces: `BatchCliOptions`, `parse_batch_cli_options(args: tuple[str, ...]) -> BatchCliOptions`, and `run_batch_cli(options: BatchCliOptions) -> int`.
- Command: `uv run main.py batch MAP_DIRECTORY [--output OUTPUT_DIRECTORY] [--game-data WARCRAFT_DIRECTORY] [--no-retry-failed]`.

- [ ] **Step 1: Write failing parser, exit-code, and filesystem E2E tests**

```python
def test_parse_batch_cli_uses_documented_default_output() -> None:
    # Given
    args = ("/maps",)

    # When
    options = parse_batch_cli_options(args)

    # Then
    assert options.output_root == "/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output"
```

```python
def test_batch_e2e_writes_original_png_descriptions_and_global_summary(tmp_path: Path) -> None:
    # Given
    maps = tmp_path / "Maps"
    output = tmp_path / "output"
    write_synthetic_icon_map(maps / "sample.w3x")

    # When
    code = run_batch_cli(BatchCliOptions(str(maps), str(output), None, True))

    # Then
    assert code == 0
    assert tuple(output.glob("地图/*/图标/原始/具名/**/*.blp"))
    assert tuple(output.glob("地图/*/图标/PNG/具名/**/*.png"))
    assert tuple(output.glob("地图/*/对象描述.tsv"))
    assert (output / "批量提取汇总.tsv").is_file()
```

Add a second E2E scenario where one corrupt input returns exit code `1`, still publishes `失败与重试.tsv`, and still completes a valid sibling map.

- [ ] **Step 2: Run tests and verify parser/dispatch imports fail**

Run: `uv run python -m pytest -q tests/test_batch_cli.py tests/test_batch_e2e.py`

Expected: FAIL because the batch CLI and `main.py batch` dispatch do not exist.

- [ ] **Step 3: Implement strict CLI parsing, progress output, and dispatch**

```python
def run_batch_cli(options: BatchCliOptions) -> int:
    state = run_batch(options.to_batch_options())
    for result in state.results:
        print(f"[{result.state}] {result.display_name} -> {result.output_directory}")
    failed = sum(result.state is MapBatchState.FAILED for result in state.results)
    print(f"完成：{len(state.results) - failed}/{len(state.results)}，失败：{failed}")
    return int(failed > 0)
```

Add `batch` dispatch before the legacy GUI branch in `main.main`; parser errors print one Chinese error line to stderr and exit `2`. Do not add background threads or parallel map loading.

- [ ] **Step 4: Run CLI/E2E and static checks**

Run: `uv run python -m pytest -q tests/test_batch_cli.py tests/test_batch_e2e.py tests/test_main_entrypoint.py`

Expected: PASS.

Run: `uv run --with ruff ruff check main.py w3xtool/batch_cli.py tests/test_batch_cli.py tests/test_batch_e2e.py && uv run --with basedpyright basedpyright --level error main.py w3xtool/batch_cli.py`

Expected: no errors and 0 type errors.

- [ ] **Step 5: Commit the CLI and E2E slice**

```bash
git add main.py w3xtool/batch_cli.py tests/test_batch_cli.py tests/test_batch_e2e.py
git commit -m "feat: add batch icon extraction command"
```

### Task 8: Full verification, real-map acceptance, and durable project commands

**Files:**
- Modify: `AGENTS.md`
- Create: `AGENTS.d/runtime.md`
- Create: `AGENTS.d/testing.md`
- Create: `docs/batch-icon-description-extraction.md`

**Interfaces:**
- Documents: exact batch command, output layout, resume/retry semantics, description statuses, anonymous icon limits, and real-map acceptance commands.
- Verifies: smallest map, largest map, then all 37 sources without changing any source size, mtime-ns, or SHA-256.

- [ ] **Step 1: Run all focused feature tests together**

Run:

```bash
uv run python -m pytest -q \
  tests/test_classic_mpq_source.py \
  tests/test_batch_descriptions.py \
  tests/test_icon_resources.py \
  tests/test_batch_icon_export.py \
  tests/test_batch_reports.py \
  tests/test_batch_runner.py \
  tests/test_batch_cli.py \
  tests/test_batch_e2e.py
```

Expected: PASS with no skipped feature scenarios.

- [ ] **Step 2: Run the complete repository gate**

Run: `uv run w3xray-test`

Expected: PASS.

Run: `uv run --with ruff ruff check main.py w3xtool tests`

Expected: no errors.

Run: `uv run --with ruff ruff format --check main.py w3xtool tests`

Expected: no formatting changes required.

Run: `uv run --with basedpyright basedpyright --level error main.py w3xtool`

Expected: 0 errors.

- [ ] **Step 3: Record source identities and run smallest/largest real-map acceptance**

Run:

```bash
find '/Volumes/zhongerbing/Program Files (x86)/Warcraft III/Warcraft III Frozen Throne/Maps' \
  -type f \( -iname '*.w3x' -o -iname '*.w3m' -o -iname '*.w3n' \) -print0 \
  | sort -z | xargs -0 stat -f '%N\t%z\t%m' > /tmp/w3xray-map-stat-before.tsv
find '/Volumes/zhongerbing/Program Files (x86)/Warcraft III/Warcraft III Frozen Throne/Maps' \
  -type f \( -iname '*.w3x' -o -iname '*.w3m' -o -iname '*.w3n' \) -print0 \
  | sort -z | xargs -0 shasum -a 256 > /tmp/w3xray-map-sha-before.tsv
```

Run the command first against a temporary directory containing only the smallest source, then another containing only the largest source, using symlinks as read-only inputs and separate output roots. Expected: smallest run resolves all known named icons and client-filled descriptions; largest run exports thousands of anonymous BLPs without retaining PIL images and reports unresolved/decode-failed evidence as partial rather than failed.

- [ ] **Step 4: Run all real maps and verify global artifacts and source immutability**

Run:

```bash
uv run main.py batch \
  '/Volumes/zhongerbing/Program Files (x86)/Warcraft III/Warcraft III Frozen Throne/Maps' \
  --output '/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output' \
  --game-data '/Volumes/zhongerbing/Program Files (x86)/Warcraft III/Warcraft III Frozen Throne'
```

Expected: 37 top-level results in `批量提取汇总.tsv`; every result has a SHA-addressed per-map directory or a stable failed row; every anonymous original filename matches `block_[0-9]{6}_[0-9a-f]{8}.blp`.

Regenerate `/tmp/w3xray-map-stat-after.tsv` and `/tmp/w3xray-map-sha-after.tsv` with the Step 3 commands, then run:

```bash
diff -u /tmp/w3xray-map-stat-before.tsv /tmp/w3xray-map-stat-after.tsv
diff -u /tmp/w3xray-map-sha-before.tsv /tmp/w3xray-map-sha-after.tsv
```

Expected: both diffs are empty.

- [ ] **Step 5: Write user documentation and update AGENTS knowledge**

Document the successful command and observed runtime/output counts in `AGENTS.d/runtime.md`; document the focused, full, lint, type, smallest/largest, and source-integrity gates in `AGENTS.d/testing.md`. Add only compact links and the new `batch` command to root `AGENTS.md`, keeping it under 60 lines. In `docs/batch-icon-description-extraction.md`, explain that anonymous exports are complete static evidence but cannot be assigned original names or objects without proof.

- [ ] **Step 6: Re-run the documentation-sensitive CLI help test and commit**

Run: `uv run python -m pytest -q tests/test_batch_cli.py tests/test_batch_e2e.py`

Expected: PASS.

```bash
git add AGENTS.md AGENTS.d/runtime.md AGENTS.d/testing.md docs/batch-icon-description-extraction.md
git commit -m "docs: explain batch map extraction workflow"
```

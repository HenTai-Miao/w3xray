# Reference Extraction Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `w3xray` match the reference program's reliable four-category object extraction while closing the static MPQ, script, campaign, CASC, diagnostic, and publication gaps that currently lose readable data.

**Architecture:** Keep `w3xtool.api` as a compatibility facade, move map models and extraction responsibilities into focused modules, and normalize every object source into immutable candidates before one deterministic merge. Split MPQ layout, name/hash, compression, and block reading responsibilities while preserving the public `MPQArchive` API; route all later archive reads through a persistent `ArchiveSource` and all export writes through structured results.

**Tech Stack:** Python 3.14, `uv`, `pytest`, standard-library `lzma`, CustomTkinter/Tkinter, existing pure-Python MPQ/Huffman/PKWARE implementations, StormLib 9.25 fixtures matching the reference DLL, Ghidra 12.1.2 with Oracle JDK 26.0.1 for reference verification.

## Global Constraints

- Keep every operation read-only with respect to maps, campaigns, game data, and saves.
- Do not execute map scripts or loaders, call platform APIs, inspect process memory, disable protections, or bypass anti-cheat.
- Preserve imports and calls through `w3xtool.api.GameObject`, `w3xtool.api.MapData`, and `w3xtool.api.load_map`.
- Preserve `write_knowledge_pack(md, out_dir) -> int`; add a detailed result API without breaking the integer facade.
- Keep every new or expanded Python module at or below 250 pure LOC; split `api.py` and `mpq.py` before adding behavior.
- Use `decode_warcraft_string` for Warcraft text and byte-based MPQ hashing for archive names.
- Every behavior change starts with a test that fails for the intended reason, then passes after the minimum implementation.
- Use pinned real-format fixtures with source URL, upstream commit, license, and SHA256; generated fixtures must be produced by pinned StormLib and documented.
- Run Python commands with `PYTHONDONTWRITEBYTECODE=1`; disable pytest cache for focused red/green runs.
- Put downloads, Ghidra projects, native builds, and generated fixture intermediates under `${TMPDIR:-/tmp}` and remove them after use.

---

### Task 1: Map Models, Archive Sources, and Component Diagnostics

**Files:**
- Create: `w3xtool/map_data.py`
- Create: `w3xtool/archive_source.py`
- Create: `w3xtool/extraction_diagnostics.py`
- Modify: `w3xtool/api.py:1-114`
- Create: `tests/test_map_data_compat.py`
- Create: `tests/test_extraction_diagnostics.py`

**Interfaces:**
- Produces: `GameObject`, `MapData`, and `MapData.category_counts()` in `w3xtool.map_data`; `w3xtool.api` re-exports both names.
- Produces: `ArchiveSource.open() -> ContextManager[MapArchiveReader]`, `PathArchiveSource`, and `BytesArchiveSource`.
- Produces: `DiagnosticSeverity`, `ExtractionDiagnostic`, and `record_diagnostic(md, diagnostic) -> None`.
- Adds compatibly: `MapData.archive_source`, `MapData.diagnostics`, `MapData.ui_strings`, and `MapData.close()`.

- [x] **Step 1: Write compatibility and lifecycle tests**

```python
def test_api_reexports_map_models() -> None:
    from w3xtool.api import GameObject as ApiObject, MapData as ApiMap
    from w3xtool.map_data import GameObject, MapData

    assert ApiObject is GameObject
    assert ApiMap is MapData


def test_bytes_archive_source_reopens_and_closes() -> None:
    source = BytesArchiveSource("Maps\\Chapter01.w3x", _minimal_mpq_bytes())

    with source.open() as archive:
        assert archive.read_file("war3map.j") == b"function main takes nothing returns nothing\nendfunction\n"

    source.close()
    assert source.is_closed
```

- [x] **Step 2: Run the new tests and confirm the modules are missing**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_map_data_compat.py tests/test_extraction_diagnostics.py -q -p no:cacheprovider`

Expected: FAIL with `ModuleNotFoundError` for `w3xtool.map_data` or `w3xtool.archive_source`.

- [x] **Step 3: Move the public models and add typed extension fields**

```python
@dataclass(slots=True)
class GameObject:
    category: str
    ext: str
    obj_id: str
    base_id: str
    name: str
    is_custom: bool
    fields: list[tuple[str, str]] = field(default_factory=list)
    search_text: str = ""
    icon: str = ""
    ref_fields: list[tuple[str, list[str]]] = field(default_factory=list)
    field_values: dict[str, str] = field(default_factory=dict)
    field_sources: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class MapData:
    path: str
    name: str
    objects: dict[str, list[GameObject]] = field(default_factory=dict)
    scripts: dict[str, str] = field(default_factory=dict)
    all_files: list[str] = field(default_factory=list)
    archive_source: ArchiveSource | None = None
    diagnostics: list[ExtractionDiagnostic] = field(default_factory=list)
    ui_strings: dict[int, str] = field(default_factory=dict)
```

Move all existing `MapData` fields unchanged after these additions. Implement `decimal`, `category_counts`, and `close` with the current behavior plus archive-source cleanup. In `api.py`, import and re-export the classes instead of defining them.

- [x] **Step 4: Implement reusable archive sources and diagnostics**

```python
class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ExtractionDiagnostic:
    component: str
    source: str
    stage: str
    severity: DiagnosticSeverity
    message: str
    recoverable: bool


def record_diagnostic(md: MapData, diagnostic: ExtractionDiagnostic) -> None:
    if diagnostic not in md.diagnostics:
        md.diagnostics.append(diagnostic)
```

`PathArchiveSource.open()` returns `MPQArchive(path)`. `BytesArchiveSource` owns immutable bytes and opens them through a private system-temporary file; the context removes that file after the archive closes, while `close()` prevents future opens and releases the bytes.

- [x] **Step 5: Run compatibility and representative existing tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_map_data_compat.py tests/test_extraction_diagnostics.py tests/test_knowledge_pack.py tests/test_campaign.py -q -p no:cacheprovider`

Expected: PASS.

- [x] **Step 6: Commit the foundation**

```bash
git add w3xtool/map_data.py w3xtool/archive_source.py w3xtool/extraction_diagnostics.py w3xtool/api.py tests/test_map_data_compat.py tests/test_extraction_diagnostics.py
git commit -m "refactor: split extraction models and sources"
```

### Task 2: Trusted and Anonymous Text Object Sources

**Files:**
- Create: `w3xtool/object_text_sources.py`
- Modify: `w3xtool/textobj.py`
- Modify: `w3xtool/map_archive_reader.py`
- Create: `tests/test_object_text_sources.py`

**Interfaces:**
- Produces: `TextObjectSourceKind`, `TextObjectRecord`, and `collect_text_object_records(archive, known_names=()) -> tuple[TextObjectRecord, ...]`.
- Produces: `merge_text_object_records(records) -> tuple[TextObjectRecord, ...]` with deterministic Func/Strings precedence.
- Consumes: `decode_warcraft_string`, `parse_text_objects`, `classify`, and optional anonymous block APIs.

- [x] **Step 1: Write GBK, WTS-independent discovery, merge, and threshold tests**

```python
def test_named_gbk_strings_file_is_decoded_below_anonymous_threshold() -> None:
    archive = FakeArchive({
        "Units\\HumanUnitStrings.txt": "[H001]\nName=圣骑士\nPropernames=光明使者\n".encode("gbk"),
    })

    records = collect_text_object_records(archive)

    assert [(record.obj_id, record.fields["Name"]) for record in records] == [("H001", "圣骑士")]


def test_func_and_strings_merge_by_field_role_not_archive_order() -> None:
    archive = FakeArchive({
        "Units\\HumanUnitStrings.txt": b"[H001]\nName=Localized\nUbertip=Readable\n",
        "Units\\HumanUnitFunc.txt": b"[H001]\nName=Internal\nHP=1000\n",
    }, reverse_listing=True)

    record = merge_text_object_records(collect_text_object_records(archive))[0]

    assert record.fields == {"Name": "Localized", "Ubertip": "Readable", "HP": "1000"}
```

- [x] **Step 2: Run the tests and confirm current discovery fails**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_object_text_sources.py -q -p no:cacheprovider`

Expected: FAIL because trusted named files are not an independent source and GBK currently becomes replacement characters.

- [x] **Step 3: Implement immutable records and trusted-name matching**

```python
class TextObjectSourceKind(StrEnum):
    FUNC = "func"
    STRINGS = "strings"
    ANONYMOUS = "anonymous"


@dataclass(frozen=True, slots=True)
class TextObjectRecord:
    category: str
    obj_id: str
    fields: Mapping[str, str]
    field_sources: Mapping[str, str]
    source_name: str
    source_kind: TextObjectSourceKind


_TRUSTED_NAME = re.compile(
    r"(?:^|[\\/])(?:[a-z]+)?(?:unit|item|ability|upgrade)(func|strings)\.txt$",
    re.IGNORECASE,
)
```

Normalize and sort archive names case-insensitively, parse every trusted file with valid sections regardless of record count, and use anonymous block scanning only when the archive exposes block operations. Apply the existing `len(records) >= 8` requirement only to anonymous blocks.

- [x] **Step 4: Implement deterministic Func/Strings field merge**

```python
_DISPLAY_FIELDS = frozenset({
    "name", "propernames", "tip", "ubertip", "description", "editorsuffix",
})


def _field_rank(kind: TextObjectSourceKind, field_name: str) -> int:
    is_display = field_name.casefold() in _DISPLAY_FIELDS
    if is_display:
        return 30 if kind is TextObjectSourceKind.STRINGS else 20
    return 30 if kind is TextObjectSourceKind.FUNC else 20
```

Group by `(category, obj_id)`, choose the highest-ranked non-empty value per field, and use normalized source-name order as the final tie-breaker. Preserve the winning source name in `field_sources` on the merged record.

- [x] **Step 5: Run text source tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_object_text_sources.py tests/test_textobj.py tests/test_war3_encoding.py -q -p no:cacheprovider`

Expected: PASS.

- [x] **Step 6: Commit text-source discovery**

```bash
git add w3xtool/object_text_sources.py w3xtool/textobj.py w3xtool/map_archive_reader.py tests/test_object_text_sources.py
git commit -m "fix: recover Warcraft text object sources"
```

### Task 3: Deterministic Object Candidate Merge Pipeline

**Files:**
- Create: `w3xtool/object_pipeline.py`
- Create: `w3xtool/object_candidates.py`
- Modify: `w3xtool/api.py:116-420`
- Modify: `w3xtool/slk_objects.py`
- Modify: `w3xtool/references.py`
- Create: `tests/test_object_pipeline.py`
- Modify: `tests/test_slk_objects.py`
- Modify: `tests/test_base_objects.py`

**Interfaces:**
- Produces: `ObjectSourceKind`, `ObjectFieldValue`, `ObjectCandidate`, `merge_object_candidates(candidates, base_objects) -> tuple[GameObject, ...]`.
- Produces: `load_object_pipeline(md, archive, wts, *, prefix="war3map", base_objects=BASE_OBJECTS) -> None`.
- Consumes: Task 2 text records, `parse_object_data`, `parse_category_objects`, and reference extractors.

- [x] **Step 1: Write pure merge regression tests**

```python
def test_text_and_binary_candidates_coexist_without_category_suppression() -> None:
    merged = merge_object_candidates(
        (
            candidate("单位", "H001", "hfoo", TEXT_STRINGS, {"display:name": "自定义步兵"}),
            candidate("单位", "H002", "hfoo", BINARY, {"binary:uhpm": "2500"}),
        ),
        BASE_OBJECTS,
    )

    assert {obj.obj_id for obj in merged} == {"H001", "H002"}


def test_custom_object_inherits_base_without_aliasing_base_id() -> None:
    merged = merge_object_candidates(
        (candidate("单位", "H001", "hfoo", BINARY, {"display:name": "强化步兵"}),),
        {"hfoo": ("单位", [("生命上限", "420"), ("移动速度", "270")])},
    )
    index = build_object_index(merged)

    assert dict(merged[0].fields)["生命上限"] == "420"
    assert index["H001"] is merged[0]
    assert "hfoo" not in index
```

Add separate tests for WTS resolution in text and SLK values, binary+SLK supplementation, duplicate candidates, reference union, and derived search/icon rebuilding.

- [x] **Step 2: Run merge tests and confirm old behavior loses data**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_object_pipeline.py tests/test_slk_objects.py -q -p no:cacheprovider`

Expected: FAIL because the candidate modules do not exist and binary objects currently reject SLK supplementation.

- [x] **Step 3: Implement canonical candidates and field priority**

```python
class ObjectSourceKind(IntEnum):
    BASE = 10
    SLK = 20
    TEXT_FUNC = 30
    BINARY = 40
    TEXT_STRINGS = 50


@dataclass(frozen=True, slots=True)
class ObjectFieldValue:
    key: str
    label: str
    value: str
    source: str
    source_kind: ObjectSourceKind


@dataclass(frozen=True, slots=True)
class ObjectCandidate:
    category: str
    obj_id: str
    base_id: str
    is_custom: bool
    ext: str
    fields: tuple[ObjectFieldValue, ...]
    refs: tuple[tuple[str, tuple[str, ...]], ...]
```

Canonicalize display aliases (`Name`/`unam`/`anam`/`gnam`, `Propernames`, Tip, Ubertip/description, icon) before merging. For non-display conflicts, binary beats Func; Strings beats other sources only for display fields. Resolve WTS and WESTRING before storing candidate values.

- [x] **Step 4: Implement merge, inheritance, deduplication, and derived fields**

```python
def build_object_index(objects: Iterable[GameObject]) -> dict[str, GameObject]:
    index: dict[str, GameObject] = {}
    for obj in objects:
        index.setdefault(obj.obj_id, obj)
    return index


def merge_object_candidates(
    candidates: Iterable[ObjectCandidate],
    base_objects: Mapping[str, tuple[str, list[tuple[str, str]]]],
) -> tuple[GameObject, ...]:
    grouped = _group_candidates(candidates)
    return tuple(
        _materialize_object(key, grouped[key], base_objects)
        for key in sorted(grouped, key=lambda item: (item[0], item[1].encode("latin-1", "replace")))
    )
```

Materialization starts from matching base fields, applies candidate fields by the explicit priority rule, unions references by `(label, code)`, then derives `name`, `icon`, labels, `search_text`, `field_values`, and `field_sources` from the final state.

- [x] **Step 5: Replace category-level assembly in `api.py`**

`load_map` must parse WTS before objects, collect all base/SLK/binary/text candidates, call one pipeline, populate each category bucket once, and set `obj_index` only from final `obj_id` values. Remove `_add_text_objects`, `_add_binary_objects`, and binary rejection in `_add_slk_objects`; preserve compatibility wrappers only when an existing test imports them.

- [x] **Step 6: Run object integration tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_object_pipeline.py tests/test_slk_objects.py tests/test_base_objects.py tests/test_w3obj.py tests/test_references.py tests/test_static_extraction_workflow.py -q -p no:cacheprovider`

Expected: PASS with no duplicate object codes.

- [x] **Step 7: Commit the unified object pipeline**

```bash
git add w3xtool/object_candidates.py w3xtool/object_pipeline.py w3xtool/api.py w3xtool/slk_objects.py w3xtool/references.py tests/test_object_pipeline.py tests/test_slk_objects.py tests/test_base_objects.py
git commit -m "fix: merge every object data source"
```

### Task 4: Reference-Compatible Sorted ID Reports

**Files:**
- Modify: `w3xtool/knowledge_object_exports.py`
- Modify: `w3xtool/gui_export_actions.py`
- Create: `tests/test_reference_id_reports.py`
- Modify: `tests/test_knowledge_pack.py`

**Interfaces:**
- Produces: `sorted_unique_objects(objects) -> tuple[GameObject, ...]`.
- Changes compatibly: `format_box_id_text(objects, *, category=None) -> str`; existing one-argument calls remain valid.
- Uses: `GameObject.field_values` with a label-based fallback for old callers.

- [x] **Step 1: Write ordering, deduplication, title, and WTS-output tests**

```python
def test_unit_box_report_is_sorted_unique_and_includes_propernames() -> None:
    objects = (
        game_object("H010", "后一个", {"display:propernames": "称谓乙", "display:description": "说明乙"}),
        game_object("H001", "前一个", {"display:propernames": "称谓甲", "display:description": "说明甲"}),
        game_object("H001", "重复项", {}),
    )

    text = format_box_id_text(objects, category="单位")

    assert text.index("ID：H001") < text.index("ID：H010")
    assert text.count("ID：H001") == 1
    assert "描述：称谓：称谓甲\n\n说明甲" in text
```

- [x] **Step 2: Run the report tests and confirm current output fails**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_reference_id_reports.py -q -p no:cacheprovider`

Expected: FAIL because current output preserves input order, duplicates IDs, and omits `称谓`.

- [x] **Step 3: Implement one shared ordered view and reference layout**

```python
def sorted_unique_objects(objects: Iterable[GameObject]) -> tuple[GameObject, ...]:
    by_id: dict[str, GameObject] = {}
    for obj in objects:
        by_id.setdefault(obj.obj_id, obj)
    return tuple(by_id[key] for key in sorted(by_id, key=lambda code: code.encode("latin-1", "replace")))
```

Use this view in TSV and box writers. A unit block writes
`描述：称谓：<Propernames>`, one blank line, then its Ubertip/Description; other categories retain
ID/name/description. Preserve Warcraft rich-text markers in the box-compatible value. Resolve the
description from canonical `display:description`, then existing labeled fields, then `-`.

- [x] **Step 4: Run report and pack tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_reference_id_reports.py tests/test_knowledge_pack.py tests/test_gui_export_safety.py -q -p no:cacheprovider`

Expected: PASS.

- [x] **Step 5: Commit report parity**

```bash
git add w3xtool/knowledge_object_exports.py w3xtool/gui_export_actions.py tests/test_reference_id_reports.py tests/test_knowledge_pack.py
git commit -m "fix: match reference object ID reports"
```

### Task 5: MPQ Layout, Filename Bytes, and Locale Selection

**Files:**
- Create: `w3xtool/mpq_constants.py`
- Create: `w3xtool/mpq_crypto.py`
- Create: `w3xtool/mpq_layout.py`
- Create: `w3xtool/mpq_names.py`
- Modify: `w3xtool/mpq.py`
- Create: `tests/test_mpq_user_data.py`
- Create: `tests/test_mpq_names_locale.py`
- Modify: `tests/test_mpq_header.py`

**Interfaces:**
- Produces: `MPQLayout`, `locate_mpq_layout(data) -> MPQLayout`, `hash_name_bytes(name, hash_type) -> int`, and `encoded_name_candidates(name, legacy_codecs=None) -> tuple[bytes, ...]`.
- Changes compatibly: `MPQArchive(path, *, locale_id=0, legacy_codecs=None)`.
- Re-exports existing constants and `_hash` from `w3xtool.mpq` for compatibility.

- [x] **Step 1: Write user-data, non-ASCII hash, and locale fallback tests**

```python
def test_mpq_user_data_header_points_to_real_archive() -> None:
    path = write_fixture(_wrap_with_user_data(_minimal_mpq_bytes(), payload=b"author metadata"))

    with MPQArchive(path) as archive:
        assert archive.read_file("war3map.j").startswith(b"function main")


def test_gbk_filename_hashes_bytes_not_unicode_codepoints() -> None:
    candidates = encoded_name_candidates("单位数据.txt", legacy_codecs=("gbk",))

    assert candidates == ("单位数据.txt".encode("gbk"),)
    assert hash_name_bytes(candidates[0], HASH_NAME_A) == STORMLIB_GBK_NAME_A


def test_locale_selection_prefers_requested_then_neutral() -> None:
    entries = (
        _entry(locale=0, platform=0, block=1),
        _entry(locale=0, platform=0, block=3),
        _entry(locale=0x0404, platform=0, block=2),
    )

    assert select_hash_entry(entries, locale_id=0x0404).block_index == 2
    assert select_hash_entry(entries, locale_id=0x0804).block_index == 3
```

- [x] **Step 2: Run layout tests and confirm failures**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_mpq_user_data.py tests/test_mpq_names_locale.py tests/test_mpq_header.py -q -p no:cacheprovider`

Expected: FAIL on user-data lookup, byte hashing, or locale preference.

- [x] **Step 3: Split constants/crypto and implement byte hashing**

```python
def hash_name_bytes(name: bytes, hash_type: int) -> int:
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE
    for byte in name.translate(_ASCII_UPPER_TABLE):
        value = CRYPT_TABLE[(hash_type << 8) + byte]
        seed1 = (value ^ ((seed1 + seed2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        seed2 = (byte + seed1 + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
    return seed1
```

`encoded_name_candidates` returns unique byte sequences in UTF-8 and configured Warcraft legacy codec order, with ASCII producing one candidate. File-key hashing uses only the basename bytes from the candidate that matched the hash entry.

- [x] **Step 4: Implement MPQ/UserData layout parsing and locale choice**

```python
@dataclass(frozen=True, slots=True)
class MPQLayout:
    archive_offset: int
    header_size: int
    format_version: int
    sector_shift: int
    hash_table_offset: int
    block_table_offset: int
    hash_count: int
    block_count: int
```

Recognize `MPQ\x1b`, validate its user-data size and `header_offset`, then validate the referenced
`MPQ\x1a` header. Retain the existing 512-byte aligned recovery scan for HM3W/protected maps.
Gather all matching hash entries in probe order. For nonzero requested locale/platform, return the
first exact pair; otherwise retain the last entry whose locale is requested-or-neutral and whose
platform is requested-or-neutral, matching StormLib 9.25 `GetHashEntryLocale`.

- [x] **Step 5: Run all MPQ layout and lookup tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_mpq_user_data.py tests/test_mpq_names_locale.py tests/test_mpq_header.py tests/test_mpq_enumerate.py tests/test_mpq_robust.py -q -p no:cacheprovider`

Expected: PASS.

- [x] **Step 6: Commit layout/name compatibility**

```bash
git add w3xtool/mpq_constants.py w3xtool/mpq_crypto.py w3xtool/mpq_layout.py w3xtool/mpq_names.py w3xtool/mpq.py tests/test_mpq_user_data.py tests/test_mpq_names_locale.py tests/test_mpq_header.py
git commit -m "fix: match StormLib MPQ lookup behavior"
```

### Task 6: StormLib-Compatible Compression Dispatch

**Files:**
- Create: `w3xtool/mpq_compression.py`
- Create: `w3xtool/mpq_adpcm.py`
- Create: `w3xtool/mpq_block_reader.py`
- Modify: `w3xtool/mpq.py`
- Create: `tests/test_mpq_compression_chain.py`
- Create: `tests/test_mpq_adpcm.py`
- Create: `tests/test_mpq_lzma.py`
- Add: `tests/fixtures/reference/stormlib-compression-*`
- Modify: `tests/fixtures/reference/README.md`

**Interfaces:**
- Produces: `decompress_mpq_sector(data: bytes, output_size: int) -> bytes`.
- Produces: `decompress_adpcm(data: bytes, channels: Literal[1, 2], output_size: int) -> bytes`.
- Produces: `read_mpq_block(storage, block, name_bytes, key) -> bytes`.
- Re-exports `_decompress_sector = decompress_mpq_sector` through `w3xtool.mpq`.

- [x] **Step 1: Vendor or generate pinned StormLib fixtures and write red tests**

Record the StormLib 9.25 release/commit shown by the reference DLL build path, compiler command,
input SHA256, output SHA256, compression mask, and license in
`tests/fixtures/reference/README.md`. The latest stable StormLib may be run as a compatibility
cross-check, but fixture truth remains 9.25.

```python
@pytest.mark.parametrize("fixture_name", (
    "stormlib-compression-huffman-adpcm-mono.bin",
    "stormlib-compression-huffman-adpcm-stereo.bin",
    "stormlib-compression-zlib-sparse.bin",
))
def test_stormlib_combined_compression_fixture(fixture_name: str) -> None:
    compressed, expected = read_compression_fixture(fixture_name)

    assert decompress_mpq_sector(compressed, len(expected)) == expected


def test_stormlib_lzma_marker_dispatches_as_lzma() -> None:
    compressed, expected = read_compression_fixture("stormlib-compression-lzma.bin")

    assert decompress_mpq_sector(compressed, len(expected)) == expected
```

- [x] **Step 2: Run compression tests and confirm unsupported-mask failures**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_mpq_compression_chain.py tests/test_mpq_adpcm.py tests/test_mpq_lzma.py -q -p no:cacheprovider`

Expected: FAIL because current code uses one `elif` branch and has no ADPCM/LZMA decoder.

- [x] **Step 3: Implement bounded LZMA and reverse chain dispatch**

```python
def decompress_mpq_sector(data: bytes, output_size: int) -> bytes:
    if not data:
        return b""
    marker = data[0]
    payload = data[1:]
    if marker == MPQ_COMPRESSION_LZMA:
        return _decompress_lzma(payload, output_size)
    remaining = marker
    for flag, decoder in _STORMLIB_REVERSE_ORDER:
        if remaining & flag:
            payload = decoder(payload, output_size)
            remaining &= ~flag
    if remaining:
        raise MPQCompressionError(marker, f"unsupported bits 0x{remaining:02X}")
    if len(payload) > output_size:
        raise MPQCompressionError(marker, "decoded output exceeds declared size")
    return payload
```

Define `_STORMLIB_REVERSE_ORDER` exactly as bzip2, PKWARE, zlib, Huffman,
ADPCM stereo, ADPCM mono, and sparse. Reject a mask containing both ADPCM modes.
For LZMA, require StormLib's 14-byte payload header: one zero filter byte, five encoded
properties, and an eight-byte little-endian original length, followed by the raw LZMA stream.
Reject nonzero filters and declared lengths larger than the sector contract. Parse the five
properties into an `lzma.FILTER_LZMA1` raw filter and cap output at the smaller matching declared
size; preserve exact valid shorter final sectors.

- [x] **Step 4: Port bounded mono/stereo ADPCM decompression**

Port StormLib's adaptive step table and channel predictor state into `mpq_adpcm.py`. Reject truncated headers, invalid channel counts, and writes beyond `output_size`; emit little-endian signed 16-bit samples.

- [x] **Step 5: Move block reading out of oversized `mpq.py`**

Move sector offsets, single-unit, encrypted sector, CRC-table, anonymous-key recovery, and first-sector peek logic to `mpq_block_reader.py`. `MPQArchive.read_file`, `decompress_block`, `read_block_anon`, and `peek_block` delegate to it while retaining current exceptions and bounds.

- [x] **Step 6: Run compression and full MPQ regression tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_mpq_compression_chain.py tests/test_mpq_adpcm.py tests/test_mpq_lzma.py tests/test_huffman.py tests/test_explode.py tests/test_decompress_limits.py tests/test_mpq_robust.py tests/test_mpq_enumerate.py -q -p no:cacheprovider`

Expected: PASS.

- [x] **Step 7: Commit compression parity**

```bash
git add w3xtool/mpq_compression.py w3xtool/mpq_adpcm.py w3xtool/mpq_block_reader.py w3xtool/mpq.py tests/test_mpq_compression_chain.py tests/test_mpq_adpcm.py tests/test_mpq_lzma.py tests/fixtures/reference
git commit -m "feat: decode StormLib MPQ compression chains"
```

### Task 7: Readable Script Sources and Complete ECA Semantics

**Files:**
- Create: `w3xtool/script_sources.py`
- Modify: `w3xtool/api.py`
- Modify: `w3xtool/wct.py`
- Modify: `w3xtool/script_text_export.py`
- Modify: `w3xtool/trigger_exports.py`
- Modify: `w3xtool/gui_trigger_eca.py`
- Modify: `w3xtool/knowledge_pack.py`
- Create: `tests/test_script_sources.py`
- Modify: `tests/test_wct.py`
- Modify: `tests/test_wtg_eca_exports.py`
- Modify: `tests/test_triggerdata_semantics.py`

**Interfaces:**
- Produces: `collect_readable_scripts(archive) -> ScriptCollection` and `analysis_script_texts(md) -> tuple[tuple[str, str], ...]`.
- `ScriptCollection` includes `texts`, `wct_diagnostic`, and `binary_members` but publishes only readable text.
- Changes compatibly: `format_trigger_eca_tsv(summary, *, trigger_data=None, wts=None, object_names=None) -> str`.

- [x] **Step 1: Write dual-language, binary-exclusion, WCT, and array-index tests**

```python
def test_jass_and_lua_are_both_analyzed_but_wtg_and_raw_wct_are_not_text() -> None:
    md = load_map(str(map_with_jass_lua_wtg_wct()))

    assert "war3map.j" in md.scripts
    assert "war3map.lua" in md.scripts
    assert "war3map.wtg" not in md.scripts
    assert "war3map.wct" not in md.scripts
    assert list(name for name in md.scripts if "wct" in name.casefold()) == ["war3map.wct(自定义代码).txt"]


def test_eca_tsv_renders_wts_object_name_and_array_index() -> None:
    text = format_trigger_eca_tsv(
        summary_with_array_parameter("TRIGSTR_001", "H001", index="3"),
        trigger_data=fixture_trigger_data(),
        wts={1: "开始游戏"},
        object_names={"H001": "圣骑士"},
    )

    assert "开始游戏" in text
    assert "圣骑士(H001)" in text
    assert "数组索引" in text and "\t3\t" in text
```

- [x] **Step 2: Run focused tests and confirm publication gaps**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_script_sources.py tests/test_wct.py tests/test_wtg_eca_exports.py -q -p no:cacheprovider`

Expected: FAIL because binary WTG/WCT are loaded into `md.scripts`, `_best_script_text` drops the second language, and array indexes are not exported.

- [x] **Step 3: Implement readable source collection and per-language analysis**

```python
@dataclass(frozen=True, slots=True)
class ScriptCollection:
    texts: Mapping[str, str]
    binary_members: tuple[str, ...]
    wct_diagnostic: str | None


def analysis_script_texts(md: MapData) -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, text)
        for name, text in sorted(md.scripts.items())
        if name.casefold().endswith((".j", ".lua", ".txt")) and not name.casefold().endswith(".wts")
    )
```

Decode JASS, Lua, and WTS with `decode_warcraft_string`. Parse WCT bytes once and publish only its virtual `.txt` output. Replace `_best_script_text` callers with iteration over both primary scripts or a labeled concatenation where the downstream scanner accepts one string.

- [x] **Step 4: Add partial WCT diagnostics and full ECA recursion**

Make `parse_wct` return confirmed blocks plus a typed truncation/version diagnostic. In ECA export, pass WTS/object maps to `render_eca_semantic`; recursively emit `nested_function`, `children`, and `array_indexer` using distinct row labels and depth.

- [x] **Step 5: Run script, trigger, UI, and pack tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_script_sources.py tests/test_wct.py tests/test_script_scan.py tests/test_script_function_index.py tests/test_script_global_index.py tests/test_wtg_eca_exports.py tests/test_triggerdata_semantics.py tests/test_gui_trigger_eca.py tests/test_knowledge_pack.py -q -p no:cacheprovider`

Expected: PASS.

- [x] **Step 6: Commit script/ECA publication fixes**

```bash
git add w3xtool/script_sources.py w3xtool/api.py w3xtool/wct.py w3xtool/script_text_export.py w3xtool/trigger_exports.py w3xtool/gui_trigger_eca.py w3xtool/knowledge_pack.py tests/test_script_sources.py tests/test_wct.py tests/test_wtg_eca_exports.py tests/test_triggerdata_semantics.py
git commit -m "fix: publish every readable script and ECA value"
```

### Task 8: Persistent Campaign Child Sources and W3F Map Order

**Files:**
- Create: `w3xtool/campaign_sources.py`
- Modify: `w3xtool/api.py`
- Modify: `w3xtool/w3i.py`
- Modify: `w3xtool/knowledge_assets.py`
- Modify: `w3xtool/knowledge_terrain_exports.py`
- Modify: `w3xtool/map_identity.py`
- Modify: `w3xtool/gui_export_actions.py`
- Create: `tests/test_campaign_sources.py`
- Modify: `tests/test_campaign.py`
- Modify: `tests/test_w3i.py`

**Interfaces:**
- Produces: `CampaignMapEntry`, `W3fInfo.maps`, and `campaign_inner_maps(w3f, archive_names) -> tuple[str, ...]`.
- Consumes: Task 1 `BytesArchiveSource`.
- Changes: all archive-backed reports call `md.archive_source.open()` through `open_map_source(md)`.

- [x] **Step 1: Write persistent child and declared-order tests**

```python
def test_campaign_child_remains_reopenable_after_parent_load() -> None:
    campaign = load_map(str(REFERENCE_CAMPAIGN))
    child = campaign.sub_maps[0]

    assert child.path == "Maps\\Chapter01.w3x"
    with child.archive_source.open() as archive:
        assert archive.has_file("war3map.w3e")
    assert build_map_identity(child).sha1
    assert build_terrain_export_data(child).terrain is not None


def test_w3f_declared_map_order_wins_over_listfile_order() -> None:
    info = parse_w3f(build_w3f_with_maps(("Maps\\B.w3x", "Maps\\A.w3x")))

    assert tuple(entry.path for entry in info.maps) == ("Maps\\B.w3x", "Maps\\A.w3x")
```

- [x] **Step 2: Run campaign tests and confirm source disappearance**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_campaign_sources.py tests/test_campaign.py tests/test_w3i.py -q -p no:cacheprovider`

Expected: FAIL because child `path` is a non-existent logical name and W3F stops at the header.

- [x] **Step 3: Parse bounded W3F map entries**

Extend `W3fInfo` with `maps: list[CampaignMapEntry]`. Parse the version-specific campaign flags, background/minimap fields, ambient data, fog, UI race, and map-entry count using bounded readers; each entry retains path and display name. On truncation, preserve the header and confirmed entries while recording a diagnostic.

- [x] **Step 4: Load children from owned bytes and route all reopeners**

```python
def open_map_source(md: MapData) -> ContextManager[MapArchiveReader]:
    if md.archive_source is not None:
        return md.archive_source.open()
    return PathArchiveSource(md.path).open()
```

When reading a child member, create `BytesArchiveSource(inner, data)`, pass it into `load_map`, retain the logical path, and attach the source to the child. Replace direct `MPQArchive(md.path)` use in identity, terrain, assets, resource bodies, and selected-child export.

- [x] **Step 5: Run campaign, terrain, resource, and export tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_campaign_sources.py tests/test_campaign.py tests/test_w3i.py tests/test_batch_extraction_gaps.py tests/test_resource_inventory.py tests/test_gui_campaign.py -q -p no:cacheprovider`

Expected: PASS.

- [x] **Step 6: Commit campaign source fixes**

```bash
git add w3xtool/campaign_sources.py w3xtool/api.py w3xtool/w3i.py w3xtool/knowledge_assets.py w3xtool/knowledge_terrain_exports.py w3xtool/map_identity.py w3xtool/gui_export_actions.py tests/test_campaign_sources.py tests/test_campaign.py tests/test_w3i.py
git commit -m "fix: keep campaign child archives readable"
```

### Task 9: Unified CASC Inventory and Client Data Enrichment

**Files:**
- Create: `w3xtool/game_data_inventory.py`
- Modify: `w3xtool/game_data_source.py`
- Modify: `w3xtool/casc_source.py`
- Modify: `w3xtool/casc_cli.py`
- Modify: `w3xtool/gui_lifecycle.py`
- Modify: `w3xtool/gui_casc_browser.py`
- Modify: `w3xtool/object_pipeline.py`
- Modify: `w3xtool/knowledge_assets.py`
- Modify: `w3xtool/knowledge_resource_exports.py`
- Create: `tests/test_game_data_inventory.py`
- Modify: `tests/test_casc_source.py`
- Modify: `tests/test_game_data_source.py`
- Modify: `tests/test_gui_casc_browser.py`

**Interfaces:**
- Produces: `GameDataEntry`, `GameDataInventorySource.iter_entries(mask="*")`, and `supports_inventory(source) -> bool`.
- Adds `DirectoryDataSource.iter_entries` and path-map `CascDataSource.iter_entries` with known-path semantics.
- Changes CLI/browser construction to `open_game_data_source` instead of direct `CascLibDataSource`.
- Supplies selected game data to base-object construction and referenced-icon export.

- [x] **Step 1: Write directory/path-map inventory and enrichment tests**

```python
@pytest.mark.parametrize("source_factory", (directory_source, path_map_source))
def test_readable_fallback_sources_expose_known_path_inventory(source_factory) -> None:
    source = source_factory({"Units\\HumanUnitStrings.txt": b"[hfoo]\nName=Footman\n"})

    entries = tuple(source.iter_entries("*UnitStrings.txt"))

    assert [entry.name for entry in entries] == ["Units\\HumanUnitStrings.txt"]
    assert all(entry.name_type is CascNameType.FULL for entry in entries)


def test_client_icon_used_by_object_is_exported_with_source_label() -> None:
    report = export_referenced_client_assets(map_with_icon("ReplaceableTextures\\CommandButtons\\BTNHero.blp"), source)

    assert report.items[0].status == "已导出"
    assert report.items[0].source == "客户端数据"
```

- [x] **Step 2: Run CASC tests and confirm hard-coded backend failures**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_game_data_inventory.py tests/test_game_data_source.py tests/test_gui_casc_browser.py -q -p no:cacheprovider`

Expected: FAIL because only CascLib exposes `iter_entries`, the GUI checks `backend == "casclib"`, and the CLI constructs CascLib directly.

- [x] **Step 3: Implement the inventory capability adapter**

```python
@runtime_checkable
class GameDataInventorySource(GameDataSource, Protocol):
    def iter_entries(self, mask: str = "*") -> Generator[CascEntry, None, None]:
        raise NotImplementedError


def supports_inventory(source: GameDataSource | None) -> TypeGuard[GameDataInventorySource]:
    return source is not None and callable(getattr(source, "iter_entries", None))
```

Directory and path-map sources enumerate their indexed known paths in sorted order and use glob matching. They do not invent FileDataID/CKey/EKey values and report their view as `known_paths`; CascLib keeps `full_root`.

- [x] **Step 4: Route GUI/CLI and enrichment through the common source**

Enable the browser when `probe.is_readable` and the opened source supports inventory. CLI inventory/extract opens through `open_game_data_source` and reports whether the view is full Root or known paths. Pass the same source into `load_object_pipeline` for missing base data and into knowledge assets for referenced client icons; label all external bodies explicitly.

- [x] **Step 5: Run CASC, icon, object, and GUI tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_game_data_inventory.py tests/test_casc_source.py tests/test_game_data_source.py tests/test_casc_inventory.py tests/test_gui_casc_browser.py tests/test_icons_cache.py tests/test_object_pipeline.py -q -p no:cacheprovider`

Expected: PASS; Windows-only native tests remain conditionally skipped on macOS.

- [x] **Step 6: Commit data-source consistency**

```bash
git add w3xtool/game_data_inventory.py w3xtool/game_data_source.py w3xtool/casc_source.py w3xtool/casc_cli.py w3xtool/gui_lifecycle.py w3xtool/gui_casc_browser.py w3xtool/object_pipeline.py w3xtool/knowledge_assets.py w3xtool/knowledge_resource_exports.py tests/test_game_data_inventory.py tests/test_casc_source.py tests/test_game_data_source.py tests/test_gui_casc_browser.py
git commit -m "feat: unify Warcraft client data sources"
```

### Task 10: Structured Publication Results, End-to-End Parity, and Documentation

**Files:**
- Create: `w3xtool/knowledge_results.py`
- Modify: `w3xtool/knowledge_io.py`
- Modify: `w3xtool/knowledge_pack.py`
- Modify: `w3xtool/knowledge_manifest.py`
- Modify: `w3xtool/knowledge_requirements.py`
- Modify: `w3xtool/map_extras.py`
- Create: `w3xtool/knowledge_diagnostics.py`
- Modify: `w3xtool/gui_export_actions.py`
- Modify: `w3xtool/cli_output.py`
- Modify: `README.md`
- Modify: `docs/KKWE借鉴清单.md`
- Create: `tests/test_knowledge_results.py`
- Create: `tests/test_reference_extraction_parity.py`
- Create: `tests/test_component_diagnostics.py`
- Modify: `tests/test_static_extraction_workflow.py`
- Modify: `tests/test_requirement_coverage_dynamic.py`

**Interfaces:**
- Produces: `KnowledgeWriteItem`, `KnowledgeWriteReport`, and `write_knowledge_pack_report(md, out_dir, ...) -> KnowledgeWriteReport`.
- Preserves: `write_knowledge_pack(...) -> int` by returning `report.written_count`.
- Produces: component-diagnostic and write-failure TSV sections in the pack manifest.

- [x] **Step 1: Write failed-write and full reference-parity tests**

```python
def test_pack_reports_partial_success_instead_of_counting_failed_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("w3xtool.knowledge_io.write_text_safely", fail_only("对象ID/单位.tsv"))

    report = write_knowledge_pack_report(minimal_map_data(), str(tmp_path))

    assert report.failed_count == 1
    assert report.status is KnowledgeWriteStatus.PARTIAL
    assert report.items_by_path["对象ID/单位.tsv"].error


def test_reference_extraction_fixture_produces_complete_sorted_four_category_reports(tmp_path) -> None:
    md = load_map(str(REFERENCE_PARITY_MAP))
    report = write_knowledge_pack_report(md, str(tmp_path))

    assert report.failed_count == 0
    for category in ("单位", "物品", "技能", "科技"):
        text = (tmp_path / "盒子兼容ID" / f"{category}ID.txt").read_text(encoding="utf-8")
        ids = re.findall(r"^ID：(....)$", text, re.MULTILINE)
        assert ids == sorted(set(ids), key=lambda code: code.encode("latin-1"))
        assert "TRIGSTR_" not in text
```

Create and pin two fixtures: `stormlib-reference-parity-map.w3x` contains GBK Func/Strings,
WTS, overlapping text/binary objects, SLK supplementation, four categories, JASS+Lua, and
WTG/WCT; `stormlib-reference-parity-campaign.w3n` contains that map as a declared child.
Record both SHA256 values and the pinned StormLib generation command.

- [x] **Step 2: Run publication/E2E tests and confirm failures**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_knowledge_results.py tests/test_reference_extraction_parity.py tests/test_static_extraction_workflow.py -q -p no:cacheprovider`

Expected: FAIL because writes collapse to integer counts and not all parity conditions are implemented.

- [x] **Step 3: Implement detailed write results and compatibility facade**

```python
class KnowledgeWriteStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class KnowledgeWriteItem:
    path: str
    written: bool
    size: int
    error: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeWriteReport:
    items: tuple[KnowledgeWriteItem, ...]

    @property
    def written_count(self) -> int:
        return sum(item.written for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(not item.written for item in self.items)

    @property
    def status(self) -> KnowledgeWriteStatus:
        if self.failed_count == 0:
            return KnowledgeWriteStatus.COMPLETE
        if self.written_count == 0:
            return KnowledgeWriteStatus.FAILED
        return KnowledgeWriteStatus.PARTIAL

    @property
    def items_by_path(self) -> Mapping[str, KnowledgeWriteItem]:
        return {item.path: item for item in self.items}
```

Use a `ContextVar[KnowledgeWriteRecorder | None]` in `knowledge_io`: existing writers keep
returning integer counts, while `write_text` and explicit binary-body writers record each real
`SafeWriteResult` when a report session is active. The integer facade returns `written_count`.
GUI and CLI show complete/partial/failed with counts and the first failure. Write
`组件诊断.tsv` from `MapData.diagnostics` and write `资料包写入结果.tsv` last; then refresh
`需求覆盖.tsv` so its publication status reflects the completed session.

- [x] **Step 4: Replace component-level silent failure with diagnostics**

Add `read_component(md, component, source, operation, recoverable=True)` in
`extraction_diagnostics.py`. Use it in `api.py` and `map_extras.py` for WTS, scripts, SLK,
W3I/W3F, WCT, WTG, world data, WGC, preview, and imports. Missing optional members are not
errors; an existing member that fails decoding or parsing records a warning/error with the
exception type and source name. Format all collected entries through
`knowledge_diagnostics.format_component_diagnostics_tsv(md)`.

- [x] **Step 5: Update dynamic coverage and user-facing documentation**

Coverage uses actual object-source counts, unresolved WTS count, script-source count, child-source readability, game-data inventory capability, component diagnostics, and write report. README and `KKWE借鉴清单.md` list what is complete, partial, runtime-only, and externally skipped; they must not claim Windows real-install PASS without an acceptance artifact.

- [x] **Step 6: Run the complete automated verification matrix**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -q -p no:cacheprovider`

Expected: PASS with zero failures; platform-dependent Windows tests may report explicit skips.

Run: `uv run python -m compileall -q w3xtool main.py`

Expected: exit 0.

Run: `uv run main.py cli tests/fixtures/reference/stormlib-slk-map.w3x`

Expected: exit 0 with non-zero object counts and no traceback.

Run: `uv run main.py cli tests/fixtures/reference/stormlib-campaign.w3n --pack "${TMPDIR:-/tmp}/w3xray-parity-pack"`

Expected: exit 0, a complete or explicitly partial report, and readable child terrain/resource outputs.

- [ ] **Step 7: Execute GUI and Windows packaging acceptance**

Run the Tk GUI smoke tests on macOS through the repository's established headless mechanism, then run or dispatch `.github/workflows/windows-package.yml`. If a real Windows Warcraft installation is unavailable, preserve `windows-real-war3` as SKIP and state that fact; do not convert it to PASS.

Local acceptance evidence (2026-07-11): the complete suite returned
`1001 passed, 4 skipped, 1 subtests passed`; source acceptance passed map load,
campaign switching, an 87-file knowledge pack, five repeat loads, and all nine GUI
tabs. `windows_runtime` and `real_windows_casc` remain explicit SKIP until the
hosted Windows workflow runs and a real Warcraft installation is supplied.

- [x] **Step 8: Review changes and remove temporary artifacts**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intended source, tests, fixtures, and docs remain. Remove `${TMPDIR:-/tmp}/codex-w3xray-reference-audit-20260710`, `.debug-journal.md`, and the local exclude entry after extracting any required non-sensitive evidence into committed tests/docs.

- [ ] **Step 9: Commit final integration and push**

```bash
git add w3xtool tests README.md docs/KKWE借鉴清单.md
git commit -m "feat: complete reference extraction parity"
git push origin local
```

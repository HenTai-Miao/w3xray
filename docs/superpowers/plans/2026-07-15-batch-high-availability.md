# Batch High-Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every batch publication content-verifiable and crash-recoverable, reuse unchanged partial results, bound batch and GUI workers, and enforce the changed-path quality and cross-platform acceptance gates.

**Architecture:** Add durable I/O primitives below the existing safe writer, then publish immutable per-map manifests through an explicit recoverable transaction. Make one validated global generation the only resume/cache authority, split orchestration from validation/execution, and route GUI workers through a shared cancellation registry with a bounded shutdown deadline.

**Tech Stack:** Python 3.14 standard library, frozen dataclasses/StrEnum/Protocol, multiprocessing spawn, CustomTkinter/Tk, pytest, Ruff, basedpyright, GitHub Actions.

## Global Constraints

- Source maps under `/Users/zhongerbing/Desktop/Maps` are read-only; never execute map scripts, historical EXEs, DLLs, or payloads.
- Do not modify `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2` during development or acceptance.
- Preserve unrelated user changes and stage only reviewed paths.
- Do not add runtime dependencies.
- Legacy state/ownership is not reusable under the new schema and is never deleted merely for being legacy.
- Root reports remain compatibility mirrors; `.w3xray-global/current.json` is the only resume authority.
- New and substantively changed Python modules must remain below 250 pure lines.
- Every behavior change follows RED → GREEN → REFACTOR and every focused gate must pass before starting the next task.

---

## File Structure

### New batch modules

- `w3xtool/durable_io.py` — file/directory synchronization primitives and typed durability errors.
- `w3xtool/batch_manifest_models.py` — immutable manifest, artifact, ownership, and validation records.
- `w3xtool/batch_manifest_io.py` — deterministic manifest/marker formatting and strict parsing.
- `w3xtool/batch_manifest_validation.py` — bounded hashing, file-set verification, and report/count reconciliation.
- `w3xtool/batch_publication_recovery.py` — strict per-map transaction records and idempotent recovery.
- `w3xtool/batch_global_publication.py` — global generation staging, manifest, current pointer, and compatibility mirrors.
- `w3xtool/batch_dependencies.py` — bounded client/cache/options dependency fingerprint.
- `w3xtool/batch_resume.py` — prior-state loading, reusable-result validation, and checkpoint-tail merge.
- `w3xtool/batch_execution.py` — spawn child protocol, cancellation, timeout, termination, and resource-limit outcomes.
- `w3xtool/batch_runtime.py` — disk preflight, RSS sampling, progress, ETA, and structured diagnostics.

### New GUI modules

- `w3xtool/gui_worker_registry.py` — tickets, group generations, cancellation, guarded callbacks, reaping, and bounded shutdown.
- `w3xtool/gui_worker_host.py` — static host Protocol for worker-aware mixins.

### New tests

- `tests/test_durable_io.py`
- `tests/test_batch_manifest.py`
- `tests/test_batch_publication_recovery.py`
- `tests/test_batch_global_publication.py`
- `tests/test_batch_dependencies.py`
- `tests/test_batch_resume.py`
- `tests/test_batch_execution.py`
- `tests/test_batch_runtime.py`
- `tests/test_gui_worker_registry.py`
- `tests/test_gui_object_filter_runner.py`
- `tests/test_batch_soak.py`

### Existing integration points

- Safe writes: `w3xtool/safe_output_chunk_writer.py`, `safe_output_publication.py`, `safe_output.py`.
- Per-map output: `w3xtool/batch_map_publication.py`, `batch_map_processing.py`.
- State/cache/global output: `w3xtool/batch_models.py`, `batch_state_io.py`, `batch_description_cache.py`, `description_cache.py`, `description_cache_models.py`.
- Orchestration/CLI: `w3xtool/batch_runner.py`, `batch_cli.py`.
- GUI: `w3xtool/gui.py`, `gui_lifecycle.py`, `gui_loader_runner.py`, `gui_loader_host.py`, `gui_object_filter_runner.py`, `gui_current_map.py`, `gui_source_browser.py`, `gui_external_data.py`, `gui_export_actions.py`, `gui_casc_browser.py`.
- Quality/acceptance: `pyproject.toml`, `uv.lock`, `w3xtool/quality_gate.py`, `w3xtool/acceptance_batch.py`, `w3xtool/acceptance_runner.py`, `.github/workflows/*.yml`, `tools/run_windows_acceptance.ps1`.

---

### Task 1: Durable staged-file publication

**Files:**
- Create: `w3xtool/durable_io.py`
- Create: `tests/test_durable_io.py`
- Modify: `w3xtool/safe_output_chunk_writer.py`
- Modify: `w3xtool/safe_output_publication.py`
- Modify: `w3xtool/safe_output.py`
- Modify: `tests/test_safe_output.py`

**Interfaces:**
- Produces: `sync_file_descriptor(descriptor: int) -> None`.
- Produces: `sync_directory_descriptor(descriptor: int) -> None` and `sync_directory(path: Path) -> None`; Windows unsupported-directory sync is an explicit no-op, while all other errors propagate.
- Changes: safe staged writes call file `fsync` before close and synchronize the parent after publication/rollback/cleanup.

- [x] **Step 1: Write failing file and directory synchronization tests**

```python
def test_chunk_writer_syncs_complete_stage_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(durable_io.os, "fsync", calls.append)
    descriptor = os.open(tmp_path / "stage", os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        assert write_chunks_to_descriptor(descriptor, (b"a", b"b")) == 2
    finally:
        os.close(descriptor)
    assert calls == [descriptor]


def test_existing_destination_is_restored_when_directory_sync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "state.json"
    destination.write_bytes(b"old")
    monkeypatch.setattr(
        safe_output_publication,
        "sync_directory_descriptor",
        lambda _descriptor: (_ for _ in ()).throw(OSError(errno.EIO, "sync")),
    )
    result = write_bytes_safely(str(tmp_path), destination.name, b"new")
    assert result.status is SafeWriteStatus.FAILED
    assert destination.read_bytes() == b"old"
```

- [x] **Step 2: Run RED tests**

Run: `uv run python -m pytest -q tests/test_durable_io.py tests/test_safe_output.py -k 'sync or restore'`

Expected: FAIL because `durable_io` and synchronization calls do not exist.

- [x] **Step 3: Implement minimal durability primitives and rollback ordering**

```python
def sync_file_descriptor(descriptor: int) -> None:
    """Flush one completed regular file to its backing store."""
    os.fsync(descriptor)


def sync_directory_descriptor(descriptor: int) -> None:
    """Flush directory metadata where the host exposes directory fsync."""
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if os.name == "nt" and exc.errno in {errno.EBADF, errno.EINVAL}:
            return
        raise
```

Call `sync_file_descriptor` once after all chunks. For an existing destination, retain the hard-link backup until the replacement rename and parent sync both succeed; on sync failure restore the backup, sync again, and return `FAILED`. For a new destination, delete it on sync failure. Apply the equivalent path-based ordering to the Windows fallback.

- [x] **Step 4: Run focused and existing safe-output tests**

Run: `uv run python -m pytest -q tests/test_durable_io.py tests/test_safe_output.py`

Expected: PASS with zero leftover `.w3xray-stage-*` or `.w3xray-backup-*` files.

- [x] **Step 5: Run static gates and commit**

Run:

```bash
uv run --with ruff ruff check w3xtool/durable_io.py w3xtool/safe_output_chunk_writer.py w3xtool/safe_output_publication.py w3xtool/safe_output.py tests/test_durable_io.py tests/test_safe_output.py
uv run --with ruff ruff format --check w3xtool/durable_io.py w3xtool/safe_output_chunk_writer.py w3xtool/safe_output_publication.py w3xtool/safe_output.py tests/test_durable_io.py tests/test_safe_output.py
uv run --with basedpyright basedpyright --level error w3xtool/durable_io.py w3xtool/safe_output_chunk_writer.py w3xtool/safe_output_publication.py
```

Commit: `fix: make staged writes durable`

---

### Task 2: Immutable per-map manifest and ownership binding

**Files:**
- Create: `w3xtool/batch_manifest_models.py`
- Create: `w3xtool/batch_manifest_io.py`
- Create: `w3xtool/batch_manifest_validation.py`
- Create: `tests/test_batch_manifest.py`
- Modify: `w3xtool/batch_models.py`
- Modify: `w3xtool/batch_map_processing.py`
- Modify: `w3xtool/batch_map_publication.py`
- Modify: `tests/test_batch_map_processing.py`

**Interfaces:**
- Produces: `ArtifactKind`, `ManifestArtifact`, `MapContentManifest`, `OwnershipRecord`, `PublicationValidation`.
- Produces: `build_map_manifest(stage: Path, result: MapBatchResult) -> tuple[MapContentManifest, str]` where the string is deterministic JSON.
- Produces: `verify_map_publication(directory: Path, expected: MapBatchResult | None = None) -> PublicationValidation`.
- Extends `MapBatchResult` with `dependency_fingerprint`, `manifest_sha256`, `published_bytes`, and `peak_rss_bytes` defaulted for source compatibility.

- [x] **Step 1: Write failing manifest round-trip, tamper, path, and count tests**

```python
def test_manifest_round_trip_binds_every_regular_artifact(tmp_path: Path) -> None:
    (tmp_path / "对象完整描述.tsv").write_text(_TEXT_HEADER + "\n", encoding="utf-8")
    icon = tmp_path / "图标" / "PNG" / "匿名" / "x.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"\x89PNG\r\n\x1a\n")
    result = _result(dependency_fingerprint="b" * 64)
    manifest, text = build_map_manifest(tmp_path, result)
    parsed = parse_map_manifest(text)
    assert parsed == manifest
    assert {item.relative_path for item in parsed.artifacts} == {
        "对象完整描述.tsv",
        "图标/PNG/匿名/x.png",
    }


def test_publication_validation_rejects_same_size_tampering(tmp_path: Path) -> None:
    result = _publish_manifest_fixture(tmp_path)
    report = tmp_path / result.output_directory / "地图摘要.txt"
    report.write_bytes(b"X" * report.stat().st_size)
    validation = verify_map_publication(report.parent, result)
    assert not validation.valid
    assert validation.code == "artifact_hash_mismatch"
```

Also test duplicate normalized paths, invalid/lowercase SHA, symlink artifacts, unlisted files, malformed TSV widths, and reconciliation of icon/text/relation counts.

- [x] **Step 2: Run RED tests**

Run: `uv run python -m pytest -q tests/test_batch_manifest.py tests/test_batch_map_processing.py`

Expected: FAIL on missing manifest APIs and missing result fields.

- [x] **Step 3: Implement frozen models and deterministic strict I/O**

```python
class ArtifactKind(StrEnum):
    REPORT = "report"
    ICON_ORIGINAL = "icon_original"
    ICON_PNG = "icon_png"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ManifestArtifact:
    relative_path: str
    kind: ArtifactKind
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class OwnershipRecord:
    schema_version: int
    source_sha256: str
    manifest_sha256: str
    transaction_id: str
```

Walk stage files in stable normalized order, hash with 1 MiB chunks, and reject unsafe/duplicate paths. Format JSON with `ensure_ascii=False`, `sort_keys=True`, and a trailing newline. Parse every integer/string/list field explicitly and reject extra or missing keys.

- [x] **Step 4: Integrate manifest finalization into one-map processing**

Write all reports first, build/write `内容清单.json`, hash it, write the JSON ownership marker, synchronize the completed stage, publish, then return `replace(result, manifest_sha256=..., published_bytes=...)`. Do not include the manifest or marker in the artifact list.

- [x] **Step 5: Run focused tests and static gates**

Run:

```bash
uv run python -m pytest -q tests/test_batch_manifest.py tests/test_batch_map_processing.py tests/test_batch_reports.py
uv run --with ruff ruff check w3xtool/batch_manifest_models.py w3xtool/batch_manifest_io.py w3xtool/batch_manifest_validation.py w3xtool/batch_models.py w3xtool/batch_map_processing.py w3xtool/batch_map_publication.py tests/test_batch_manifest.py tests/test_batch_map_processing.py
uv run --with ruff ruff format --check w3xtool/batch_manifest_models.py w3xtool/batch_manifest_io.py w3xtool/batch_manifest_validation.py w3xtool/batch_models.py w3xtool/batch_map_processing.py w3xtool/batch_map_publication.py tests/test_batch_manifest.py tests/test_batch_map_processing.py
uv run --with basedpyright basedpyright --level error w3xtool/batch_manifest_models.py w3xtool/batch_manifest_io.py w3xtool/batch_manifest_validation.py
```

Commit: `feat: bind map output to content manifests`

---

### Task 3: Recoverable per-map directory transactions

**Files:**
- Create: `w3xtool/batch_publication_recovery.py`
- Create: `tests/test_batch_publication_recovery.py`
- Modify: `w3xtool/batch_map_publication.py`
- Modify: `w3xtool/batch_map_processing.py`

**Interfaces:**
- Produces: `MapPublicationStage(stage: Path, transaction_id: str, relative: str, digest: str)`.
- Changes: `create_map_stage(output_root, relative, digest) -> MapPublicationStage`.
- Changes: `publish_map_stage(publication, output_root, manifest_sha256) -> Path`.
- Produces: `recover_map_publications(output_root: str) -> tuple[RecoveryDiagnostic, ...]`.

- [x] **Step 1: Write failing transition and recovery tests**

```python
@pytest.mark.parametrize("failure_phase", ("backup", "destination", "sync", "cleanup"))
def test_recovery_keeps_exactly_one_valid_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    old = _publish_valid_generation(tmp_path, payload=b"old")
    publication = _prepare_valid_stage(tmp_path, payload=b"new")
    _inject_publication_failure(monkeypatch, failure_phase)
    with pytest.raises(OSError):
        publish_map_stage(publication, str(tmp_path), publication.manifest_sha256)
    diagnostics = recover_map_publications(str(tmp_path))
    destination = tmp_path / publication.relative
    assert verify_map_publication(destination).valid
    assert destination in {old, tmp_path / publication.relative}
    assert not tuple((tmp_path / "地图").glob(".w3xray-map-*-*"))
    assert all(item.code != "unproved_path" for item in diagnostics)
```

Add an idempotence test, a test that leaves an unowned similarly named directory untouched, and a test that a prepared stage completes when the destination is absent.

- [x] **Step 2: Run RED tests**

Run: `uv run python -m pytest -q tests/test_batch_publication_recovery.py`

Expected: FAIL because transaction stages and recovery do not exist.

- [x] **Step 3: Implement strict transaction records and durable phases**

```python
class PublicationPhase(StrEnum):
    BUILDING = "building"
    PREPARED = "prepared"
    BACKUP_READY = "backup_ready"
    DESTINATION_READY = "destination_ready"
    COMMITTED = "committed"


@dataclass(frozen=True, slots=True)
class PublicationTransaction:
    transaction_id: str
    phase: PublicationPhase
    stage_name: str
    destination_name: str
    backup_name: str
    source_sha256: str
    manifest_sha256: str
```

Persist every phase with the safe durable writer. Derive all private names from the transaction ID; parse them with exact regexes; require immediate children of `地图/`. Recovery uses `verify_map_publication` before choosing stage/destination/backup and never deletes an unproven path.

- [x] **Step 4: Integrate startup recovery and stage cleanup**

Call recovery after root validation and before previous-state loading. `discard_map_stage` removes a building stage only when its transaction record matches; otherwise it returns a diagnostic and leaves the path.

- [x] **Step 5: Verify and commit**

Run:

```bash
uv run python -m pytest -q tests/test_batch_publication_recovery.py tests/test_batch_map_processing.py tests/test_batch_runner.py
uv run --with ruff ruff check w3xtool/batch_publication_recovery.py w3xtool/batch_map_publication.py w3xtool/batch_map_processing.py tests/test_batch_publication_recovery.py
uv run --with ruff ruff format --check w3xtool/batch_publication_recovery.py w3xtool/batch_map_publication.py w3xtool/batch_map_processing.py tests/test_batch_publication_recovery.py
uv run --with basedpyright basedpyright --level error w3xtool/batch_publication_recovery.py w3xtool/batch_map_publication.py
```

Commit: `feat: recover interrupted map publications`

---

### Task 4: Strict global generations, state validation, cache binding, and dependencies

**Files:**
- Create: `w3xtool/batch_global_publication.py`
- Create: `w3xtool/batch_dependencies.py`
- Create: `tests/test_batch_global_publication.py`
- Create: `tests/test_batch_dependencies.py`
- Modify: `w3xtool/batch_models.py`
- Modify: `w3xtool/batch_state_io.py`
- Modify: `w3xtool/batch_description_cache.py`
- Modify: `w3xtool/description_cache.py`
- Modify: `w3xtool/description_cache_models.py`
- Modify: `tests/test_batch_state_reports.py`
- Modify: `tests/test_description_cache.py`
- Modify: `tests/test_batch_description_cache.py`

**Interfaces:**
- Sets `BATCH_SCHEMA_VERSION = 3` and adds `MapBatchState.CANCELLED = "已取消"`.
- Produces: `publish_global_generation(output_root, state, cache_text, diagnostics_text) -> GlobalGeneration`.
- Produces: `load_current_generation(output_root) -> GlobalGeneration | None` and `load_current_batch_state(output_root) -> BatchState | None`.
- Produces: `fingerprint_dependencies(source, options, cache_sha256) -> str`.
- Extends `DescriptionCacheEntry` with `source_manifest_sha256`.

- [x] **Step 1: Write failing state-semantic and generation-atomicity tests**

```python
@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload["results"][0]["source"].update(sha256="xyz"),
        lambda payload: payload["results"][0].update(object_count=-1),
        lambda payload: payload["results"].append(payload["results"][0]),
        lambda payload: payload["results"][0].update(output_directory="../escape"),
    ),
)
def test_state_parser_rejects_semantically_invalid_results(mutation) -> None:
    payload = json.loads(format_batch_state_json(BatchState(3, (_result(),))))
    mutation(payload)
    with pytest.raises(BatchStateFormatError):
        parse_batch_state_json(json.dumps(payload))


def test_current_pointer_never_selects_partial_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = publish_global_generation(tmp_path, _state("a"), _cache(), _events())
    monkeypatch.setattr(
        batch_global_publication,
        "_publish_pointer",
        lambda *_args: (_ for _ in ()).throw(OSError("pointer")),
    )
    with pytest.raises(OSError):
        publish_global_generation(tmp_path, _state("b"), _cache(), _events())
    assert load_current_generation(tmp_path).generation_id == first.generation_id
```

Add report-hash tamper, pointer traversal, duplicate count label, impossible state/stage, and compatibility-mirror failure tests.

- [x] **Step 2: Write failing cache-manifest binding tests**

Publish a valid map manifest fixture, prove its client-fill row enters the cache with `source_manifest_sha256`, mutate the report, and prove a rebuild ignores it with `manifest_validation_failed`. Prove an automatic seed is accepted only through a validated global generation.

- [x] **Step 3: Run RED tests**

Run: `uv run python -m pytest -q tests/test_batch_global_publication.py tests/test_batch_dependencies.py tests/test_batch_state_reports.py tests/test_description_cache.py tests/test_batch_description_cache.py`

Expected: FAIL on schema 3, generation, dependency, and manifest-bound cache APIs.

- [x] **Step 4: Implement global generation commit and strict state parsing**

Stage all five global payloads, write a deterministic `全局清单.json`, sync the directory tree, atomically rename it into `generations/`, validate it, and atomically update `current.json`. Only then mirror root reports. Parse state with exact key sets and validate every invariant before returning `BatchState`.

- [x] **Step 5: Implement bounded dependency fingerprint**

```python
@dataclass(frozen=True, slots=True)
class DependencyEvidence:
    kind: str
    identity: tuple[tuple[str, int, int, str], ...]


def fingerprint_dependencies(
    source: SourceFingerprint,
    options: BatchOptionsView,
    cache_sha256: str,
) -> str:
    payload = format_dependency_json(
        BATCH_SCHEMA_VERSION,
        __version__,
        source.sha256,
        normalized_option_items(options),
        game_data_evidence(options.game_data_path),
        cache_sha256,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
```

For classic MPQs use normalized name/size/mtime; for CASC hash `.build.info` and record data/index stats; for trusted icon cache hash marker/manifests; for extracted directories record sorted relative path/size/mtime without following symlinks.

- [x] **Step 6: Verify and commit**

Run:

```bash
uv run python -m pytest -q tests/test_batch_global_publication.py tests/test_batch_dependencies.py tests/test_batch_state_reports.py tests/test_description_cache.py tests/test_batch_description_cache.py
uv run --with ruff ruff check w3xtool/batch_global_publication.py w3xtool/batch_dependencies.py w3xtool/batch_models.py w3xtool/batch_state_io.py w3xtool/batch_description_cache.py w3xtool/description_cache.py w3xtool/description_cache_models.py tests/test_batch_global_publication.py tests/test_batch_dependencies.py tests/test_batch_state_reports.py tests/test_description_cache.py tests/test_batch_description_cache.py
uv run --with ruff ruff format --check w3xtool/batch_global_publication.py w3xtool/batch_dependencies.py w3xtool/batch_models.py w3xtool/batch_state_io.py w3xtool/batch_description_cache.py w3xtool/description_cache.py w3xtool/description_cache_models.py tests/test_batch_global_publication.py tests/test_batch_dependencies.py tests/test_batch_state_reports.py tests/test_description_cache.py tests/test_batch_description_cache.py
uv run --with basedpyright basedpyright --level error w3xtool/batch_global_publication.py w3xtool/batch_dependencies.py w3xtool/batch_models.py w3xtool/batch_state_io.py
```

Commit: `feat: publish validated global generations`

---

### Task 5: Manifest-verified reuse and lossless checkpoints

**Files:**
- Create: `w3xtool/batch_resume.py`
- Create: `tests/test_batch_resume.py`
- Modify: `w3xtool/batch_runner.py`
- Modify: `tests/test_batch_runner.py`

**Interfaces:**
- Produces: `load_previous_state(output_root) -> PreviousBatchState` with diagnostics rather than silent corruption.
- Produces: `find_reusable_result(previous, fingerprint, dependency_fingerprint, output_root, retry_failed) -> ReuseDecision`.
- Produces: `checkpoint_state(current_results, previous, remaining_paths) -> BatchState`.

- [x] **Step 1: Write failing reusable-partial and checkpoint-tail tests**

```python
@pytest.mark.parametrize("state", (MapBatchState.COMPLETE, MapBatchState.PARTIAL, MapBatchState.RESTRICTED))
def test_unchanged_manifest_verified_publication_is_reused(
    tmp_path: Path, state: MapBatchState
) -> None:
    result = _publish_valid_result(tmp_path, state=state, dependency="d" * 64)
    decision = find_reusable_result(
        PreviousBatchState(BatchState(3, (result,)), ()),
        result.source,
        "d" * 64,
        str(tmp_path),
        retry_failed=True,
    )
    assert decision.result == result
    assert decision.code == "reused_verified_publication"


def test_checkpoint_preserves_unvisited_previous_results() -> None:
    previous = PreviousBatchState(BatchState(3, (_result("a"), _result("b"), _result("c"))), ())
    checkpoint = checkpoint_state((_result("a", state=MapBatchState.FAILED),), previous, ("b", "c"))
    assert [Path(item.source.path).name for item in checkpoint.results] == ["a", "b", "c"]
```

Add tests for dependency changes, hash tampering, missing files, invalid global pointer/state, `--no-retry-failed`, deleted sources, and duplicate previous paths.

- [x] **Step 2: Run RED tests**

Run: `uv run python -m pytest -q tests/test_batch_resume.py tests/test_batch_runner.py`

Expected: FAIL because reusable partials and tail merge are absent.

- [x] **Step 3: Implement resume module and shrink `batch_runner.py`**

Move previous-state loading, publication validation, and reuse selection out of `batch_runner.py`. Materialize the stable source path tuple once. At each checkpoint merge processed results with prior entries whose normalized paths are still unvisited. Publish through `publish_global_generation` only.

- [x] **Step 4: Run focused regression and static gates**

Run:

```bash
uv run python -m pytest -q tests/test_batch_resume.py tests/test_batch_runner.py tests/test_batch_e2e.py
uv run --with ruff ruff check w3xtool/batch_resume.py w3xtool/batch_runner.py tests/test_batch_resume.py tests/test_batch_runner.py
uv run --with ruff ruff format --check w3xtool/batch_resume.py w3xtool/batch_runner.py tests/test_batch_resume.py tests/test_batch_runner.py
uv run --with basedpyright basedpyright --level error w3xtool/batch_resume.py w3xtool/batch_runner.py
```

Commit: `feat: resume verified partial map results`

---

### Task 6: Isolated map execution, cancellation, resource preflight, and diagnostics

**Files:**
- Create: `w3xtool/batch_execution.py`
- Create: `w3xtool/batch_runtime.py`
- Create: `tests/test_batch_execution.py`
- Create: `tests/test_batch_runtime.py`
- Modify: `w3xtool/batch_models.py`
- Modify: `w3xtool/batch_runner.py`
- Modify: `w3xtool/batch_cli.py`
- Modify: `tests/test_batch_cli.py`
- Modify: `tests/test_batch_runner.py`

**Interfaces:**
- Adds `BatchOptions.map_timeout_seconds`, `max_memory_bytes`, and `minimum_free_bytes`.
- Produces: `execute_map_isolated(...) -> MapExecutionOutcome`.
- Produces: `BatchProgress` and `BatchDiagnostic` frozen models.
- Changes: `run_batch(options, *, cancellation=None, on_progress=None) -> BatchState`.

- [x] **Step 1: Write failing timeout, cancellation, child-crash, OOM, and reap tests**

```python
def test_timeout_terminates_and_reaps_child(tmp_path: Path) -> None:
    outcome = execute_test_worker(
        _blocking_worker,
        timeout_seconds=0.05,
        cancellation=None,
    )
    assert isinstance(outcome, MapExecutionFailure)
    assert outcome.code == "map_timeout"
    assert outcome.child_alive is False


def test_cancellation_returns_explicit_cancelled_outcome() -> None:
    signal = threading.Event()
    timer = threading.Timer(0.02, signal.set)
    timer.start()
    try:
        outcome = execute_test_worker(_blocking_worker, timeout_seconds=2, cancellation=signal)
    finally:
        timer.cancel()
    assert isinstance(outcome, MapExecutionCancelled)
```

Use module-level spawn-picklable test workers. Add a hard `os._exit(7)` child, a `MemoryError` child, a success child, and assert every process and queue is closed/reaped.

- [x] **Step 2: Write failing disk/progress/ETA/JSONL tests**

Patch `shutil.disk_usage` below the reserve and prove processing is not called. Feed deterministic monotonic times into progress calculation and assert bounded nonnegative ETA. Parse every emitted JSONL line and assert required fields.

- [x] **Step 3: Run RED tests**

Run: `uv run python -m pytest -q tests/test_batch_execution.py tests/test_batch_runtime.py tests/test_batch_cli.py tests/test_batch_runner.py`

Expected: FAIL on missing execution/runtime APIs and CLI options.

- [x] **Step 4: Implement spawn child protocol and resource limits**

```python
class CancellationSignal(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class MapExecutionFailure:
    code: str
    detail: str
    child_alive: bool = False


def execute_map_isolated(..., timeout_seconds: float, cancellation: CancellationSignal | None) -> MapExecutionOutcome:
    process = multiprocessing.get_context("spawn").Process(target=_child_entry, args=(...))
    process.start()
    try:
        return _wait_for_child(process, receiver, deadline, cancellation)
    finally:
        _terminate_and_reap_if_needed(process)
        receiver.close()
```

Set `RLIMIT_AS` only when configured and supported. Poll the pipe with a bounded interval. Never continue in the parent after catching child `MemoryError`.

- [x] **Step 5: Integrate disk preflight, graceful SIGINT, progress, and diagnostics**

The first SIGINT sets an event; the second raises `KeyboardInterrupt`. Convert cancellation into a `MapBatchState.CANCELLED` result, checkpoint it, and stop. CLI defaults to a positive timeout and prints `完成/总数`, action, elapsed, RSS, and ETA. Direct tests explicitly set timeout to `None` when monkeypatching in-process processing.

- [x] **Step 6: Verify and commit**

Run:

```bash
uv run python -m pytest -q tests/test_batch_execution.py tests/test_batch_runtime.py tests/test_batch_cli.py tests/test_batch_runner.py tests/test_batch_e2e.py
uv run --with ruff ruff check w3xtool/batch_execution.py w3xtool/batch_runtime.py w3xtool/batch_runner.py w3xtool/batch_cli.py tests/test_batch_execution.py tests/test_batch_runtime.py tests/test_batch_cli.py tests/test_batch_runner.py
uv run --with ruff ruff format --check w3xtool/batch_execution.py w3xtool/batch_runtime.py w3xtool/batch_runner.py w3xtool/batch_cli.py tests/test_batch_execution.py tests/test_batch_runtime.py tests/test_batch_cli.py tests/test_batch_runner.py
uv run --with basedpyright basedpyright --level error w3xtool/batch_execution.py w3xtool/batch_runtime.py w3xtool/batch_runner.py w3xtool/batch_cli.py
```

Commit: `feat: bound and observe batch map workers`

---

### Task 7: Unified bounded GUI worker lifecycle

**Files:**
- Create: `w3xtool/gui_worker_registry.py`
- Create: `w3xtool/gui_worker_host.py`
- Create: `tests/test_gui_worker_registry.py`
- Create: `tests/test_gui_object_filter_runner.py`
- Modify: `w3xtool/gui.py`
- Modify: `w3xtool/gui_lifecycle.py`
- Modify: `w3xtool/gui_loader_runner.py`
- Modify: `w3xtool/gui_loader_host.py`
- Modify: `w3xtool/gui_object_filter_runner.py`
- Modify: `w3xtool/gui_current_map.py`
- Modify: `w3xtool/gui_source_browser.py`
- Modify: `w3xtool/gui_external_data.py`
- Modify: `w3xtool/gui_export_actions.py`
- Modify: `w3xtool/gui_casc_browser.py`
- Modify: related GUI tests.

**Interfaces:**
- Produces: `GuiWorkerRegistry.start(group, target, *, replace) -> GuiWorkerTicket`.
- Produces: `cancel_group`, `accepts`, `finish`, and `shutdown(timeout_seconds) -> tuple[str, ...]`.
- Produces host helpers `_start_gui_worker(...)` and `_post_gui_worker(...)`.

- [x] **Step 1: Write failing registry lifecycle tests**

```python
def test_shutdown_is_bounded_when_worker_ignores_cancellation() -> None:
    registry = GuiWorkerRegistry(thread_factory=threading.Thread)
    release = threading.Event()
    registry.start("loader", lambda _ticket: release.wait(2), replace=False)
    started = time.monotonic()
    lingering = registry.shutdown(timeout_seconds=0.05)
    elapsed = time.monotonic() - started
    release.set()
    assert elapsed < 0.25
    assert lingering == ("loader",)


def test_replaced_ticket_cannot_deliver_callback() -> None:
    registry = GuiWorkerRegistry()
    first = registry.reserve("filter", replace=True)
    second = registry.reserve("filter", replace=True)
    assert not registry.accepts(first)
    assert registry.accepts(second)
```

Add cleanup-on-late-result, shared-deadline, idempotent shutdown, and worker-finish race tests.

- [x] **Step 2: Run RED registry tests**

Run: `uv run python -m pytest -q tests/test_gui_worker_registry.py`

Expected: FAIL because registry APIs do not exist.

- [x] **Step 3: Implement registry under 200 pure lines**

```python
@dataclass(frozen=True, slots=True)
class GuiWorkerTicket:
    worker_id: int
    group: str
    generation: int
    cancellation: threading.Event


class GuiWorkerRegistry:  # noqa: MUTABLE_OK - lifecycle registry owns changing workers.
    def shutdown(self, timeout_seconds: float) -> tuple[str, ...]:
        deadline = monotonic() + max(0.0, timeout_seconds)
        # Signal all tickets, then join each only for the shared remaining budget.
```

Guard callbacks before adding them to a lock-protected host queue and again when the Tk-main-thread 20-millisecond poll delivers them. Background workers never call Tk. Cleanup callbacks run when a ticket is stale or the registry stopped.

- [x] **Step 4: Migrate loader and filter first**

Write loader/filter RED tests that blocked jobs do not block shutdown, stale payloads are discarded, object-filter workers are reaped, and no late status callback runs. Remove loader-local worker maps and filter untracked threads only after tests fail for the expected old behavior.

- [x] **Step 5: Migrate current-map, source scan, external analysis, exports, and CASC open**

For each subsystem add one failing late-result test before replacing `threading.Thread(...).start()` with `_start_gui_worker`. Current-map snapshot cleanup and loader resolver cleanup remain the resource-specific cleanup callbacks.

- [x] **Step 6: Integrate bounded app shutdown**

Initialize the registry before all worker-producing mixins. In `_on_close`, invalidate subsystem polls, call `shutdown(timeout_seconds=1.5)`, log lingering daemon names, then destroy Tk. No subsystem calls an unbounded `join()`.

- [x] **Step 7: Verify and commit**

Run:

```bash
uv run python -m pytest -q tests/test_gui_worker_registry.py tests/test_gui_loader_runner.py tests/test_gui_object_filter_runner.py tests/test_gui_current_map_lifecycle.py tests/test_gui_export_safety.py tests/test_external_listfile_gui.py tests/test_gui_casc_browser.py
uv run --with ruff ruff check w3xtool/gui_worker_registry.py w3xtool/gui_worker_host.py w3xtool/gui.py w3xtool/gui_lifecycle.py w3xtool/gui_loader_runner.py w3xtool/gui_loader_host.py w3xtool/gui_object_filter_runner.py w3xtool/gui_current_map.py w3xtool/gui_source_browser.py w3xtool/gui_external_data.py w3xtool/gui_export_actions.py w3xtool/gui_casc_browser.py tests/test_gui_worker_registry.py tests/test_gui_loader_runner.py tests/test_gui_object_filter_runner.py
uv run --with ruff ruff format --check w3xtool/gui_worker_registry.py w3xtool/gui_worker_host.py w3xtool/gui.py w3xtool/gui_lifecycle.py w3xtool/gui_loader_runner.py w3xtool/gui_loader_host.py w3xtool/gui_object_filter_runner.py w3xtool/gui_current_map.py w3xtool/gui_source_browser.py w3xtool/gui_external_data.py w3xtool/gui_export_actions.py w3xtool/gui_casc_browser.py tests/test_gui_worker_registry.py tests/test_gui_loader_runner.py tests/test_gui_object_filter_runner.py
uv run --with basedpyright basedpyright --level error w3xtool/gui_worker_registry.py w3xtool/gui_worker_host.py w3xtool/gui_loader_runner.py w3xtool/gui_object_filter_runner.py
```

Commit: `fix: bound GUI background worker shutdown`

---

### Task 8: Quality gate, batch acceptance, and soak coverage

**Files:**
- Create: `w3xtool/quality_gate.py`
- Create: `w3xtool/acceptance_batch.py`
- Create: `tests/test_quality_gate.py`
- Create: `tests/test_batch_soak.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `w3xtool/acceptance_runner.py`
- Modify: `tests/test_acceptance_runner.py`
- Modify: `.github/workflows/posix-package.yml`
- Modify: `.github/workflows/windows-package.yml`
- Modify: `.github/workflows/windows-real-war3.yml`
- Modify: `tools/run_windows_acceptance.ps1`

**Interfaces:**
- Adds project script `w3xray-quality = "w3xtool.quality_gate:main"`.
- Produces one immutable strict path tuple and executes Ruff check, Ruff format check, and basedpyright with the current Python executable/environment.
- Adds acceptance check `batch_publication`.

- [x] **Step 1: Write failing quality command-construction tests**

```python
def test_quality_gate_builds_all_three_cross_platform_commands() -> None:
    commands = build_quality_commands(python_executable="python")
    assert [command.tool for command in commands] == [
        "ruff-check",
        "ruff-format",
        "basedpyright",
    ]
    assert all("w3xtool/batch_manifest_io.py" in command.argv for command in commands)
    assert all("shell=True" not in command.argv for command in commands)
```

- [x] **Step 2: Write failing packaged batch acceptance and soak tests**

Copy the real MPQ fixture to a private input directory, run the batch twice, require the second action to be `reused`, validate the current global generation and map manifest, assert no stage/backup/transaction leftovers, and compare the fixture SHA before/after. The soak test repeats five runs and uses `tracemalloc` plus worker/process enumeration to prove bounded growth and no leaked child processes.

- [x] **Step 3: Run RED tests**

Run: `uv run python -m pytest -q tests/test_quality_gate.py tests/test_batch_soak.py tests/test_acceptance_runner.py`

Expected: FAIL on missing quality and batch-acceptance modules/check.

- [x] **Step 4: Configure tools and implement the cross-platform quality entry point**

Add Ruff and basedpyright to the dev group. Configure Python 3.14, project excludes, formatter compatibility ignores, and test-specific ignores. Run subprocess argument tuples with `shell=False`, echo each command, stop on the first nonzero result, and return its exit code.

- [x] **Step 5: Add CI and acceptance gates**

Run `uv run w3xray-quality` immediately after `uv sync --dev` in POSIX, Windows packaging, and real-Windows scripts. Add `batch_publication` to source and packaged acceptance and require its manifest/resume/source-hash detail.

- [x] **Step 6: Run focused quality, acceptance, and soak verification**

Run:

```bash
uv sync --dev
uv run w3xray-quality
uv run python -m pytest -q tests/test_quality_gate.py tests/test_batch_soak.py tests/test_acceptance_runner.py tests/test_batch_e2e.py tests/test_windows_acceptance_assets.py
```

Expected: all commands exit 0; Windows/CASC checks may skip only on non-Windows hosts.

- [x] **Step 7: Commit**

Commit: `ci: gate resilient batch publication`

---

### Task 9: Documentation, full verification, and source-integrity handoff

**Files:**
- Modify: `AGENTS.md`
- Modify: `AGENTS.d/runtime.md`
- Modify: `AGENTS.d/testing.md`
- Modify: relevant design/plan checkboxes only when actually complete.

**Interfaces:**
- Documents schema 3, manifests, global pointer, partial reuse, timeout/cancellation, quality command, acceptance command, and migration behavior.

- [x] **Step 1: Update durable project knowledge**

Record exact commands, new output layout, recovery behavior, CLI defaults, and verified counts. Do not put conversation notes or machine secrets into AGENTS files.

- [x] **Step 2: Measure every changed Python file**

Run:

```bash
git diff --name-only HEAD~8..HEAD -- '*.py' | while IFS= read -r file; do
  printf '%s\t' "$file"
  awk '!/^[[:space:]]*$/ && !/^[[:space:]]*#/' "$file" | wc -l
done
```

Expected: every new/substantively changed file is at or below 250 pure lines; files in 200–250 warning band are explicitly reported.

- [x] **Step 3: Run full static and test gates fresh**

Run:

```bash
uv run w3xray-quality
uv run w3xray-test
git diff --check
```

Expected: quality exit 0; pytest has zero failures; diff check is empty.

- [x] **Step 4: Run local packaged/source acceptance where supported**

Run:

```bash
uv run main.py acceptance \
  --map tests/fixtures/maps/war3net-map-script-builder.w3x \
  --campaign tests/fixtures/reference/stormlib-campaign.w3n \
  --output /tmp/w3xray-ha-acceptance \
  --report /tmp/w3xray-ha-acceptance/acceptance.json \
  --repeat 5 --no-gui
```

Expected: `overall_status` is `pass`, including `batch_publication`.

- [x] **Step 5: Verify real source inventory remains unchanged**

When `/Users/zhongerbing/Desktop/Maps` is present, compute path/size/mtime/SHA-256 before and after read-only acceptance and compare exact manifests. Do not run the new batch against `map-extract-output-v2`; use a new temporary output root.

- [ ] **Step 6: Commit documentation and push the current branch**

```bash
git add -- AGENTS.md AGENTS.d/runtime.md AGENTS.d/testing.md docs/superpowers/specs/2026-07-15-batch-high-availability-design.md docs/superpowers/plans/2026-07-15-batch-high-availability.md
git diff --cached --check
git commit -m "docs: record resilient batch operations"
git push origin syx-local/complete-static-extraction
```

---

## Plan self-review

- Spec coverage: every manifest, publication, recovery, global transaction, resume, dependency, cancellation, timeout, disk, memory, GUI, CI, soak, and source-integrity requirement maps to a task.
- Type consistency: `MapBatchResult` gains hashes/bytes/RSS before manifest, state, resume, and runtime tasks consume them; global generation exists before resume uses it; registry exists before GUI migration.
- Scope: no map parser, item-relation, complete-description, or unrelated repository formatting is changed.
- Rollback boundaries: every task ends in an independently tested commit; authoritative pointers move only after complete validation.

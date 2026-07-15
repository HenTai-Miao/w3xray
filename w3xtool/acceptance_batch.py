"""Private-copy batch publication acceptance for source and packaged runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Final, assert_never, override

from .batch_configuration import BatchOptions
from .batch_global_publication import load_current_generation
from .batch_global_models import GlobalGeneration
from .batch_manifest_validation import verify_map_publication
from .batch_models import BatchState, MapBatchResult, MapBatchState
from .batch_reports import parse_batch_state_json
from .batch_runner import fingerprint_source, run_batch
from .batch_runtime import BatchAction, BatchProgress
from .bounded_file import read_bounded_regular_file
from .safe_output import safe_relative_path


_MAX_STATE_BYTES: Final = 512 * 1024 * 1024


class BatchAcceptanceError(RuntimeError):
    """One batch publication acceptance invariant failed."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class AuthoritativeBatch:
    """One validated pointer, compatibility mirror, and exact map directory set."""

    generation: GlobalGeneration
    publications: tuple[tuple[MapBatchResult, Path], ...]


def require_authoritative_batch(
    output_root: str | Path,
    expected_state: BatchState | None = None,
) -> AuthoritativeBatch:
    """Require exact agreement between pointer, mirrors, directories, and manifests."""
    output = Path(output_root)
    generation = load_current_generation(output)
    if generation is None:
        raise BatchAcceptanceError("current global generation is invalid")
    if expected_state is not None and generation.state != expected_state:
        raise BatchAcceptanceError("current global generation changed")
    try:
        payload, _identity = read_bounded_regular_file(
            output / "批量提取状态.json",
            _MAX_STATE_BYTES,
        )
        mirror = parse_batch_state_json(payload.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise BatchAcceptanceError("compatibility mirror is invalid") from exc
    if mirror != generation.state:
        raise BatchAcceptanceError(
            "compatibility mirror disagrees with current pointer"
        )
    maps_root = output / "地图"
    if output.is_symlink() or maps_root.is_symlink() or not maps_root.is_dir():
        raise BatchAcceptanceError("authoritative map root is unsafe")
    publications = _authoritative_publications(maps_root, generation.state)
    expected_names = {directory.name for _result, directory in publications}
    children = tuple(maps_root.iterdir())
    if (
        len(children) != len(expected_names)
        or {child.name for child in children} != expected_names
        or any(child.is_symlink() or not child.is_dir() for child in children)
    ):
        raise BatchAcceptanceError("authoritative map directory set is not exact")
    for result, directory in publications:
        validation = verify_map_publication(directory, result)
        if not validation.valid:
            raise BatchAcceptanceError(
                f"map publication validation failed: {validation.code}"
            )
    return AuthoritativeBatch(generation, publications)


def _authoritative_publications(
    maps_root: Path,
    state: BatchState,
) -> tuple[tuple[MapBatchResult, Path], ...]:
    publications: list[tuple[MapBatchResult, Path]] = []
    names: set[str] = set()
    for result in state.results:
        match result.state:
            case (
                MapBatchState.COMPLETE
                | MapBatchState.PARTIAL
                | MapBatchState.RESTRICTED
            ):
                pass
            case MapBatchState.FAILED | MapBatchState.CANCELLED:
                raise BatchAcceptanceError("authority contains an unpublished result")
            case unreachable:
                assert_never(unreachable)
        relative = safe_relative_path(result.output_directory)
        if relative is None or len(relative.parts) != 2 or relative.parts[0] != "地图":
            raise BatchAcceptanceError("authority contains an unsafe map directory")
        identity = relative.name.casefold()
        if identity in names:
            raise BatchAcceptanceError("authority contains duplicate map directories")
        names.add(identity)
        publications.append((result, maps_root / relative.name))
    return tuple(publications)


def check_batch_publication(map_path: Path, evidence_root: Path) -> str:
    """Publish a private map copy twice and verify durable reusable evidence."""
    original_before = fingerprint_source(str(map_path))
    source_root, output_root, source = _prepare_lane(map_path, evidence_root)
    private_before = fingerprint_source(str(source))
    if (
        private_before.size != original_before.size
        or private_before.sha256 != original_before.sha256
    ):
        raise BatchAcceptanceError("private fixture copy does not match its source")
    options = BatchOptions(
        str(source_root),
        str(output_root),
        map_timeout_seconds=120,
        minimum_free_bytes=0,
    )
    first_progress: list[BatchProgress] = []
    first = run_batch(options, on_progress=first_progress.append)
    first_result = _single_published_result(first.results)
    _require_action(first_progress, BatchAction.PROCESSED, "first")
    second_progress: list[BatchProgress] = []
    second = run_batch(options, on_progress=second_progress.append)
    second_result = _single_published_result(second.results)
    _require_action(second_progress, BatchAction.REUSED, "second")
    if second_result != first_result:
        raise BatchAcceptanceError("reused result changed persisted map evidence")
    authority = require_authoritative_batch(output_root, second)
    leftovers = _publication_leftovers(output_root)
    if leftovers:
        raise BatchAcceptanceError(f"private transaction leftovers: {leftovers[0]}")
    if fingerprint_source(str(source)) != private_before:
        raise BatchAcceptanceError("private source changed during batch acceptance")
    if fingerprint_source(str(map_path)) != original_before:
        raise BatchAcceptanceError("acceptance fixture changed during batch acceptance")
    return (
        f"source_sha256={original_before.sha256}; "
        f"manifest_sha256={second_result.manifest_sha256}; "
        f"generation={authority.generation.generation_id}; "
        f"state={second_result.state.value}; first=processed; second=reused; leftovers=0"
    )


def _prepare_lane(
    map_path: Path,
    evidence_root: Path,
) -> tuple[Path, Path, Path]:
    if map_path.is_symlink() or not map_path.is_file():
        raise BatchAcceptanceError(f"map fixture is not a regular file: {map_path}")
    if evidence_root.is_symlink():
        raise BatchAcceptanceError(f"evidence root is a symlink: {evidence_root}")
    evidence_root.mkdir(parents=True, exist_ok=True)
    lane = evidence_root / "batch-publication"
    if lane.is_symlink() or (lane.exists() and not lane.is_dir()):
        raise BatchAcceptanceError(f"batch evidence lane is unsafe: {lane}")
    if lane.exists():
        shutil.rmtree(lane)
    source_root = lane / "input"
    output_root = lane / "output"
    source_root.mkdir(parents=True)
    source = source_root / map_path.name
    shutil.copy2(map_path, source)
    return source_root, output_root, source


def _single_published_result(
    results: tuple[MapBatchResult, ...],
) -> MapBatchResult:
    if len(results) != 1:
        raise BatchAcceptanceError(f"batch result count is {len(results)}, expected 1")
    result = results[0]
    match result.state:
        case MapBatchState.COMPLETE | MapBatchState.PARTIAL | MapBatchState.RESTRICTED:
            if not result.output_directory:
                raise BatchAcceptanceError("successful batch result was not published")
            return result
        case MapBatchState.FAILED | MapBatchState.CANCELLED:
            raise BatchAcceptanceError(
                f"batch result is {result.state.value}: {result.first_error}"
            )
        case unreachable:
            assert_never(unreachable)


def _require_action(
    progress: list[BatchProgress],
    expected: BatchAction,
    run_name: str,
) -> None:
    actions = tuple(item.action for item in progress if item.completed > 0)
    if actions != (expected,):
        raise BatchAcceptanceError(f"{run_name} batch actions are {actions}")


def _publication_leftovers(output_root: Path) -> tuple[Path, ...]:
    prefixes = (
        ".w3xray-backup-",
        ".w3xray-global-stage-",
        ".w3xray-map-backup-",
        ".w3xray-map-stage-",
        ".w3xray-map-transaction-",
        ".w3xray-stage-",
    )
    return tuple(
        path
        for path in output_root.rglob("*")
        if any(path.name.startswith(prefix) for prefix in prefixes)
    )


__all__ = (
    "AuthoritativeBatch",
    "BatchAcceptanceError",
    "check_batch_publication",
    "require_authoritative_batch",
)

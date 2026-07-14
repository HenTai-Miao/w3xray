"""Sequential, resumable orchestration for map extraction batches."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Final, override

from .batch_models import (
    BatchState,
    BatchStateFormatError,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from .batch_reports import (
    format_batch_state_json,
    format_batch_summary_tsv,
    format_retry_tsv,
    parse_batch_state_json,
)
from .bounded_file import BoundedFileError, sha256_regular_file
from .load_context import MapLoadContext, build_map_load_context
from .map_directory import scan_map_sources
from .safe_output import safe_destination, write_text_safely
from .safe_output_models import SafeWriteStatus

DEFAULT_BATCH_OUTPUT: Final = (
    "/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output"
)
OWNERSHIP_MARKER: Final = ".w3xray-batch-owned"
REQUIRED_MAP_REPORTS: Final = (
    "地图摘要.txt",
    "图标索引.tsv",
    "对象描述.tsv",
    "图标完整性.txt",
    "描述完整性.txt",
)
_STATE_FILE: Final = "批量提取状态.json"


@dataclass(frozen=True, slots=True)
class BatchOptions:
    source_directory: str
    output_root: str = DEFAULT_BATCH_OUTPUT
    game_data_path: str | None = None
    retry_failed: bool = True


@dataclass(frozen=True, slots=True)
class BatchConfigurationError(ValueError):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class BatchOutputError(OSError):
    path: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"cannot publish {self.path}: {self.detail}"


def run_batch(options: BatchOptions) -> BatchState:
    """Process sources sequentially and persist progress after every map."""
    normalized = _normalized_options(options)
    _validate_roots(normalized)
    previous = _read_previous_state(normalized.output_root)
    context = build_map_load_context(game_data_path=normalized.game_data_path)
    results: list[MapBatchResult] = []
    for index, path in enumerate(
        scan_map_sources(normalized.source_directory), start=1
    ):
        try:
            fingerprint = fingerprint_source(path)
        except (OSError, ValueError) as exc:
            result = _failed_without_fingerprint(path, exc)
        else:
            reusable = _reusable_result(
                previous,
                fingerprint,
                normalized.output_root,
                retry_failed=normalized.retry_failed,
            )
            if reusable is not None:
                result = reusable
            else:
                try:
                    result = process_one_map(index, fingerprint, normalized, context)
                except (OSError, ValueError, KeyError, IndexError, struct.error) as exc:
                    result = _failed_result(fingerprint, exc)
        results.append(result)
        _publish_global_reports(normalized.output_root, BatchState(1, tuple(results)))
    state = BatchState(1, tuple(results))
    if not results:
        _publish_global_reports(normalized.output_root, state)
    return state


def process_one_map(
    index: int,
    fingerprint: SourceFingerprint,
    options: BatchOptions,
    context: MapLoadContext,
) -> MapBatchResult:
    """Load the focused single-map processor without coupling scan tests to it."""
    from .batch_map_processing import process_one_map as process

    return process(index, fingerprint, options, context)


def fingerprint_source(path: str) -> SourceFingerprint:
    """Hash one stable regular source and capture its resume identity."""
    source = Path(path)
    before = source.stat(follow_symlinks=False)
    digest, identity = sha256_regular_file(source)
    after = source.stat(follow_symlinks=False)
    if (after.st_dev, after.st_ino, after.st_size) != (
        identity.device,
        identity.inode,
        identity.size,
    ) or before.st_mtime_ns != after.st_mtime_ns:
        raise BoundedFileError(source, "file identity changed while hashing")
    return SourceFingerprint(str(source), identity.size, after.st_mtime_ns, digest)


def _normalized_options(options: BatchOptions) -> BatchOptions:
    source = os.path.abspath(os.path.expanduser(options.source_directory))
    output = os.path.abspath(os.path.expanduser(options.output_root))
    game_data = options.game_data_path or _find_classic_root(source)
    return BatchOptions(source, output, game_data, options.retry_failed)


def _validate_roots(options: BatchOptions) -> None:
    if not os.path.isdir(options.source_directory):
        raise BatchConfigurationError("source directory does not exist")
    if os.path.islink(options.output_root):
        raise BatchConfigurationError("output root is a symlink")
    source = os.path.realpath(options.source_directory)
    output = os.path.realpath(options.output_root)
    try:
        common = os.path.commonpath((source, output))
    except ValueError as exc:
        raise BatchConfigurationError(
            "source and output roots cannot be compared"
        ) from exc
    if common in {source, output}:
        raise BatchConfigurationError("source and output roots overlap")


def _find_classic_root(source_directory: str) -> str | None:
    current = Path(source_directory)
    for _ in range(8):
        if (current / "war3.mpq").is_file():
            return str(current)
        if current.parent == current:
            return None
        current = current.parent
    return None


def _read_previous_state(output_root: str) -> BatchState | None:
    path = Path(output_root, _STATE_FILE)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return parse_batch_state_json(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, BatchStateFormatError:
        return None


def _reusable_result(
    previous: BatchState | None,
    fingerprint: SourceFingerprint,
    output_root: str,
    *,
    retry_failed: bool,
) -> MapBatchResult | None:
    if previous is None:
        return None
    for result in previous.results:
        if result.source != fingerprint:
            continue
        if result.state is MapBatchState.COMPLETE:
            if result.stage == "published" and _published_result_exists(
                output_root, result
            ):
                return result
            continue
        if result.state is MapBatchState.FAILED and not retry_failed:
            return result
    return None


def _published_result_exists(output_root: str, result: MapBatchResult) -> bool:
    directory = safe_destination(output_root, result.output_directory)
    if directory is None or os.path.islink(directory) or not os.path.isdir(directory):
        return False
    marker = Path(directory, OWNERSHIP_MARKER)
    try:
        if (
            marker.is_symlink()
            or marker.read_text(encoding="ascii") != result.source.sha256
        ):
            return False
    except OSError:
        return False
    return all(
        not Path(directory, name).is_symlink() and Path(directory, name).is_file()
        for name in REQUIRED_MAP_REPORTS
    )


def _failed_result(
    fingerprint: SourceFingerprint, exc: BaseException
) -> MapBatchResult:
    return MapBatchResult(
        source=fingerprint,
        display_name=Path(fingerprint.path).stem,
        output_directory="",
        stage="load/process",
        state=MapBatchState.FAILED,
        first_error=f"{type(exc).__name__}: {exc}".replace("\n", " "),
        object_count=0,
        description_counts=(),
        named_icon_count=0,
        anonymous_icon_count=0,
        original_written_count=0,
        png_written_count=0,
        icon_failure_count=0,
        restricted_block_count=0,
        elapsed_ms=0,
    )


def _failed_without_fingerprint(path: str, exc: BaseException) -> MapBatchResult:
    fingerprint = SourceFingerprint(path, 0, 0, "0" * 64)
    return _failed_result(fingerprint, exc)


def _publish_global_reports(output_root: str, state: BatchState) -> None:
    reports = (
        ("批量提取汇总.tsv", format_batch_summary_tsv(state)),
        (_STATE_FILE, format_batch_state_json(state)),
        ("失败与重试.tsv", format_retry_tsv(state)),
    )
    for name, text in reports:
        result = write_text_safely(output_root, name, text)
        if result.status is not SafeWriteStatus.WRITTEN:
            raise BatchOutputError(name, result.error or result.status.value)

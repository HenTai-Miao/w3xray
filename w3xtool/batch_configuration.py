"""Normalized options and root-safety checks for batch extraction."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Final, override


DEFAULT_BATCH_OUTPUT: Final = (
    "/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output"
)
DEFAULT_MAP_TIMEOUT_SECONDS: Final = 900.0
DEFAULT_MINIMUM_FREE_BYTES: Final = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BatchOptions:
    """Paths and retry policy that define one batch run."""

    source_directory: str
    output_root: str = DEFAULT_BATCH_OUTPUT
    game_data_path: str | None = None
    retry_failed: bool = True
    map_timeout_seconds: float | None = None
    max_memory_bytes: int | None = None
    minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES
    description_cache_path: str | None = None


@dataclass(frozen=True, slots=True)
class BatchConfigurationError(ValueError):
    """One batch path configuration is missing or unsafe."""

    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


class BatchOutputError(OSError):
    """One authoritative batch checkpoint could not be published."""

    __slots__ = ("detail", "path")

    detail: str
    path: str

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(detail)
        self.path = path
        self.detail = detail

    @override
    def __str__(self) -> str:
        return f"cannot publish {self.path}: {self.detail}"


def normalize_batch_options(options: BatchOptions) -> BatchOptions:
    """Expand user paths and discover an adjacent classic client root."""
    source = os.path.abspath(os.path.expanduser(options.source_directory))
    output = os.path.abspath(os.path.expanduser(options.output_root))
    game_data = options.game_data_path or _find_classic_root(source)
    description_cache = (
        None
        if options.description_cache_path is None
        else os.path.abspath(os.path.expanduser(options.description_cache_path))
    )
    return BatchOptions(
        source_directory=source,
        output_root=output,
        game_data_path=game_data,
        retry_failed=options.retry_failed,
        map_timeout_seconds=options.map_timeout_seconds,
        max_memory_bytes=options.max_memory_bytes,
        minimum_free_bytes=options.minimum_free_bytes,
        description_cache_path=description_cache,
    )


def validate_batch_roots(options: BatchOptions) -> None:
    """Reject missing, symlinked, or overlapping source/output roots."""
    if options.map_timeout_seconds is not None and options.map_timeout_seconds <= 0:
        raise BatchConfigurationError("map timeout must be positive")
    if options.max_memory_bytes is not None and options.max_memory_bytes <= 0:
        raise BatchConfigurationError("map memory limit must be positive")
    if options.minimum_free_bytes < 0:
        raise BatchConfigurationError("minimum free bytes must be nonnegative")
    if not os.path.isdir(options.source_directory):
        raise BatchConfigurationError("source directory does not exist")
    if os.path.islink(options.output_root):
        raise BatchConfigurationError("output root is a symlink")
    cache_path = options.description_cache_path
    if cache_path is not None:
        if os.path.islink(cache_path):
            raise BatchConfigurationError("description cache root is a symlink")
        if not os.path.isdir(cache_path):
            raise BatchConfigurationError("description cache root does not exist")
    source = os.path.realpath(options.source_directory)
    output = os.path.realpath(options.output_root)
    _reject_overlap(source, output, "source and output roots overlap")
    if cache_path is not None:
        cache = os.path.realpath(cache_path)
        _reject_overlap(
            source,
            cache,
            "description cache and source roots overlap",
        )
        _reject_overlap(
            output,
            cache,
            "description cache and output roots overlap",
        )


def _reject_overlap(first: str, second: str, detail: str) -> None:
    try:
        common = os.path.commonpath((first, second))
    except ValueError as exc:
        raise BatchConfigurationError("batch roots cannot be compared") from exc
    if common in {first, second}:
        raise BatchConfigurationError(detail)


def _find_classic_root(source_directory: str) -> str | None:
    current = Path(source_directory)
    for _ in range(8):
        if (current / "war3.mpq").is_file():
            return str(current)
        if current.parent == current:
            return None
        current = current.parent
    return None


__all__ = (
    "DEFAULT_BATCH_OUTPUT",
    "DEFAULT_MAP_TIMEOUT_SECONDS",
    "DEFAULT_MINIMUM_FREE_BYTES",
    "BatchConfigurationError",
    "BatchOptions",
    "BatchOutputError",
    "normalize_batch_options",
    "validate_batch_roots",
)

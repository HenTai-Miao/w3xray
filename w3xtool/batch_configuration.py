"""Normalized options and root-safety checks for batch extraction."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Final, override


DEFAULT_BATCH_OUTPUT: Final = (
    "/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output"
)


@dataclass(frozen=True, slots=True)
class BatchOptions:
    """Paths and retry policy that define one batch run."""

    source_directory: str
    output_root: str = DEFAULT_BATCH_OUTPUT
    game_data_path: str | None = None
    retry_failed: bool = True


@dataclass(frozen=True, slots=True)
class BatchConfigurationError(ValueError):
    """One batch path configuration is missing or unsafe."""

    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class BatchOutputError(OSError):
    """One authoritative batch checkpoint could not be published."""

    path: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"cannot publish {self.path}: {self.detail}"


def normalize_batch_options(options: BatchOptions) -> BatchOptions:
    """Expand user paths and discover an adjacent classic client root."""
    source = os.path.abspath(os.path.expanduser(options.source_directory))
    output = os.path.abspath(os.path.expanduser(options.output_root))
    game_data = options.game_data_path or _find_classic_root(source)
    return BatchOptions(source, output, game_data, options.retry_failed)


def validate_batch_roots(options: BatchOptions) -> None:
    """Reject missing, symlinked, or overlapping source/output roots."""
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


__all__ = (
    "DEFAULT_BATCH_OUTPUT",
    "BatchConfigurationError",
    "BatchOptions",
    "BatchOutputError",
    "normalize_batch_options",
    "validate_batch_roots",
)

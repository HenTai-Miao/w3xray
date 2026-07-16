"""Immutable outcomes from safe batch icon publication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .icon_evidence_models import IconResolutionLayer
from .icon_resources import IconObjectReference


class IconKind(StrEnum):
    NAMED = "具名"
    ANONYMOUS = "匿名"


class IconExportState(StrEnum):
    COMPLETE = "complete"
    ORIGINAL_FAILED = "original_failed"
    PNG_FAILED = "png_failed"
    UNSAFE_PATH = "unsafe_path"


@dataclass(frozen=True, slots=True)
class IconExportRecord:
    kind: IconKind
    requested_path: str
    resolved_path: str
    source_path: str
    block_index: int | None
    sha256: str
    original_relative_path: str
    png_relative_path: str
    original_written: bool
    png_written: bool
    state: IconExportState
    error: str
    objects: tuple[IconObjectReference, ...]
    resolution_layer: IconResolutionLayer | None = None

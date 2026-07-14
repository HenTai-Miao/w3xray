"""Safely publish original icon payloads and disposable PNG copies."""

from __future__ import annotations

import hashlib
import os
import struct
from io import BytesIO
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import assert_never

from PIL import Image

from .blp import decode_blp
from .icon_resources import (
    AnonymousIconResource,
    IconObjectReference,
    NamedIconResource,
)
from .safe_output import safe_destination, safe_relative_path, write_bytes_safely
from .safe_output_models import SafeWriteResult, SafeWriteStatus


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


@dataclass(frozen=True, slots=True)
class _PngResult:
    payload: bytes | None
    error: str = ""


def export_named_icon(root: str, resource: NamedIconResource) -> IconExportRecord:
    """Write one named original and then its PNG convenience copy."""
    if safe_relative_path(resource.normalized_path) is None:
        return _failed_record(
            IconKind.NAMED,
            resource,
            IconExportState.UNSAFE_PATH,
            "unsafe named icon path",
        )
    source_suffix = _path_suffix(resource.resolved_path)
    base = _without_leaf_suffix(resource.normalized_path)
    original = f"图标/原始/具名/{base}{source_suffix}"
    png = f"图标/PNG/具名/{base}.png"
    return _export(
        root=root,
        kind=IconKind.NAMED,
        requested_path=resource.requested_path,
        resolved_path=resource.resolved_path,
        source_path=resource.source_path,
        block_index=None,
        digest=resource.sha256,
        payload=resource.payload,
        original_path=original,
        png_path=png,
        objects=resource.objects,
    )


def export_anonymous_icon(
    root: str, resource: AnonymousIconResource
) -> IconExportRecord:
    """Write one anonymous BLP under its evidence-derived stable basename."""
    return _export(
        root=root,
        kind=IconKind.ANONYMOUS,
        requested_path="",
        resolved_path="",
        source_path=resource.source_path,
        block_index=resource.block_index,
        digest=resource.sha256,
        payload=resource.payload,
        original_path=f"图标/原始/匿名/{resource.basename}.blp",
        png_path=f"图标/PNG/匿名/{resource.basename}.png",
        objects=(),
    )


def _export(
    *,
    root: str,
    kind: IconKind,
    requested_path: str,
    resolved_path: str,
    source_path: str,
    block_index: int | None,
    digest: str,
    payload: bytes,
    original_path: str,
    png_path: str,
    objects: tuple[IconObjectReference, ...],
) -> IconExportRecord:
    original_path = _collision_path(root, original_path, payload)
    original = write_bytes_safely(root, original_path, payload)
    original_failure = _write_failure_state(original)
    if original_failure is not None:
        return IconExportRecord(
            kind,
            requested_path,
            resolved_path,
            source_path,
            block_index,
            digest,
            original_path,
            png_path,
            False,
            False,
            original_failure,
            original.error,
            objects,
        )
    converted = _png_bytes(payload)
    if converted.payload is None:
        return IconExportRecord(
            kind,
            requested_path,
            resolved_path,
            source_path,
            block_index,
            digest,
            original_path,
            png_path,
            True,
            False,
            IconExportState.PNG_FAILED,
            converted.error,
            objects,
        )
    png_path = _collision_path(root, png_path, converted.payload)
    png_result = write_bytes_safely(root, png_path, converted.payload)
    png_failure = _write_failure_state(png_result)
    return IconExportRecord(
        kind,
        requested_path,
        resolved_path,
        source_path,
        block_index,
        digest,
        original_path,
        png_path,
        True,
        png_failure is None,
        IconExportState.COMPLETE if png_failure is None else png_failure,
        png_result.error,
        objects,
    )


def _png_bytes(payload: bytes) -> _PngResult:
    try:
        image: Image.Image | None = decode_blp(payload)
    except (OSError, ValueError, struct.error) as exc:
        return _PngResult(None, f"{type(exc).__name__}: {exc}")
    if image is None:
        return _PngResult(None, "BLP decode failed")
    try:
        output = BytesIO()
        image.save(output, format="PNG")
        return _PngResult(output.getvalue())
    except (OSError, ValueError) as exc:
        return _PngResult(None, f"{type(exc).__name__}: {exc}")
    finally:
        image.close()


def _write_failure_state(result: SafeWriteResult) -> IconExportState | None:
    match result.status:
        case SafeWriteStatus.WRITTEN:
            return None
        case SafeWriteStatus.UNSAFE:
            return IconExportState.UNSAFE_PATH
        case SafeWriteStatus.FAILED:
            return IconExportState.ORIGINAL_FAILED
        case unreachable:
            assert_never(unreachable)


def _collision_path(root: str, name: str, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    destination = safe_destination(root, name)
    if destination is None or not os.path.isfile(destination):
        return name
    try:
        if os.path.getsize(destination) == len(payload):
            with open(destination, "rb") as handle:
                if hashlib.sha256(handle.read()).hexdigest() == digest:
                    return name
    except OSError:
        return name
    path = PurePosixPath(name.replace("\\", "/"))
    return str(path.with_name(f"{path.stem}_{digest[:8]}{path.suffix}"))


def _path_suffix(path: str) -> str:
    leaf = path.replace("\\", "/").rsplit("/", 1)[-1]
    return f".{leaf.rsplit('.', 1)[-1]}" if "." in leaf else ".blp"


def _without_leaf_suffix(path: str) -> str:
    normalized = path.replace("\\", "/")
    leaf = normalized.rsplit("/", 1)[-1]
    return normalized.rsplit(".", 1)[0] if "." in leaf else normalized


def _failed_record(
    kind: IconKind,
    resource: NamedIconResource,
    state: IconExportState,
    error: str,
) -> IconExportRecord:
    return IconExportRecord(
        kind=kind,
        requested_path=resource.requested_path,
        resolved_path=resource.resolved_path,
        source_path=resource.source_path,
        block_index=None,
        sha256=resource.sha256,
        original_relative_path="",
        png_relative_path="",
        original_written=False,
        png_written=False,
        state=state,
        error=error,
        objects=resource.objects,
    )

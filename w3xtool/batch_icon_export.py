"""Safely publish original icon payloads and disposable PNG copies."""

from __future__ import annotations

from typing import assert_never

from .batch_icon_models import IconExportRecord, IconExportState, IconKind
from .batch_icon_paths import collision_path, icon_path_suffix, without_leaf_suffix
from .batch_icon_png import convert_icon_to_png
from .icon_evidence_models import IconResolutionLayer, ResolvedIconEvidence
from .icon_resources import (
    AnonymousIconResource,
    IconObjectReference,
    NamedIconResource,
)
from .safe_output import safe_relative_path, write_bytes_safely
from .safe_output_models import SafeWriteResult, SafeWriteStatus


def export_named_icon(
    root: str,
    resource: NamedIconResource | ResolvedIconEvidence,
) -> IconExportRecord:
    """Write one named original and then its PNG convenience copy."""
    match resource:
        case NamedIconResource():
            normalized_path = resource.normalized_path
            requested_path = resource.requested_path
            digest = resource.sha256
            objects = resource.objects
            resolution_layer = None
        case ResolvedIconEvidence():
            normalized_path = resource.reference.normalized_path
            requested_path = resource.reference.requested_path
            digest = resource.content_sha256
            objects = (resource.reference,)
            resolution_layer = resource.layer
        case unreachable:
            assert_never(unreachable)
    if safe_relative_path(normalized_path) is None:
        return _failed_record(
            requested_path=requested_path,
            resolved_path=resource.resolved_path,
            source_path=resource.source_path,
            digest=digest,
            objects=objects,
            resolution_layer=resolution_layer,
            state=IconExportState.UNSAFE_PATH,
            error="unsafe named icon path",
        )
    source_suffix = icon_path_suffix(resource.resolved_path)
    base = without_leaf_suffix(normalized_path)
    original = f"图标/原始/具名/{base}{source_suffix}"
    png = f"图标/PNG/具名/{base}.png"
    return _export(
        root=root,
        kind=IconKind.NAMED,
        requested_path=requested_path,
        resolved_path=resource.resolved_path,
        source_path=resource.source_path,
        block_index=None,
        digest=digest,
        payload=resource.payload,
        original_path=original,
        png_path=png,
        objects=objects,
        resolution_layer=resolution_layer,
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
        resolution_layer=None,
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
    resolution_layer: IconResolutionLayer | None,
) -> IconExportRecord:
    original_path = collision_path(root, original_path, payload)
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
            resolution_layer,
        )
    converted = convert_icon_to_png(payload)
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
            resolution_layer,
        )
    png_path = collision_path(root, png_path, converted.payload)
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
        resolution_layer,
    )


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


def _failed_record(
    *,
    requested_path: str,
    resolved_path: str,
    source_path: str,
    digest: str,
    objects: tuple[IconObjectReference, ...],
    resolution_layer: IconResolutionLayer | None,
    state: IconExportState,
    error: str,
) -> IconExportRecord:
    return IconExportRecord(
        kind=IconKind.NAMED,
        requested_path=requested_path,
        resolved_path=resolved_path,
        source_path=source_path,
        block_index=None,
        sha256=digest,
        original_relative_path="",
        png_relative_path="",
        original_written=False,
        png_written=False,
        state=state,
        error=error,
        objects=objects,
        resolution_layer=resolution_layer,
    )

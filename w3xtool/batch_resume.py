"""Validated prior-state reuse and lossless checkpoint assembly."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import assert_never
from unicodedata import normalize

from .batch_global_models import GLOBAL_ROOT_NAME
from .batch_global_publication import load_current_generation
from .batch_manifest_validation import verify_map_publication
from .batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from .safe_output import safe_destination


@dataclass(frozen=True, slots=True)
class ResumeDiagnostic:
    """Stable reason emitted while loading or selecting prior evidence."""

    code: str
    detail: str = ""
    source_path: str = ""


@dataclass(frozen=True, slots=True)
class PreviousBatchState:
    """Validated authoritative state plus non-fatal loading diagnostics."""

    state: BatchState | None
    diagnostics: tuple[ResumeDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class ReuseDecision:
    """Either one reusable result or the exact reason for reprocessing."""

    result: MapBatchResult | None
    code: str
    detail: str = ""


def format_resume_diagnostics_jsonl(
    diagnostics: tuple[ResumeDiagnostic, ...],
) -> str:
    """Serialize stable resume evidence without normalizing diagnostic text."""
    return "".join(
        json.dumps(
            {
                "code": item.code,
                "detail": item.detail,
                "source_path": item.source_path,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for item in diagnostics
    )


def load_previous_state(output_root: str) -> PreviousBatchState:
    """Load state only through one fully validated global current pointer."""
    root = Path(output_root)
    generation = load_current_generation(root)
    if generation is not None:
        return PreviousBatchState(generation.state, ())
    global_root = root / GLOBAL_ROOT_NAME
    if global_root.exists() or global_root.is_symlink():
        return PreviousBatchState(
            None,
            (
                ResumeDiagnostic(
                    "invalid_global_generation",
                    str(global_root / "current.json"),
                ),
            ),
        )
    legacy_state = root / "批量提取状态.json"
    if legacy_state.exists() or legacy_state.is_symlink():
        return PreviousBatchState(
            None,
            (ResumeDiagnostic("legacy_state_ignored", str(legacy_state)),),
        )
    return PreviousBatchState(None, ())


def find_reusable_result(
    previous: PreviousBatchState,
    fingerprint: SourceFingerprint,
    dependency_fingerprint: str,
    output_root: str,
    *,
    retry_failed: bool,
) -> ReuseDecision:
    """Reuse one exact prior result only after publication validation."""
    state = previous.state
    if state is None:
        return ReuseDecision(None, "no_previous_state")
    matches = tuple(
        result
        for result in state.results
        if _path_key(result.source.path) == _path_key(fingerprint.path)
    )
    if not matches:
        return ReuseDecision(None, "previous_source_missing")
    if len(matches) != 1:
        return ReuseDecision(None, "ambiguous_previous_source")
    result = matches[0]
    if result.source != fingerprint:
        return ReuseDecision(None, "source_changed")
    match result.state:
        case MapBatchState.COMPLETE | MapBatchState.PARTIAL | MapBatchState.RESTRICTED:
            if result.dependency_fingerprint != dependency_fingerprint:
                return ReuseDecision(None, "dependency_changed")
            destination = safe_destination(output_root, result.output_directory)
            if destination is None:
                return ReuseDecision(None, "unsafe_output_directory")
            validation = verify_map_publication(Path(destination), result)
            if not validation.valid:
                return ReuseDecision(None, "publication_invalid", validation.code)
            return ReuseDecision(result, "reused_verified_publication")
        case MapBatchState.FAILED:
            if retry_failed:
                return ReuseDecision(None, "retry_failed_result")
            if result.dependency_fingerprint != dependency_fingerprint:
                return ReuseDecision(None, "dependency_changed")
            return ReuseDecision(result, "reused_failed_without_retry")
        case MapBatchState.CANCELLED:
            return ReuseDecision(None, "retry_cancelled_result")
        case unreachable:
            assert_never(unreachable)


def checkpoint_state(
    current_results: tuple[MapBatchResult, ...],
    previous: PreviousBatchState,
    remaining_paths: tuple[str, ...],
) -> BatchState:
    """Merge processed results with unvisited prior entries still in the scan."""
    previous_results = () if previous.state is None else previous.state.results
    grouped: dict[str, list[MapBatchResult]] = {}
    for result in previous_results:
        grouped.setdefault(_path_key(result.source.path), []).append(result)
    tail = tuple(
        grouped[key][0]
        for path in remaining_paths
        if len(grouped.get(key := _path_key(path), ())) == 1
    )
    return BatchState(BATCH_SCHEMA_VERSION, (*current_results, *tail))


def _path_key(path: str) -> str:
    expanded = os.path.abspath(os.path.expanduser(path))
    return normalize("NFC", os.path.normcase(expanded)).casefold()


__all__ = (
    "PreviousBatchState",
    "ResumeDiagnostic",
    "ReuseDecision",
    "checkpoint_state",
    "find_reusable_result",
    "format_resume_diagnostics_jsonl",
    "load_previous_state",
)

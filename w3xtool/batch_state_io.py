"""Deterministic JSON persistence for resumable batch state."""

from __future__ import annotations

import json
from typing import TypedDict

from .batch_models import (
    BatchState,
    MapBatchResult,
)
from .batch_state_parser import parse_state_json


class _SourceJson(TypedDict):
    path: str
    size: int
    mtime_ns: int
    sha256: str


class _ResultJson(TypedDict):
    source: _SourceJson
    display_name: str
    output_directory: str
    stage: str
    state: str
    first_error: str
    object_count: int
    description_counts: list[tuple[str, int]]
    named_icon_count: int
    anonymous_icon_count: int
    original_written_count: int
    png_written_count: int
    icon_failure_count: int
    restricted_block_count: int
    elapsed_ms: int
    relation_counts: list[tuple[str, int]]
    relation_incomplete_count: int
    dependency_fingerprint: str
    manifest_sha256: str
    published_bytes: int
    peak_rss_bytes: int
    valid_icon_reference_count: int
    resolved_icon_reference_count: int
    filtered_icon_field_count: int
    unresolved_icon_count: int
    unresolved_icon_reference_count: int
    anonymous_read_failure_count: int
    original_write_failure_count: int
    png_failure_count: int


class _StateJson(TypedDict):
    schema_version: int
    results: list[_ResultJson]


def format_batch_state_json(state: BatchState) -> str:
    """Serialize batch state with stable key and row ordering."""
    payload = _StateJson(
        schema_version=state.schema_version,
        results=[
            _result_json(result) for result in sorted(state.results, key=_result_key)
        ],
    )
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def parse_batch_state_json(text: str) -> BatchState:
    """Parse persisted state or raise a typed boundary error."""
    return parse_state_json(text)


def _result_json(result: MapBatchResult) -> _ResultJson:
    return _ResultJson(
        source=_SourceJson(
            path=result.source.path,
            size=result.source.size,
            mtime_ns=result.source.mtime_ns,
            sha256=result.source.sha256,
        ),
        display_name=result.display_name,
        output_directory=result.output_directory,
        stage=result.stage,
        state=result.state.value,
        first_error=result.first_error,
        object_count=result.object_count,
        description_counts=list(result.description_counts),
        named_icon_count=result.named_icon_count,
        anonymous_icon_count=result.anonymous_icon_count,
        original_written_count=result.original_written_count,
        png_written_count=result.png_written_count,
        icon_failure_count=result.icon_failure_count,
        restricted_block_count=result.restricted_block_count,
        elapsed_ms=result.elapsed_ms,
        relation_counts=list(result.relation_counts),
        relation_incomplete_count=result.relation_incomplete_count,
        dependency_fingerprint=result.dependency_fingerprint,
        manifest_sha256=result.manifest_sha256,
        published_bytes=result.published_bytes,
        peak_rss_bytes=result.peak_rss_bytes,
        valid_icon_reference_count=result.valid_icon_reference_count,
        resolved_icon_reference_count=result.resolved_icon_reference_count,
        filtered_icon_field_count=result.filtered_icon_field_count,
        unresolved_icon_count=result.unresolved_icon_count,
        unresolved_icon_reference_count=result.unresolved_icon_reference_count,
        anonymous_read_failure_count=result.anonymous_read_failure_count,
        original_write_failure_count=result.original_write_failure_count,
        png_failure_count=result.png_failure_count,
    )


def _result_key(result: MapBatchResult) -> tuple[str, str]:
    return result.source.path.casefold(), result.source.path

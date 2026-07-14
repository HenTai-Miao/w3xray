"""Deterministic JSON persistence for resumable batch state."""

from __future__ import annotations

import json
from typing import TypedDict

from .batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    BatchStateFormatError,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)


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
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BatchStateFormatError(f"invalid batch state JSON: {exc.msg}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != BATCH_SCHEMA_VERSION
    ):
        raise BatchStateFormatError("unsupported batch state schema")
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise BatchStateFormatError("batch state results must be a list")
    try:
        results = tuple(_parse_result(item) for item in raw_results)
    except (KeyError, TypeError, ValueError) as exc:
        raise BatchStateFormatError(f"invalid batch state result: {exc}") from exc
    return BatchState(schema_version=BATCH_SCHEMA_VERSION, results=results)


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
    )


def _parse_result(raw) -> MapBatchResult:
    source = raw["source"]
    counts = raw["description_counts"]
    return MapBatchResult(
        source=SourceFingerprint(
            path=str(source["path"]),
            size=int(source["size"]),
            mtime_ns=int(source["mtime_ns"]),
            sha256=str(source["sha256"]),
        ),
        display_name=str(raw["display_name"]),
        output_directory=str(raw["output_directory"]),
        stage=str(raw["stage"]),
        state=MapBatchState(str(raw["state"])),
        first_error=str(raw["first_error"]),
        object_count=int(raw["object_count"]),
        description_counts=tuple((str(item[0]), int(item[1])) for item in counts),
        named_icon_count=int(raw["named_icon_count"]),
        anonymous_icon_count=int(raw["anonymous_icon_count"]),
        original_written_count=int(raw["original_written_count"]),
        png_written_count=int(raw["png_written_count"]),
        icon_failure_count=int(raw["icon_failure_count"]),
        restricted_block_count=int(raw["restricted_block_count"]),
        elapsed_ms=int(raw["elapsed_ms"]),
        relation_counts=tuple(
            (str(item[0]), int(item[1])) for item in raw["relation_counts"]
        ),
        relation_incomplete_count=int(raw["relation_incomplete_count"]),
    )


def _result_key(result: MapBatchResult) -> tuple[str, str]:
    return result.source.path.casefold(), result.source.path

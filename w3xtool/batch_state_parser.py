"""Strict semantic parser for authoritative schema-3 batch state."""

from __future__ import annotations

import json
import re
from typing import Final, assert_never

from .batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    BatchStateFormatError,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from .safe_output import safe_relative_path


_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_STATE_KEYS: Final = frozenset(("schema_version", "results"))
_SOURCE_KEYS: Final = frozenset(("path", "size", "mtime_ns", "sha256"))
_RESULT_KEYS: Final = frozenset(
    (
        "source",
        "display_name",
        "output_directory",
        "stage",
        "state",
        "first_error",
        "object_count",
        "description_counts",
        "named_icon_count",
        "anonymous_icon_count",
        "original_written_count",
        "png_written_count",
        "icon_failure_count",
        "restricted_block_count",
        "elapsed_ms",
        "relation_counts",
        "relation_incomplete_count",
        "dependency_fingerprint",
        "manifest_sha256",
        "published_bytes",
        "peak_rss_bytes",
    )
)

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


def parse_state_json(text: str) -> BatchState:
    """Parse exact JSON types, keys, identities, counts, and state semantics."""
    try:
        value: JsonValue = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BatchStateFormatError(f"invalid batch state JSON: {exc.msg}") from exc
    root = _mapping(value, "batch state")
    _require_keys(root, _STATE_KEYS)
    if _integer(root["schema_version"], "schema version") != BATCH_SCHEMA_VERSION:
        raise BatchStateFormatError("unsupported batch state schema")
    raw_results = root["results"]
    if not isinstance(raw_results, list):
        raise BatchStateFormatError("batch state results must be a list")
    try:
        results = tuple(_parse_result(item) for item in raw_results)
    except ValueError as exc:
        if isinstance(exc, BatchStateFormatError):
            raise
        raise BatchStateFormatError(f"invalid batch state result: {exc}") from exc
    _require_unique_results(results)
    return BatchState(BATCH_SCHEMA_VERSION, results)


def _parse_result(value: JsonValue) -> MapBatchResult:
    raw = _mapping(value, "result")
    _require_keys(raw, _RESULT_KEYS)
    source = _parse_source(raw["source"])
    state = _state(raw["state"])
    result = MapBatchResult(
        source=source,
        display_name=_text(raw["display_name"], "display name"),
        output_directory=_text(raw["output_directory"], "output directory"),
        stage=_text(raw["stage"], "stage"),
        state=state,
        first_error=_text(raw["first_error"], "first error"),
        object_count=_nonnegative(raw["object_count"], "object count"),
        description_counts=_counts(raw["description_counts"], "description counts"),
        named_icon_count=_nonnegative(raw["named_icon_count"], "named icon count"),
        anonymous_icon_count=_nonnegative(
            raw["anonymous_icon_count"], "anonymous icon count"
        ),
        original_written_count=_nonnegative(
            raw["original_written_count"], "original written count"
        ),
        png_written_count=_nonnegative(raw["png_written_count"], "PNG written count"),
        icon_failure_count=_nonnegative(
            raw["icon_failure_count"], "icon failure count"
        ),
        restricted_block_count=_nonnegative(
            raw["restricted_block_count"], "restricted block count"
        ),
        elapsed_ms=_nonnegative(raw["elapsed_ms"], "elapsed milliseconds"),
        relation_counts=_counts(raw["relation_counts"], "relation counts"),
        relation_incomplete_count=_nonnegative(
            raw["relation_incomplete_count"], "relation incomplete count"
        ),
        dependency_fingerprint=_text(
            raw["dependency_fingerprint"], "dependency fingerprint"
        ),
        manifest_sha256=_text(raw["manifest_sha256"], "manifest SHA-256"),
        published_bytes=_nonnegative(raw["published_bytes"], "published bytes"),
        peak_rss_bytes=_nonnegative(raw["peak_rss_bytes"], "peak RSS bytes"),
    )
    _validate_result_state(result)
    return result


def _parse_source(value: JsonValue) -> SourceFingerprint:
    raw = _mapping(value, "source")
    _require_keys(raw, _SOURCE_KEYS)
    path = _text(raw["path"], "source path")
    if not path:
        raise BatchStateFormatError("source path is empty")
    return SourceFingerprint(
        path,
        _nonnegative(raw["size"], "source size"),
        _nonnegative(raw["mtime_ns"], "source mtime"),
        _digest(raw["sha256"], "source SHA-256"),
    )


def _validate_result_state(result: MapBatchResult) -> None:
    match result.state:
        case MapBatchState.COMPLETE | MapBatchState.PARTIAL | MapBatchState.RESTRICTED:
            relative = safe_relative_path(result.output_directory)
            if (
                result.stage != "published"
                or relative is None
                or len(relative.parts) != 2
                or relative.parts[0] != "地图"
            ):
                raise BatchStateFormatError("published state has an unsafe stage/path")
            _require_digest(result.dependency_fingerprint, "dependency fingerprint")
            _require_digest(result.manifest_sha256, "manifest SHA-256")
        case MapBatchState.FAILED | MapBatchState.CANCELLED:
            if (
                not result.stage
                or result.stage == "published"
                or result.output_directory
                or result.manifest_sha256
                or result.published_bytes
            ):
                raise BatchStateFormatError("failed/cancelled state contradicts stage")
            if result.dependency_fingerprint:
                _require_digest(
                    result.dependency_fingerprint,
                    "dependency fingerprint",
                )
        case unreachable:
            assert_never(unreachable)


def _require_unique_results(results: tuple[MapBatchResult, ...]) -> None:
    paths: set[str] = set()
    identities: set[tuple[str, int]] = set()
    outputs: set[str] = set()
    for result in results:
        path_key = result.source.path.casefold()
        identity = result.source.sha256, result.source.size
        if path_key in paths or identity in identities:
            raise BatchStateFormatError("duplicate source result")
        paths.add(path_key)
        identities.add(identity)
        if result.output_directory:
            output_key = result.output_directory.casefold()
            if output_key in outputs:
                raise BatchStateFormatError("duplicate output directory")
            outputs.add(output_key)


def _counts(value: JsonValue, label: str) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, list):
        raise BatchStateFormatError(f"{label} must be a list")
    result: list[tuple[str, int]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise BatchStateFormatError(f"invalid {label} row")
        name = _text(item[0], f"{label} label")
        if not name or name in seen:
            raise BatchStateFormatError(f"duplicate {label} label")
        seen.add(name)
        result.append((name, _nonnegative(item[1], f"{label} value")))
    return tuple(result)


def _mapping(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise BatchStateFormatError(f"{label} must be an object")
    return value


def _require_keys(value: dict[str, JsonValue], expected: frozenset[str]) -> None:
    if set(value) != expected:
        raise BatchStateFormatError("unexpected batch state keys")


def _text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise BatchStateFormatError(f"{label} must be text")
    return value


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BatchStateFormatError(f"{label} must be an integer")
    return value


def _nonnegative(value: JsonValue, label: str) -> int:
    number = _integer(value, label)
    if number < 0:
        raise BatchStateFormatError(f"{label} must be nonnegative")
    return number


def _digest(value: JsonValue, label: str) -> str:
    digest = _text(value, label)
    _require_digest(digest, label)
    return digest


def _require_digest(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise BatchStateFormatError(f"invalid {label}")


def _state(value: JsonValue) -> MapBatchState:
    try:
        return MapBatchState(_text(value, "map state"))
    except ValueError as exc:
        raise BatchStateFormatError("invalid map state") from exc

"""Strict bounded wire messages returned by isolated map children."""

from __future__ import annotations

from dataclasses import dataclass
import json

from .batch_models import BATCH_SCHEMA_VERSION, BatchState, MapBatchResult
from .batch_reports import format_batch_state_json, parse_batch_state_json
from .batch_result_parser import JsonValue

# RSS is expressed in whole pages. UINT64_MAX is not page aligned and cannot
# represent a native working-set byte count, including on 32-bit Windows.
_UNKNOWN_PEAK = (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class ChildSuccess:
    result: MapBatchResult
    peak_rss_bytes: int | None


@dataclass(frozen=True, slots=True)
class ChildFailure:
    code: str
    detail: str
    peak_rss_bytes: int | None
    resource_diagnostics: tuple[str, ...] = ()


type ChildMessage = ChildSuccess | ChildFailure


def encode_child_success(result: MapBatchResult, peak_rss_bytes: int | None) -> bytes:
    """Encode one result through the strict persisted-state schema."""
    state = BatchState(BATCH_SCHEMA_VERSION, (result,))
    peak = _encode_peak(peak_rss_bytes)
    return b"S" + peak + format_batch_state_json(state).encode("utf-8")


def encode_child_failure(
    code: str,
    detail: str,
    peak_rss_bytes: int | None = None,
    resource_diagnostics: tuple[str, ...] = (),
) -> bytes:
    """Encode arbitrary diagnostic text behind a bounded code prefix."""
    encoded_code = code.encode("utf-8")
    if resource_diagnostics:
        return (
            b"D"
            + _encode_peak(peak_rss_bytes)
            + json.dumps(
                {
                    "code": code,
                    "detail": detail,
                    "resource_diagnostics": resource_diagnostics,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    return (
        b"F"
        + _encode_peak(peak_rss_bytes)
        + len(encoded_code).to_bytes(4, "little")
        + encoded_code
        + detail.encode("utf-8")
    )


def decode_child_message(payload: bytes) -> ChildMessage:
    """Parse one child payload or return a typed protocol failure."""
    if payload[:1] == b"S" and len(payload) >= 9:
        try:
            peak = _decode_peak(payload[1:9])
            state = parse_batch_state_json(payload[9:].decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            return ChildFailure("invalid_child_payload", str(exc), None)
        if len(state.results) != 1:
            return ChildFailure("invalid_child_payload", "expected one result", peak)
        return ChildSuccess(state.results[0], peak)
    if payload[:1] == b"F" and len(payload) >= 13:
        peak = _decode_peak(payload[1:9])
        size = int.from_bytes(payload[9:13], "little")
        if 13 + size <= len(payload):
            try:
                code = payload[13 : 13 + size].decode("utf-8")
                detail = payload[13 + size :].decode("utf-8")
            except UnicodeError as exc:
                return ChildFailure("invalid_child_payload", str(exc), peak)
            return ChildFailure(code, detail, peak)
    if payload[:1] == b"D" and len(payload) >= 9:
        peak = _decode_peak(payload[1:9])
        try:
            value: JsonValue = json.loads(payload[9:].decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            return ChildFailure("invalid_child_payload", str(exc), peak)
        if isinstance(value, dict) and set(value) == {
            "code",
            "detail",
            "resource_diagnostics",
        }:
            code = value["code"]
            detail = value["detail"]
            diagnostics = value["resource_diagnostics"]
            if (
                isinstance(code, str)
                and isinstance(detail, str)
                and isinstance(diagnostics, list)
                and all(isinstance(item, str) for item in diagnostics)
            ):
                confirmed = tuple(item for item in diagnostics if isinstance(item, str))
                return ChildFailure(code, detail, peak, confirmed)
    return ChildFailure("invalid_child_payload", "unknown child message", None)


def _encode_peak(peak: int | None) -> bytes:
    if peak is None or peak <= 0:
        return _UNKNOWN_PEAK.to_bytes(8, "little")
    if peak >= _UNKNOWN_PEAK:
        raise ValueError("peak RSS cannot use the reserved unknown byte count")
    return peak.to_bytes(8, "little")


def _decode_peak(payload: bytes) -> int | None:
    peak = int.from_bytes(payload, "little")
    return None if peak in {0, _UNKNOWN_PEAK} else peak


__all__ = (
    "ChildFailure",
    "ChildMessage",
    "ChildSuccess",
    "decode_child_message",
    "encode_child_failure",
    "encode_child_success",
)

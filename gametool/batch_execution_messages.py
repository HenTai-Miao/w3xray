"""Strict bounded wire messages returned by isolated map children."""

from __future__ import annotations

from dataclasses import dataclass

from .batch_models import BATCH_SCHEMA_VERSION, BatchState, MapBatchResult
from .batch_reports import format_batch_state_json, parse_batch_state_json


@dataclass(frozen=True, slots=True)
class ChildSuccess:
    result: MapBatchResult
    peak_rss_bytes: int


@dataclass(frozen=True, slots=True)
class ChildFailure:
    code: str
    detail: str
    peak_rss_bytes: int


type ChildMessage = ChildSuccess | ChildFailure


def encode_child_success(result: MapBatchResult, peak_rss_bytes: int) -> bytes:
    """Encode one result through the strict persisted-state schema."""
    state = BatchState(BATCH_SCHEMA_VERSION, (result,))
    peak = max(0, peak_rss_bytes).to_bytes(8, "little")
    return b"S" + peak + format_batch_state_json(state).encode("utf-8")


def encode_child_failure(code: str, detail: str, peak_rss_bytes: int = 0) -> bytes:
    """Encode arbitrary diagnostic text behind a bounded code prefix."""
    encoded_code = code.encode("utf-8")
    return (
        b"F"
        + max(0, peak_rss_bytes).to_bytes(8, "little")
        + len(encoded_code).to_bytes(4, "little")
        + encoded_code
        + detail.encode("utf-8")
    )


def decode_child_message(payload: bytes) -> ChildMessage:
    """Parse one child payload or return a typed protocol failure."""
    if payload[:1] == b"S":
        try:
            peak = int.from_bytes(payload[1:9], "little")
            state = parse_batch_state_json(payload[9:].decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            return ChildFailure("invalid_child_payload", str(exc), 0)
        if len(state.results) != 1:
            return ChildFailure("invalid_child_payload", "expected one result", peak)
        return ChildSuccess(state.results[0], peak)
    if payload[:1] == b"F" and len(payload) >= 13:
        peak = int.from_bytes(payload[1:9], "little")
        size = int.from_bytes(payload[9:13], "little")
        if 13 + size <= len(payload):
            try:
                code = payload[13 : 13 + size].decode("utf-8")
                detail = payload[13 + size :].decode("utf-8")
            except UnicodeError as exc:
                return ChildFailure("invalid_child_payload", str(exc), peak)
            return ChildFailure(code, detail, peak)
    return ChildFailure("invalid_child_payload", "unknown child message", 0)


__all__ = (
    "ChildFailure",
    "ChildMessage",
    "ChildSuccess",
    "decode_child_message",
    "encode_child_failure",
    "encode_child_success",
)

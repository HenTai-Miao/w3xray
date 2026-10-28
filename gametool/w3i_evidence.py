"""JSON-safe complete W3I evidence, including unknown and non-finite values."""

from __future__ import annotations

import math
from dataclasses import fields, is_dataclass

from .w3i_models import W3iInfo


def w3i_info_to_dict(info: W3iInfo) -> dict[str, object]:
    """Serialize every model field without dropping original bytes or NaNs.

    Byte strings use an explicit hex envelope. Non-finite floats use a tagged
    object, so callers can require ``json.dumps(..., allow_nan=False)``. The
    field-byte stream followed by ``unconsumed_data`` reconstructs the input.
    """
    return {
        "schema": "gamexray.w3i.v1",
        "source": "war3map.w3i",
        **{
            member.name: _json_value(getattr(info, member.name))
            for member in fields(info)
        },
    }


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"encoding": "hex", "data": value.hex()}
    if isinstance(value, float) and not math.isfinite(value):
        spelling = (
            "nan" if math.isnan(value) else "+infinity" if value > 0 else "-infinity"
        )
        return {"non_finite": spelling}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            member.name: _json_value(getattr(value, member.name))
            for member in fields(value)
        }
    raise TypeError(f"unsupported W3I evidence value: {type(value).__name__}")

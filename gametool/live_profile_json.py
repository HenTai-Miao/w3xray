"""Shared pure-data JSON boundary for live and offline profile consumers."""

from __future__ import annotations

import json
from typing import Any

from .live_profile_validation import validate_profile_data


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"档案 JSON 有重复键 {key!r}；未猜测哪项有效。")
        data[key] = value
    return data


def parse_live_profile_json(payload: str | bytes) -> dict[str, Any]:
    """Validate a complete UTF-8 profile without losing duplicate declarations.

    Accept one file-leading UTF-8 BOM and preserve embedded BOM characters.
    JSON object keys must be unique at every level, before schema validation
    can consume a mapping. No file-size or record-count quota is imposed here.
    """
    text = (
        payload.decode("utf-8-sig")
        if isinstance(payload, bytes)
        else payload.removeprefix("\ufeff")
    )
    return validate_profile_data(json.loads(text, object_pairs_hook=_unique_pairs))

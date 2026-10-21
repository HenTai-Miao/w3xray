"""Stable JSON codec for map identities in resolved-icon reports."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import re
from typing import Final, TypedDict, override

from .icon_resources import IconObjectReference

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)

_IDENTITY_KEYS: Final = frozenset(("map", "sha256"))
_SHA256: Final = re.compile(r"[0-9a-f]{64}")


class _MapIdentityJson(TypedDict):
    map: str
    sha256: str


@dataclass(frozen=True, slots=True)
class IconReportMapIdentity:
    """One logical map identity carried by a resolved icon row."""

    map_path: str
    map_sha256: str


@dataclass(frozen=True, slots=True)
class IconReportMapIdentityFormatError(ValueError):
    """Malformed resolved-icon map identity JSON."""

    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


def format_icon_report_map_identities(
    references: Iterable[IconObjectReference],
) -> str:
    """Render unique map identities in stable compact JSON."""
    identities = {(item.map_path, item.map_sha256) for item in references}
    payload = tuple(
        _MapIdentityJson(map=map_path, sha256=map_sha256)
        for map_path, map_sha256 in sorted(
            identities,
            key=lambda item: (item[0].casefold(), item[0], item[1]),
        )
    )
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_icon_report_map_identities(
    text: str,
) -> tuple[IconReportMapIdentity, ...]:
    """Parse a nonempty, unique set of exact logical map identities."""
    try:
        value: JsonValue = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IconReportMapIdentityFormatError("malformed icon map JSON") from exc
    if not isinstance(value, list) or not value:
        raise IconReportMapIdentityFormatError("icon map identity set is empty")
    identities = tuple(_parse_identity(item) for item in value)
    if len(set(identities)) != len(identities):
        raise IconReportMapIdentityFormatError("duplicate icon map identity")
    return identities


def _parse_identity(value: JsonValue) -> IconReportMapIdentity:
    if not isinstance(value, dict) or set(value) != _IDENTITY_KEYS:
        raise IconReportMapIdentityFormatError("unexpected icon map identity keys")
    map_path = value["map"]
    map_sha256 = value["sha256"]
    if not isinstance(map_path, str) or not isinstance(map_sha256, str):
        raise IconReportMapIdentityFormatError("icon map identity value is not text")
    if not map_path or _SHA256.fullmatch(map_sha256) is None:
        raise IconReportMapIdentityFormatError("invalid icon map identity")
    return IconReportMapIdentity(map_path, map_sha256)

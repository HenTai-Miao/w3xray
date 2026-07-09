"""Readable script text exports with WTS-backed TRIGSTR literals resolved."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Final

from .wts import parse_wts

if TYPE_CHECKING:
    from .api import MapData

_QUOTED_TRIGSTR_RE: Final = re.compile(r'"TRIGSTR_(\d+)"', re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ReadableScriptExport:
    name: str
    text: str


def build_readable_script_exports(md: MapData) -> tuple[ReadableScriptExport, ...]:
    """Return non-WTS script texts with quoted TRIGSTR literals resolved."""
    table = _string_table(md)
    return tuple(
        ReadableScriptExport(source, resolve_trigstr_literals(text, table))
        for source, text in sorted(md.scripts.items())
        if not source.lower().endswith(".wts")
    )


def resolve_trigstr_literals(text: str, table: dict[int, str]) -> str:
    """Resolve quoted TRIGSTR_N literals while preserving unresolved tokens."""

    def replace(match: re.Match[str]) -> str:
        sid = int(match.group(1))
        value = table.get(sid)
        if value is None:
            return match.group(0)
        return f'"{_escape_script_string(value)}"'

    return _QUOTED_TRIGSTR_RE.sub(replace, text)


def _string_table(md: MapData) -> dict[int, str]:
    existing = getattr(md, "ui_strings", None)
    if isinstance(existing, dict):
        return {int(key): str(value) for key, value in existing.items()}
    wts_text = md.scripts.get("war3map.wts") or md.scripts.get("war3campaign.wts")
    if not wts_text:
        return {}
    return parse_wts(wts_text.encode("utf-8", "replace"))


def _escape_script_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )

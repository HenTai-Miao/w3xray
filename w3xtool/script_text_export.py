"""Readable script text exports with WTS-backed TRIGSTR literals resolved."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Final

from .script_sources import analysis_script_texts
from .wts import map_wts_table

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
        for source, text in analysis_script_texts(md)
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
    return map_wts_table(md)


def _escape_script_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )

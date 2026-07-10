"""Collect readable map scripts without publishing binary trigger members."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from .map_archive_reader import MapArchiveReader
from .war3_encoding import decode_warcraft_string
from .wct import WctDiagnostic, WctScript, parse_wct

if TYPE_CHECKING:
    from .map_data import MapData

_TEXT_MEMBERS: Final = ("war3map.j", "war3map.lua", "war3map.wts")
_BINARY_MEMBERS: Final = ("war3map.wtg", "war3map.wct")
WCT_TEXT_NAME: Final = "war3map.wct(自定义代码).txt"


@dataclass(frozen=True, slots=True)
class ScriptCollection:
    """Decoded script texts plus binary membership and WCT parse status."""

    texts: Mapping[str, str]
    binary_members: tuple[str, ...]
    wct_diagnostic: WctDiagnostic | None


def collect_readable_scripts(archive: MapArchiveReader) -> ScriptCollection:
    """Decode text members and publish WCT only through its readable virtual text."""
    texts: dict[str, str] = {}
    for name in _TEXT_MEMBERS:
        if not archive.has_file(name):
            continue
        try:
            raw = archive.read_file(name)
        except (KeyError, OSError, ValueError):
            continue
        texts[name] = decode_warcraft_string(raw)

    binary_members = tuple(name for name in _BINARY_MEMBERS if archive.has_file(name))
    diagnostic: WctDiagnostic | None = None
    if "war3map.wct" in binary_members:
        try:
            raw_wct = archive.read_file("war3map.wct")
        except (KeyError, OSError, ValueError):
            diagnostic = WctDiagnostic.TRUNCATED
        else:
            parsed = parse_wct(raw_wct)
            diagnostic = parsed.diagnostic
            readable = _format_wct_text(parsed)
            if readable is not None:
                texts[WCT_TEXT_NAME] = readable
    return ScriptCollection(MappingProxyType(texts), binary_members, diagnostic)


def analysis_script_texts(md: MapData) -> tuple[tuple[str, str], ...]:
    """Return sorted source-preserving texts accepted by script analyzers."""
    return tuple(
        (name, text)
        for name, text in sorted(md.scripts.items())
        if name.casefold().endswith((".j", ".lua", ".txt"))
        and not name.casefold().endswith(".wts")
    )


def _format_wct_text(script: WctScript) -> str | None:
    parts: list[str] = []
    if script.custom_code.strip():
        parts.append("// ===== 全局自定义脚本 =====\n" + script.custom_code)
    for index, trigger in enumerate(script.triggers, start=1):
        if trigger.strip():
            parts.append(f"// ===== 触发器自定义脚本 #{index} =====\n{trigger}")
    return "\n\n".join(parts) if parts else None

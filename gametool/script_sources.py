"""Collect readable map scripts without publishing binary trigger members."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Final, NamedTuple, Protocol

from .map_archive_reader import MapArchiveReader
from .extraction_diagnostics import DiagnosticTarget, read_component
from .war3_encoding import decode_warcraft_string
from .wct import WctDiagnostic, WctScript, parse_wct


class ScriptSourceHost(DiagnosticTarget, Protocol):
    """Structural surface of MapData used here (breaks map_data import cycle)."""

    @property
    def scripts(self) -> dict[str, str]: ...


_TEXT_MEMBERS: Final = ("war3map.j", "war3map.lua", "war3map.wts")
_BINARY_MEMBERS: Final = ("war3map.wtg", "war3map.wct")
WCT_TEXT_NAME: Final = "war3map.wct(自定义代码).txt"
_SCRIPT_PLACEHOLDER_CHARS: Final = "\x00\r\n\t "
_WCT_HEADER: Final = re.compile(
    r"(?m)^//(?= ===== (?:全局自定义脚本|触发器自定义脚本 #\d+) =====\r?$)"
)
_SCRIPT_TYPE_LINE: Final = re.compile(r"(?im)^脚本语言[:：]([^\r\n]*)\r?$")


class AnalysisScriptSource(NamedTuple):
    source: str
    text: str
    lua: bool | None


def script_language(
    source: str,
    *,
    available_sources: Iterable[str] = (),
    declared_script_type: str = "",
) -> bool | None:
    """Resolve language from direct file/map evidence; retain unknown context."""
    name = source.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if name.endswith(".lua"):
        return True
    if name.endswith(".j"):
        return False
    if name != WCT_TEXT_NAME.casefold():
        return None
    declared = {"lua": True, "jass": False}.get(declared_script_type.casefold())
    if declared is not None:
        return declared
    if declared_script_type.strip():
        return None
    choices = {
        name.casefold().endswith(".lua")
        for path in available_sources
        if (name := path.replace("\\", "/").rsplit("/", 1)[-1]).casefold()
        in {"war3map.j", "war3map.lua"}
    }
    return next(iter(choices)) if len(choices) == 1 else None


def script_type_from_report(text: str) -> str:
    declarations = {
        {"lua": "Lua", "jass": "JASS"}.get(value.casefold(), "unknown")
        for match in _SCRIPT_TYPE_LINE.finditer(text)
        if (value := match.group(1).strip())
    }
    if not declarations:
        return ""
    return next(iter(declarations)) if len(declarations) == 1 else "unknown"


def analysis_script_text(source: str, text: str, lua: bool | None) -> str:
    """Adapt only tool-generated WCT headers without moving source offsets."""
    if (
        source.replace("\\", "/").rsplit("/", 1)[-1].casefold()
        == WCT_TEXT_NAME.casefold()
        and lua is True
    ):
        return _WCT_HEADER.sub("--", text)
    return text


@dataclass(frozen=True, slots=True)
class ScriptCollection:
    """Decoded script texts plus binary membership and WCT parse status."""

    texts: Mapping[str, str]
    binary_members: tuple[str, ...]
    wct_diagnostic: WctDiagnostic | None
    wts_raw: bytes | None = None


def collect_readable_scripts(
    archive: MapArchiveReader,
    *,
    md: ScriptSourceHost | None = None,
) -> ScriptCollection:
    """Decode text members and publish WCT only through its readable virtual text."""
    texts: dict[str, str] = {}
    wts_raw: bytes | None = None
    for name in _TEXT_MEMBERS:
        if not archive.has_file(name):
            continue
        raw = _read_script_member(archive, name, md)
        if raw is None:
            continue
        text = _decode_script_member(raw, name, md)
        if text is None:
            continue
        texts[name] = text
        if name == "war3map.wts":
            wts_raw = raw

    binary_members = tuple(name for name in _BINARY_MEMBERS if archive.has_file(name))
    diagnostic: WctDiagnostic | None = None
    if "war3map.wct" in binary_members:
        raw_wct = _read_script_member(archive, "war3map.wct", md)
        if raw_wct is not None:
            parsed = parse_wct(raw_wct)
            diagnostic = parsed.diagnostic
            readable = _format_wct_text(parsed)
            if readable is not None:
                texts[WCT_TEXT_NAME] = readable
    return ScriptCollection(
        MappingProxyType(texts), binary_members, diagnostic, wts_raw
    )


def _read_script_member(
    archive: MapArchiveReader,
    name: str,
    md: ScriptSourceHost | None,
) -> bytes | None:
    if md is not None:
        component = (
            "wts"
            if name == "war3map.wts"
            else ("wct" if name == "war3map.wct" else "script")
        )
        return read_component(
            md, component, name, lambda: archive.read_file(name), stage="read"
        )
    try:
        return archive.read_file(name)
    except KeyError, OSError, ValueError:
        return None


def _decode_script_member(
    raw: bytes, name: str, md: ScriptSourceHost | None
) -> str | None:
    if md is not None:
        component = "wts" if name == "war3map.wts" else "script"
        return read_component(
            md, component, name, lambda: decode_warcraft_string(raw), stage="decode"
        )
    return decode_warcraft_string(raw)


def analysis_script_texts(md: ScriptSourceHost) -> tuple[tuple[str, str], ...]:
    """Return sorted source-preserving texts accepted by script analyzers."""
    return tuple((source, text) for source, text, _lua in analysis_script_sources(md))


def analysis_script_sources(md: ScriptSourceHost) -> tuple[AnalysisScriptSource, ...]:
    """Return full texts with language context, preserving names and line numbers."""
    declared = getattr(getattr(md, "w3i", None), "script_type", "")
    declared = declared if isinstance(declared, str) else ""
    entries: list[AnalysisScriptSource] = []
    for name, text in sorted(md.scripts.items()):
        if not name.casefold().endswith(
            (".j", ".lua", ".txt")
        ) or not is_substantive_script_text(text):
            continue
        lua = script_language(
            name, available_sources=md.scripts, declared_script_type=declared
        )
        entries.append(
            AnalysisScriptSource(name, analysis_script_text(name, text, lua), lua)
        )
    return tuple(entries)


def is_substantive_script_text(text: str) -> bool:
    """Return whether a decoded script contains more than placeholder bytes."""
    return bool(text.strip(_SCRIPT_PLACEHOLDER_CHARS))


def _format_wct_text(script: WctScript) -> str | None:
    parts: list[str] = []
    if script.custom_code.strip():
        parts.append("// ===== 全局自定义脚本 =====\n" + script.custom_code)
    for index, trigger in enumerate(script.triggers, start=1):
        if trigger.strip():
            parts.append(f"// ===== 触发器自定义脚本 #{index} =====\n{trigger}")
    return "\n\n".join(parts) if parts else None

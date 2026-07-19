"""Plan reversible, strict Warcraft icon virtual paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Final

from .icon_evidence_models import IconGapReason


@dataclass(frozen=True, slots=True)
class IconPathPlan:
    """Original icon text, cleaned path, and ordered exact candidates."""

    original: str
    normalized: str
    candidates: tuple[str, ...]


_KNOWN_SEGMENTS: Final = {
    "replaceabletextures": "ReplaceableTextures",
    "commandbuttons": "CommandButtons",
    "commandbuttonsdisabled": "CommandButtonsDisabled",
    "passivebuttons": "PassiveButtons",
}
_SUPPORTED_EXTENSIONS: Final = frozenset((".blp", ".tga", ".dds"))


def plan_icon_path(raw: str) -> IconPathPlan:
    """Normalize one virtual path and produce exact extension attempts."""
    reportable = reportable_icon_path(raw)
    if reportable != raw:
        return IconPathPlan(reportable, "", ())
    cleaned = raw.strip()
    if len(cleaned) >= 2 and cleaned.startswith('"') and cleaned.endswith('"'):
        cleaned = cleaned[1:-1]
    windows_path = PureWindowsPath(cleaned)
    normalized = cleaned.replace("/", "\\").lstrip("\\")
    normalized = "\\".join(
        _KNOWN_SEGMENTS.get(segment.casefold(), segment)
        for segment in normalized.split("\\")
    )
    parts = normalized.split("\\")
    if (
        not normalized
        or windows_path.drive
        or any(part in ("", ".", "..") for part in parts)
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        return IconPathPlan(raw, normalized, ())
    leaf = parts[-1]
    dot = leaf.rfind(".")
    extension = leaf[dot:] if dot >= 0 else ""
    if extension and extension.casefold() not in _SUPPORTED_EXTENSIONS:
        return IconPathPlan(raw, normalized, ())
    base = normalized[: -len(extension)] if extension else normalized
    ordered = (normalized, f"{base}.blp", f"{base}.tga", f"{base}.dds")
    seen: set[str] = set()
    candidates: list[str] = []
    for candidate in ordered:
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)
    return IconPathPlan(raw, normalized, tuple(candidates))


def reportable_icon_path(value: str) -> str:
    """Escape isolated surrogates so malformed map text remains strict UTF-8."""
    try:
        _ = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return "".join(
            f"\\u{ord(character):04x}"
            if 0xD800 <= ord(character) <= 0xDFFF
            else character
            for character in value
        )
    return value


def is_canonical_icon_gap_path(normalized: str, reason: IconGapReason) -> bool:
    """Accept invalid references without pretending they have a usable path."""
    plan = plan_icon_path(normalized)
    if plan.normalized != normalized:
        return False
    if reason is IconGapReason.INVALID_REFERENCE:
        return not plan.candidates
    return bool(normalized and plan.candidates)

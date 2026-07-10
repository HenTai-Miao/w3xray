"""Warcraft text decoding helpers for legacy map files."""

from __future__ import annotations

import codecs
import locale


_MULTIBYTE_WINDOWS_CODECS = frozenset((
    "big5",
    "cp932",
    "cp949",
    "cp950",
    "euc-kr",
    "gb18030",
    "gbk",
    "shift-jis",
))


def default_legacy_codecs() -> tuple[str, ...]:
    """Return legacy encodings in the order a Windows Warcraft map expects."""
    preferred = locale.getpreferredencoding(False)
    normalized = _normalized_codec_name(preferred)
    if normalized in _MULTIBYTE_WINDOWS_CODECS:
        candidates = [preferred, "gbk", "gb18030", "mbcs"]
    else:
        candidates = ["gbk", "gb18030", preferred, "mbcs"]
    return _known_non_utf8_codecs(candidates)


def decode_warcraft_string(
    raw: bytes,
    *,
    legacy_codecs: tuple[str, ...] | None = None,
    allow_latin1: bool = False,
) -> str:
    """Decode map text as UTF-8, then the active Windows ACP, then Chinese fallbacks."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for encoding in legacy_codecs if legacy_codecs is not None else default_legacy_codecs():
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    if allow_latin1:
        return raw.decode("latin-1")
    return raw.decode("utf-8", "replace")


def _known_non_utf8_codecs(candidates: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        name = candidate.strip()
        if not name:
            continue
        try:
            info = codecs.lookup(name)
        except LookupError:
            continue
        normalized = info.name.lower()
        if normalized == "utf-8" or normalized in seen:
            continue
        seen.add(normalized)
        result.append(name)
    return tuple(result)


def _normalized_codec_name(name: str) -> str:
    try:
        return codecs.lookup(name).name.lower().replace("_", "-")
    except LookupError:
        return ""

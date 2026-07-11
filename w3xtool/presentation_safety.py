"""Sanitize untrusted text at terminal and dialog presentation boundaries."""

from __future__ import annotations

from collections.abc import Iterable
import os
import re
from typing import Final
import unicodedata

_CONTROL_CATEGORIES: Final = frozenset(("Cc", "Cf"))
_MAX_DISPLAY_CHARS: Final = 4096
_MAX_ERROR_CHARS: Final = 512
_QUOTED_ABSOLUTE_PATH: Final = re.compile(
    r"(?P<quote>['\"])(?:(?:[A-Za-z]:[\\/]|/)[^'\"\r\n]*)(?P=quote)",
)
_UNQUOTED_ABSOLUTE_PATH: Final = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/][^\s'\"]+|/(?!/)[^\s'\"]+)",
)


def single_line_text(value: str, *, max_chars: int = _MAX_DISPLAY_CHARS) -> str:
    """Replace terminal-affecting Unicode controls and bound displayed text."""
    return _flatten_controls(value)[:max_chars]


def tsv_cell(value: str) -> str:
    """Flatten one durable TSV cell and neutralize spreadsheet formulas."""
    cleaned = _flatten_controls(value)
    stripped = cleaned.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        prefix_size = len(cleaned) - len(stripped)
        return f"{cleaned[:prefix_size]}'{cleaned[prefix_size:]}"
    return cleaned


def redact_user_text(value: str, *, paths: Iterable[str] = ()) -> str:
    """Remove absolute host paths and Unicode controls without truncating."""
    message = value
    for path in paths:
        message = _redact_path(message, path)
    message = _QUOTED_ABSOLUTE_PATH.sub(_replace_quoted_path, message)
    message = _UNQUOTED_ABSOLUTE_PATH.sub("<path>", message)
    return _flatten_controls(message)


def _flatten_controls(value: str) -> str:
    return "".join(
        " " if unicodedata.category(char) in _CONTROL_CATEGORIES else char
        for char in value
    )


def format_user_exception(
    error: BaseException,
    *,
    paths: Iterable[str] = (),
) -> str:
    """Return a useful bounded error without host absolute paths or controls."""
    redacted_paths = list(paths)
    for candidate in (
        getattr(error, "filename", None),
        getattr(error, "filename2", None),
    ):
        if isinstance(candidate, str):
            redacted_paths.append(candidate)
    message = redact_user_text(str(error), paths=redacted_paths)
    return single_line_text(
        f"{type(error).__name__}: {message}",
        max_chars=_MAX_ERROR_CHARS,
    )


def _redact_path(message: str, path: str) -> str:
    if not path:
        return message
    absolute = os.path.abspath(os.path.expanduser(path))
    variants = {absolute, os.path.realpath(absolute)}
    if os.path.isabs(path):
        variants.add(path)
    for candidate in sorted(variants, key=len, reverse=True):
        message = message.replace(candidate, "<path>")
    return message


def _replace_quoted_path(match: re.Match[str]) -> str:
    quote = match.group("quote")
    return f"{quote}<path>{quote}"

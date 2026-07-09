"""User-provided MPQ listfile parsing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import os
from pathlib import PureWindowsPath
from typing import Protocol

from .war3_encoding import decode_warcraft_string


class ExternalNameArchive(Protocol):
    def has_file(self, name: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ExternalListfileReport:
    confirmed: tuple[str, ...]
    missing: tuple[str, ...]
    unsafe: tuple[str, ...]
    duplicates: tuple[str, ...]


def read_external_listfile(path: str | None) -> tuple[str, ...]:
    """Read archive paths from a user-provided listfile."""
    if not path:
        return ()
    file_path = os.fspath(path)
    try:
        with open(file_path, "rb") as handle:
            text = decode_warcraft_string(handle.read(), allow_latin1=True)
    except OSError:
        return ()
    names: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        name = line.strip()
        is_slash_comment = name.startswith("//") and "/" not in name[2:]
        if not name or name.startswith("#") or is_slash_comment:
            continue
        names.append(name)
    return tuple(names)


def validate_external_names(
    archive: ExternalNameArchive,
    names: Sequence[str],
) -> ExternalListfileReport:
    """Classify user-provided archive names without trusting the listfile."""
    confirmed: list[str] = []
    missing: list[str] = []
    unsafe: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        key = name.replace("/", "\\").lower()
        if key in seen:
            duplicates.append(name)
            continue
        seen.add(key)
        if not _is_safe_archive_name(name):
            unsafe.append(name)
            continue
        try:
            exists = archive.has_file(name)
        except (KeyError, OSError, ValueError):
            exists = False
        (confirmed if exists else missing).append(name)
    return ExternalListfileReport(
        tuple(confirmed),
        tuple(missing),
        tuple(unsafe),
        tuple(duplicates),
    )


def _is_safe_archive_name(name: str) -> bool:
    if "\0" in name or name.startswith(("/", "\\")) or PureWindowsPath(name).drive:
        return False
    parts = tuple(part for part in name.replace("\\", "/").split("/") if part not in ("", "."))
    return bool(parts) and ".." not in parts

"""User-provided MPQ listfile parsing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from io import StringIO
import os
from pathlib import PureWindowsPath
from pathlib import Path
from typing import Final, Protocol

from .war3_encoding import decode_warcraft_string
from .bounded_file import read_bounded_regular_file


MAX_EXTERNAL_LISTFILE_BYTES: Final[int | None] = None


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
        payload, _identity = read_bounded_regular_file(
            Path(file_path), MAX_EXTERNAL_LISTFILE_BYTES
        )
    except OSError:
        return ()
    text = decode_warcraft_string(payload, allow_latin1=True)
    names: list[str] = []
    with StringIO(text, newline=None) as lines:
        for raw_line in lines:
            line = raw_line.rstrip("\r\n")
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
        except KeyError, OSError, ValueError:
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
    parts = tuple(
        part for part in name.replace("\\", "/").split("/") if part not in ("", ".")
    )
    return bool(parts) and ".." not in parts

"""User-provided MPQ listfile parsing."""

from __future__ import annotations

import os

from .war3_encoding import decode_warcraft_string


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
    seen: set[str] = set()
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        name = line.strip()
        if not name or name.startswith("#") or name.startswith("//"):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return tuple(names)

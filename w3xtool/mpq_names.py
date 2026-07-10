"""MPQ filename byte candidates and StormLib-compatible locale choice."""

from __future__ import annotations

import codecs
from collections.abc import Sequence
from typing import NamedTuple

from .war3_encoding import default_legacy_codecs


class HashEntry(NamedTuple):
    """One classic MPQ hash-table entry."""

    name_a: int
    name_b: int
    locale: int
    platform: int
    block_index: int


def encoded_name_candidates(
    name: str,
    legacy_codecs: tuple[str, ...] | None = None,
) -> tuple[bytes, ...]:
    """Encode a name in configured order and remove duplicate byte sequences."""
    encodings = (
        ("utf-8", *default_legacy_codecs())
        if legacy_codecs is None
        else legacy_codecs
    )
    candidates: list[bytes] = []
    seen: set[bytes] = set()
    for encoding in encodings:
        codec = codecs.lookup(encoding)
        try:
            candidate = name.encode(codec.name)
        except UnicodeEncodeError:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
    return tuple(candidates)


def select_hash_entry(
    entries: Sequence[HashEntry],
    *,
    locale_id: int = 0,
    platform: int = 0,
) -> HashEntry | None:
    """Apply StormLib 9.25 exact-then-last-neutral hash selection."""
    best: HashEntry | None = None
    for entry in entries:
        if (locale_id or platform) and entry.locale == locale_id and entry.platform == platform:
            return entry
        if entry.locale in (0, locale_id) and entry.platform in (0, platform):
            best = entry
    return best

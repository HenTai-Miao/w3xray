"""Immutable models for trusted base-object description evidence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


type DescriptionCacheKey = tuple[str, str, str, int | None]


@dataclass(frozen=True, slots=True)
class DescriptionCacheEntry:
    """One validated original base-object text value."""

    category: str
    base_id: str
    role: str
    level: int | None
    raw_value: str
    readable_value: str
    source_map_sha256: str
    source_path: str

    @property
    def key(self) -> DescriptionCacheKey:
        """Return the exact lookup identity."""
        return self.category, self.base_id, self.role, self.level


@dataclass(frozen=True, slots=True)
class DescriptionCache:
    """Unique cache entries plus deterministic conflict diagnostics."""

    entries: tuple[DescriptionCacheEntry, ...]
    _by_key: Mapping[DescriptionCacheKey, tuple[DescriptionCacheEntry, ...]]
    conflict_count: int
    diagnostics: tuple[str, ...]

    @classmethod
    def build(
        cls,
        entries: Iterable[DescriptionCacheEntry],
        diagnostics: Iterable[str] = (),
    ) -> DescriptionCache:
        """Discard conflicting keys and freeze unique values."""
        grouped: dict[DescriptionCacheKey, list[DescriptionCacheEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.key, []).append(entry)
        retained: list[DescriptionCacheEntry] = []
        conflicts: list[str] = []
        for key in sorted(grouped, key=_cache_key_sort):
            candidates = tuple(sorted(grouped[key], key=_entry_sort_key))
            values = {candidate.raw_value for candidate in candidates}
            if len(values) > 1:
                category, base_id, role, level = key
                level_text = "" if level is None else f"/{level}"
                conflicts.append(
                    f"缓存来源冲突：{category}/{base_id}/{role}{level_text}"
                )
                continue
            retained.append(candidates[0])
        ordered = tuple(sorted(retained, key=_entry_sort_key))
        by_key = MappingProxyType({entry.key: (entry,) for entry in ordered})
        all_diagnostics = tuple((*sorted(set(diagnostics)), *conflicts))
        return cls(ordered, by_key, len(conflicts), all_diagnostics)

    def lookup(
        self,
        category: str,
        base_id: str,
        role: str,
        level: int | None,
    ) -> tuple[DescriptionCacheEntry, ...]:
        """Look up one exact base-object role and level."""
        return self._by_key.get((category, base_id, role, level), ())


def _cache_key_sort(key: DescriptionCacheKey) -> tuple[str, str, str, int]:
    category, base_id, role, level = key
    return category.casefold(), base_id, role.casefold(), -1 if level is None else level


def _entry_sort_key(
    entry: DescriptionCacheEntry,
) -> tuple[str, str, str, int, str, str]:
    return (*_cache_key_sort(entry.key), entry.raw_value, entry.source_path.casefold())


EMPTY_DESCRIPTION_CACHE: Final = DescriptionCache.build(())

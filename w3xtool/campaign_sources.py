"""Pure campaign child-map ordering and archive reopening helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, ContextManager

from .archive_source import PathArchiveSource

if TYPE_CHECKING:
    from .map_archive_reader import MapArchiveReader
    from .map_data import MapData
    from .w3f import W3fInfo


def campaign_inner_maps(w3f: W3fInfo | None, archive_names: Iterable[str]) -> tuple[str, ...]:
    """Return archive map names in declared W3F order, then remaining members."""
    archive_maps: dict[str, str] = {}
    for name in archive_names:
        if _is_map(name):
            archive_maps.setdefault(_path_key(name), name)

    ordered: list[str] = []
    used: set[str] = set()
    if w3f is not None:
        for entry in w3f.maps:
            key = _path_key(entry.path)
            archive_name = archive_maps.get(key)
            if archive_name is not None and key not in used:
                ordered.append(archive_name)
                used.add(key)
    for key, archive_name in archive_maps.items():
        if key not in used:
            ordered.append(archive_name)
    return tuple(ordered)


def open_map_source(md: MapData) -> ContextManager[MapArchiveReader]:
    """Open a map's retained archive source, or its on-disk path as fallback."""
    if md.archive_source is not None:
        return md.archive_source.open()
    return PathArchiveSource(md.path).open()


def _is_map(name: str) -> bool:
    return name.casefold().endswith((".w3x", ".w3m"))


def _path_key(path: str) -> str:
    return path.replace("/", "\\").casefold()

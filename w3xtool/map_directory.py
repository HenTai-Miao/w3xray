"""Directory scanning helpers for map selection."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Final

from .api import quick_map_name

BATTLE_MAP_EXTENSIONS: Final = frozenset({".w3x", ".w3m"})
MAP_SOURCE_EXTENSIONS: Final = frozenset({".w3x", ".w3m", ".w3n"})
DEFAULT_SCAN_WORKERS: Final = 8

MapNameLoader = Callable[[str], str]
BattleMapEntry = tuple[str, str]


def scan_map_sources(directory: str) -> tuple[str, ...]:
    """Return every supported map or campaign in stable relative-path order."""
    root_path = os.path.abspath(directory)
    sources: list[str] = []
    for root, dirs, files in os.walk(root_path):
        dirs.sort(key=lambda name: (name.casefold(), name))
        files.sort(key=lambda name: (name.casefold(), name))
        for filename in files:
            if Path(filename).suffix.casefold() in MAP_SOURCE_EXTENSIONS:
                sources.append(os.path.join(root, filename))
    return tuple(
        sorted(
            sources,
            key=lambda path: (
                os.path.relpath(path, root_path).casefold(),
                os.path.relpath(path, root_path),
            ),
        ),
    )


def scan_battle_maps(
    directory: str,
    *,
    name_loader: MapNameLoader = quick_map_name,
    max_workers: int | None = None,
) -> list[BattleMapEntry]:
    """Find battle maps and load display names in a worker pool."""
    files = _sorted_existing_paths(_iter_battle_map_paths(directory))
    if not files:
        return []

    workers = _worker_count(len(files), max_workers)
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="w3xray-scan"
    ) as pool:
        return list(pool.map(lambda path: (path, name_loader(path)), files))


def _iter_battle_map_paths(directory: str) -> Iterable[str]:
    for root, _dirs, files in os.walk(directory):
        for filename in files:
            path = os.path.join(root, filename)
            if Path(filename).suffix.lower() in BATTLE_MAP_EXTENSIONS:
                yield path


def _sorted_existing_paths(paths: Iterable[str]) -> list[str]:
    existing = []
    for path in set(paths):
        try:
            modified_at = os.path.getmtime(path)
        except OSError:
            continue
        existing.append((modified_at, path))
    existing.sort(key=lambda item: (-item[0], item[1]))
    return [path for _modified_at, path in existing]


def _worker_count(file_count: int, configured: int | None) -> int:
    if configured is not None:
        return max(1, min(configured, file_count))
    return max(1, min(DEFAULT_SCAN_WORKERS, file_count))

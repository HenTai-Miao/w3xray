"""Optional map metadata loaders used by the high-level API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import MapData
    from .load_context import MapLoadContext
    from .mpq import MPQArchive


def add_world_metadata(md: "MapData", archive: "MPQArchive", wts: dict) -> None:
    """Load regions, cameras and sounds from World Editor metadata files."""
    from .w3world import parse_cameras, parse_regions, parse_sounds

    if archive.has_file("war3map.w3r"):
        try:
            md.regions = parse_regions(archive.read_file("war3map.w3r"), wts)
        except (KeyError, ValueError):
            md.regions = []
    if archive.has_file("war3map.w3c"):
        try:
            md.cameras = parse_cameras(archive.read_file("war3map.w3c"))
        except (KeyError, ValueError):
            md.cameras = []
    if archive.has_file("war3map.w3s"):
        try:
            md.sounds = parse_sounds(archive.read_file("war3map.w3s"))
        except (KeyError, ValueError):
            md.sounds = []


def add_game_configs(md: "MapData", archive: "MPQArchive") -> None:
    """Load visible .wgc game configurations without failing map loading."""
    from .gameconfig import (
        NamedGameConfiguration,
        find_internal_game_config_names,
        parse_game_configuration,
    )

    names = list(archive.list_files())
    names.extend(name for name in ("war3map.wgc", "testconfig.wgc") if archive.has_file(name))
    configs = []
    for name in find_internal_game_config_names(names):
        try:
            configs.append(NamedGameConfiguration(name, parse_game_configuration(archive.read_file(name))))
        except (KeyError, ValueError):
            continue
    md.game_configs = configs


def add_trigger_summary(md: "MapData", archive: "MPQArchive", load_context: "MapLoadContext | None" = None) -> None:
    """Load a trigger tree summary from war3map.wtg when present."""
    if not archive.has_file("war3map.wtg"):
        return
    try:
        from .wtg import parse_wtg

        schema = load_context.trigger_schema if load_context is not None else None
        md.trigger_summary = parse_wtg(archive.read_file("war3map.wtg"), schema)
    except (KeyError, ValueError):
        md.trigger_summary = None


def add_preview_icons(md: "MapData", archive: "MPQArchive") -> None:
    """Load minimap preview icons from war3map.mmp when present."""
    if not archive.has_file("war3map.mmp"):
        return
    try:
        from .mmp import parse_preview_icons

        md.preview_icons = parse_preview_icons(archive.read_file("war3map.mmp"))
    except (KeyError, ValueError):
        md.preview_icons = None


def add_import_summary(md: "MapData", archive: "MPQArchive") -> None:
    """Load map/campaign import tables with missing-file diagnostics."""
    from .mpq_files import import_tables_from_archive

    tables = import_tables_from_archive(archive)
    if not tables:
        return
    from .imp import ImportSummary

    entries = tuple(entry for table in tables for entry in table.entries)
    resolved = []
    missing = []
    for entry in entries:
        actual = _resolve_import_path(archive, entry)
        if actual is None:
            missing.append(entry.candidate_paths[0] if entry.candidate_paths else entry.path)
        else:
            resolved.append(actual)
    md.import_summary = ImportSummary(
        version=tables[0].version,
        entries=entries,
        resolved_paths=tuple(resolved),
        missing_paths=tuple(missing),
    )


def _resolve_import_path(archive: "MPQArchive", entry) -> str | None:
    for path in entry.candidate_paths:
        if archive.has_file(path):
            return path
    return None

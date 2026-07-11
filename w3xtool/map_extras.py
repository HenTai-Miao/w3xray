"""Optional map metadata loaders used by the high-level API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .extraction_diagnostics import (
    ComponentParseError,
    read_component,
    record_component_parse_issue,
)

if TYPE_CHECKING:
    from .api import MapData
    from .load_context import MapLoadContext
    from .map_archive_reader import MapArchiveReader


def add_world_metadata(md: "MapData", archive: "MapArchiveReader", wts: dict) -> None:
    """Load regions, cameras and sounds from World Editor metadata files."""
    from .w3world import parse_cameras, parse_regions, parse_sounds

    if archive.has_file("war3map.w3r"):
        payload = read_component(
            md,
            "world",
            "war3map.w3r",
            lambda: archive.read_file("war3map.w3r"),
            stage="read",
        )
        parsed = (
            read_component(
                md,
                "world",
                "war3map.w3r",
                lambda: parse_regions(_require_world_header(payload, {5}, "W3R"), wts),
                stage="parse",
            )
            if payload is not None
            else None
        )
        md.regions = parsed or []
        _record_world_count_issue(md, "war3map.w3r", payload, len(md.regions))
    if archive.has_file("war3map.w3c"):
        payload = read_component(
            md,
            "world",
            "war3map.w3c",
            lambda: archive.read_file("war3map.w3c"),
            stage="read",
        )
        parsed = (
            read_component(
                md,
                "world",
                "war3map.w3c",
                lambda: parse_cameras(_require_world_header(payload, {0}, "W3C")),
                stage="parse",
            )
            if payload is not None
            else None
        )
        md.cameras = parsed or []
        _record_world_count_issue(md, "war3map.w3c", payload, len(md.cameras))
    if archive.has_file("war3map.w3s"):
        payload = read_component(
            md,
            "world",
            "war3map.w3s",
            lambda: archive.read_file("war3map.w3s"),
            stage="read",
        )
        parsed = (
            read_component(
                md,
                "world",
                "war3map.w3s",
                lambda: parse_sounds(_require_world_header(payload, {1, 3}, "W3S")),
                stage="parse",
            )
            if payload is not None
            else None
        )
        md.sounds = parsed or []
        _record_world_count_issue(md, "war3map.w3s", payload, len(md.sounds))


def add_game_configs(md: "MapData", archive: "MapArchiveReader") -> None:
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
        parsed = read_component(
            md,
            "wgc",
            name,
            lambda source=name: parse_game_configuration(archive.read_file(source)),
        )
        if parsed is not None:
            configs.append(NamedGameConfiguration(name, parsed))
    md.game_configs = configs


def add_trigger_summary(md: "MapData", archive: "MapArchiveReader", load_context: "MapLoadContext | None" = None) -> None:
    """Load a trigger tree summary from war3map.wtg when present."""
    if not archive.has_file("war3map.wtg"):
        return
    from .wtg import parse_wtg

    schema = load_context.trigger_schema if load_context is not None else None
    md.trigger_summary = read_component(
        md,
        "wtg",
        "war3map.wtg",
        lambda: parse_wtg(archive.read_file("war3map.wtg"), schema),
    )
    if md.trigger_summary is not None and md.trigger_summary.parse_failures:
        first = md.trigger_summary.parse_failures[0]
        record_component_parse_issue(
            md,
            "wtg",
            "war3map.wtg",
            f"{len(md.trigger_summary.parse_failures)} parse failure(s); first at {first.offset}: {first.reason}",
        )


def add_preview_icons(md: "MapData", archive: "MapArchiveReader") -> None:
    """Load minimap preview icons from war3map.mmp when present."""
    if not archive.has_file("war3map.mmp"):
        return
    from .mmp import parse_preview_icons

    md.preview_icons = read_component(
        md,
        "mmp",
        "war3map.mmp",
        lambda: parse_preview_icons(archive.read_file("war3map.mmp")),
    )


def add_import_summary(md: "MapData", archive: "MapArchiveReader") -> None:
    """Load map/campaign import tables with missing-file diagnostics."""
    from .mpq_files import import_tables_from_archive

    tables = import_tables_from_archive(archive, md=md)
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


def _resolve_import_path(archive: "MapArchiveReader", entry) -> str | None:
    for path in entry.candidate_paths:
        if archive.has_file(path):
            return path
    return None


def _require_world_header(data: bytes, versions: set[int], kind: str) -> bytes:
    if len(data) < 8:
        raise ComponentParseError(f"truncated {kind} header")
    version = int.from_bytes(data[:4], "little", signed=True)
    if version not in versions:
        raise ComponentParseError(f"unsupported {kind} version: {version}")
    return data


def _record_world_count_issue(
    md: "MapData",
    source: str,
    data: bytes | None,
    recovered: int,
) -> None:
    if data is None or len(data) < 8:
        return
    declared = int.from_bytes(data[4:8], "little", signed=True)
    if declared != recovered:
        record_component_parse_issue(
            md,
            "world",
            source,
            f"recovered {recovered} of {declared} records",
        )

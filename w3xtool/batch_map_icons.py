"""Per-map named and anonymous icon discovery and streaming export."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unicodedata import normalize

from .batch_icon_export import (
    IconExportRecord,
    export_anonymous_icon,
    export_named_icon,
)
from .campaign_sources import open_map_source
from .extraction_ledger import ExtractionLedger
from .game_data_source import GameDataSource
from .icon_resources import (
    AnonymousIconArchive,
    IconObjectReference,
    NamedIconResource,
    TrustedIconEvidenceSource,
    collect_icon_references,
    iter_anonymous_blps,
    resolve_named_icon,
)
from .map_data import GameObject, MapData


def export_map_icons(
    root: MapData,
    maps: tuple[MapData, ...],
    stage: Path,
    game_source: GameDataSource | None,
    source_digest: str,
) -> tuple[tuple[IconExportRecord, ...], int, int]:
    """Discover and stream-export every provable icon from one map tree."""
    records: list[IconExportRecord] = []
    named_indexes: dict[tuple[str, str], int] = {}
    unresolved: set[str] = set()
    anonymous_failures = 0
    with ExitStack() as stack:
        opened = tuple(
            (item, stack.enter_context(open_map_source(item))) for item in maps
        )
        root_archive = opened[0][1]
        for item, archive in opened:
            sources = (archive,) if item is root else (archive, root_archive)
            for reference in collect_icon_references(_map_objects(item)):
                resource = resolve_named_icon(reference, sources, game_source)
                if resource is None:
                    unresolved.add(reference.normalized_path.casefold())
                    continue
                _merge_named_icon(records, named_indexes, stage, resource)
            ledger = item.extraction_ledger
            if ledger is None:
                continue
            expected = _anonymous_blp_count(ledger)
            if not isinstance(archive, AnonymousIconArchive):
                anonymous_failures += expected
                continue
            exported = 0
            for resource in iter_anonymous_blps(archive, ledger):
                records.append(export_anonymous_icon(str(stage), resource))
                exported += 1
            anonymous_failures += max(0, expected - exported)
        if isinstance(game_source, TrustedIconEvidenceSource):
            for resource in game_source.historical_icons_for(source_digest).resources:
                unresolved.discard(resource.normalized_path.casefold())
                _merge_named_icon(records, named_indexes, stage, resource)
    return (
        canonicalize_icon_paths(stage, tuple(records)),
        len(unresolved),
        anonymous_failures,
    )


def canonicalize_icon_paths(
    stage: Path,
    records: tuple[IconExportRecord, ...],
) -> tuple[IconExportRecord, ...]:
    """Record the exact spelling of files published on the local filesystem."""
    actual_paths: dict[str, list[str]] = {}
    for path in Path(stage, "图标").rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(stage).as_posix()
        actual_paths.setdefault(_path_key(relative), []).append(relative)
    return tuple(
        replace(
            record,
            original_relative_path=_canonical_path(
                record.original_relative_path, actual_paths
            ),
            png_relative_path=_canonical_path(record.png_relative_path, actual_paths),
        )
        for record in records
    )


def _map_objects(item: MapData) -> tuple[GameObject, ...]:
    return tuple(obj for values in item.objects.values() for obj in values)


def _anonymous_blp_count(ledger: ExtractionLedger) -> int:
    return sum(
        entry.block_index is not None
        and entry.internal_path.replace("\\", "/").casefold().startswith("unknown/")
        and entry.internal_path.casefold().endswith(".blp")
        for entry in ledger.entries
    )


def _reference_key(item: IconObjectReference) -> tuple[str, str, str]:
    return item.category.casefold(), item.object_id, item.object_name


def _merge_named_icon(
    records: list[IconExportRecord],
    named_indexes: dict[tuple[str, str], int],
    stage: Path,
    resource: NamedIconResource,
) -> None:
    key = (resource.normalized_path.casefold(), resource.sha256)
    previous = named_indexes.get(key)
    if previous is None:
        named_indexes[key] = len(records)
        records.append(export_named_icon(str(stage), resource))
        return
    current = records[previous]
    merged = tuple(
        sorted(set((*current.objects, *resource.objects)), key=_reference_key)
    )
    records[previous] = replace(current, objects=merged)


def _canonical_path(name: str, actual_paths: dict[str, list[str]]) -> str:
    candidates = actual_paths.get(_path_key(name), ())
    if name in candidates:
        return name
    return candidates[0] if len(candidates) == 1 else name


def _path_key(name: str) -> str:
    return normalize("NFC", name.replace("\\", "/")).casefold()

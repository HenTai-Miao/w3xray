"""Per-map named and anonymous icon discovery and streaming export."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from unicodedata import normalize

from .batch_icon_export import (
    IconExportRecord,
    export_anonymous_icon,
    export_named_icon,
)
from .campaign_sources import open_map_source
from .game_data_source import GameDataSource
from .icon_evidence_builder import build_icon_evidence_index
from .icon_evidence_index import (
    IconEvidenceIndex,
    merge_icon_evidence_indexes,
)
from .icon_evidence_models import (
    IconArchiveLayer,
    IconResolutionLayer,
    ResolvedIconEvidence,
)
from .icon_resources import IconObjectReference
from .map_data import MapData


@dataclass(frozen=True, slots=True)
class BatchIconEvidence:
    """Physical exports paired with their complete immutable evidence index."""

    exports: tuple[IconExportRecord, ...]
    index: IconEvidenceIndex


def export_map_icons(
    root: MapData,
    maps: tuple[MapData, ...],
    stage: Path,
    game_source: GameDataSource | None,
) -> BatchIconEvidence:
    """Discover and stream-export every provable icon from one map tree."""
    records: list[IconExportRecord] = []
    named_indexes: dict[tuple[str, str], int] = {}
    indexes: list[IconEvidenceIndex] = []
    with ExitStack() as stack:
        opened = tuple(
            (item, stack.enter_context(open_map_source(item))) for item in maps
        )
        root_archive = opened[0][1]
        for item, archive in opened:
            layers = [
                IconArchiveLayer(
                    IconResolutionLayer.CURRENT_MAP,
                    archive,
                    item.path,
                )
            ]
            if item is not root:
                layers.append(
                    IconArchiveLayer(
                        IconResolutionLayer.CAMPAIGN_ROOT,
                        root_archive,
                        root.path,
                    )
                )
            index = build_icon_evidence_index(item, tuple(layers), game_source)
            item.icon_evidence = index
            indexes.append(index)
            for row in index.resolved:
                _merge_resolved_icon(records, named_indexes, stage, row)
            records.extend(
                export_anonymous_icon(str(stage), resource)
                for resource in index.anonymous
            )
    return BatchIconEvidence(
        canonicalize_icon_paths(stage, tuple(records)),
        merge_icon_evidence_indexes(tuple(indexes)),
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


def _merge_resolved_icon(
    records: list[IconExportRecord],
    named_indexes: dict[tuple[str, str], int],
    stage: Path,
    row: ResolvedIconEvidence,
) -> None:
    key = (row.reference.normalized_path.casefold(), row.content_sha256)
    previous = named_indexes.get(key)
    if previous is None:
        named_indexes[key] = len(records)
        records.append(export_named_icon(str(stage), row))
        return
    current = records[previous]
    merged = tuple(sorted(set((*current.objects, row.reference)), key=_reference_key))
    records[previous] = replace(current, objects=merged)


def _reference_key(item: IconObjectReference) -> tuple[str, ...]:
    values = (
        item.map_sha256,
        item.map_path,
        item.map_scope,
        item.category,
        item.object_id,
        item.object_name,
        item.base_id,
        item.field_key,
        item.field_label,
        item.field_type,
        item.field_source,
        item.wts_source,
        item.normalized_path,
        item.requested_path,
    )
    return tuple(part for value in values for part in (value.casefold(), value))


def _canonical_path(name: str, actual_paths: dict[str, list[str]]) -> str:
    candidates = actual_paths.get(_path_key(name), ())
    if name in candidates:
        return name
    return candidates[0] if len(candidates) == 1 else name


def _path_key(name: str) -> str:
    return normalize("NFC", name.replace("\\", "/")).casefold()

"""Map archive lifecycle and recursive extraction orchestration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

from .archive_inventory import InventoryArchive, build_archive_inventory
from .archive_source import PathArchiveSource
from .base_objects import BASE_OBJECTS
from .campaign_child_loader import load_campaign_children
from .campaign_sources import campaign_inner_maps
from .client_object_data import merge_client_base_objects
from .external_listfile import validate_external_names
from .extraction_diagnostics import (
    DiagnosticSeverity,
    ExtractionDiagnostic,
    read_component,
    record_component_failure,
    record_diagnostic,
)
from .item_relation_builder import build_item_relation_index
from .load_context import MapLoadContext
from .map_archive_open import open_map_archive, source_sha256
from .map_archive_reader import MapArchiveReader
from .map_components import (
    _add_preplaced,
    _add_script_refs,
    _add_w3f,
    _add_w3i,
    _map_name,
)
from .map_data import GameObject, MapData
from .mpq import MPQArchive
from .mpq_files import list_archive_files
from .object_candidates import OBJECT_EXTS, collect_object_candidates
from .object_pipeline import populate_object_pipeline_from_context
from .references import build_reference_graph
from .script_sources import analysis_script_texts, collect_readable_scripts
from .supplemented_source import SupplementedPathArchiveSource
from .wts import parse_wts, validate_wts_component

_MAX_CAMPAIGN_CHILDREN: Final = 256
_MAX_CAMPAIGN_CHILD_BYTES: Final = 512 * 1024 * 1024
_MAX_CAMPAIGN_READ_BYTES: Final = 512 * 1024 * 1024


def load_map(
    path: str,
    _depth: int = 0,
    shared_index: Mapping[tuple[str, str], GameObject] | None = None,
    load_context: MapLoadContext | None = None,
) -> MapData:
    path = os.fspath(path)
    if load_context is None:
        load_context = MapLoadContext()
    with open_map_archive(
        path,
        author_bundle_path=load_context.author_bundle_path if _depth == 0 else None,
        compat_bundle_path=load_context.compat_bundle_path if _depth == 0 else None,
        archive_factory=MPQArchive,
    ) as archive:
        md = _load_map_impl(archive, path, _depth, shared_index, load_context)
        md.archive_source = _root_archive_source(path, load_context)
        if isinstance(archive, InventoryArchive):
            md.extraction_ledger = build_archive_inventory(archive, source_sha256(path))
        return md


def _load_map_impl(
    archive: MapArchiveReader,
    path: str,
    _depth: int,
    shared_index: Mapping[tuple[str, str], GameObject] | None,
    load_context: MapLoadContext,
) -> MapData:
    md = MapData(
        path=path, name=_map_name(archive), archive_source=PathArchiveSource(path)
    )
    script_collection = collect_readable_scripts(archive, md=md)
    wts = {}
    wts_raw = script_collection.wts_raw
    if wts_raw is not None:
        parsed_wts = read_component(
            md,
            "wts",
            "war3map.wts",
            lambda: validate_wts_component(
                wts_raw,
                parse_wts(wts_raw),
            ),
            stage="parse",
        )
        wts = parsed_wts or {}

    md.ui_strings = dict(wts)
    if script_collection.wct_diagnostic is not None:
        record_diagnostic(
            md,
            ExtractionDiagnostic(
                component="wct",
                source="war3map.wct",
                stage="parse",
                severity=DiagnosticSeverity.WARNING,
                message=f"WCT parse diagnostic: {script_collection.wct_diagnostic.value}",
                recoverable=True,
                exception_type="WctDiagnostic",
            ),
        )
    md.author_bundle_files = getattr(archive, "author_bundle_files", ())
    external_report = validate_external_names(archive, load_context.external_names)
    md.external_listfile = external_report if load_context.external_names else None

    candidates = list(collect_object_candidates(archive, wts, prefix="war3map", md=md))
    if archive.has_file("war3campaign.wts") or any(
        archive.has_file("war3campaign." + ext) for ext in OBJECT_EXTS
    ):
        cwts = {}
        if archive.has_file("war3campaign.wts"):
            parsed_cwts = read_component(
                md,
                "wts",
                "war3campaign.wts",
                lambda: _parse_campaign_wts(archive),
            )
            cwts = parsed_cwts or {}
        candidates.extend(
            collect_object_candidates(archive, cwts, prefix="war3campaign", md=md),
        )
    base_objects = merge_client_base_objects(
        BASE_OBJECTS, load_context.client_base_objects
    )
    populate_object_pipeline_from_context(md, candidates, base_objects, load_context)

    md.scripts.update(script_collection.texts)
    script_sources = analysis_script_texts(md)
    for _source, text in script_sources:
        _add_script_refs(md, text, shared_index)

    _add_w3i(md, archive, wts)
    _add_w3f(md, archive, wts)
    _add_preplaced(md, archive)
    from .map_extras import (
        add_game_configs,
        add_import_summary,
        add_preview_icons,
        add_trigger_summary,
        add_world_metadata,
    )

    add_world_metadata(md, archive, wts)
    add_game_configs(md, archive)
    add_trigger_summary(md, archive, load_context)
    add_preview_icons(md, archive)
    add_import_summary(md, archive)

    if script_sources:
        from .script_scan import scan_script_features

        features: list[str] = []
        for _source, text in script_sources:
            source_features, _ = scan_script_features(text)
            for feature in source_features:
                if feature not in features:
                    features.append(feature)
        md.script_features = features

    try:
        build_reference_graph(md)
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - optional reference analysis cannot abort extraction.
        md.ref_low_coverage = True
        record_component_failure(
            md,
            "reference-graph",
            "objects/scripts/preplaced",
            exc,
            stage="analyze",
        )

    md.item_relations = build_item_relation_index(md)

    md.all_files = list_archive_files(archive, external_names=external_report.confirmed)

    if _depth == 0 and path.lower().endswith(".w3n"):
        inner_maps = _campaign_inner_maps(archive, md.all_files, md.w3f)
        load_campaign_children(
            md,
            archive,
            inner_maps,
            _depth,
            load_context,
            _load_map_impl,
            max_children=_MAX_CAMPAIGN_CHILDREN,
            max_retained_bytes=_MAX_CAMPAIGN_CHILD_BYTES,
            max_read_bytes=_MAX_CAMPAIGN_READ_BYTES,
        )

    return md


def _root_archive_source(
    path: str,
    context: MapLoadContext,
) -> PathArchiveSource | SupplementedPathArchiveSource:
    if context.author_bundle_path is None and context.compat_bundle_path is None:
        return PathArchiveSource(path)
    return SupplementedPathArchiveSource(
        path,
        context.author_bundle_path,
        context.compat_bundle_path,
    )


def _campaign_inner_maps(archive: MapArchiveReader, known_names=(), w3f=None):
    """从战役里找出内含的地图文件名。优先 listfile，其次扫常见名。"""
    declared = tuple(entry.path for entry in w3f.maps) if w3f is not None else ()
    candidates = declared + tuple(known_names) + tuple(archive.list_files())
    found = list(campaign_inner_maps(w3f, candidates))
    if found:
        return found
    for i in range(1, 30):
        for pattern in (f"Map{i}.w3x", f"Map{i:02d}.w3x", f"Chapter{i}.w3x"):
            if archive.has_file(pattern):
                found.append(pattern)
    return found


def _parse_campaign_wts(archive: MapArchiveReader) -> dict[int, str]:
    data = archive.read_file("war3campaign.wts")
    return validate_wts_component(data, parse_wts(data))

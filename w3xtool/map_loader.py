"""Map archive lifecycle and recursive extraction orchestration."""
from __future__ import annotations

import os
import struct
from dataclasses import replace
from typing import Final

from .archive_source import BytesArchiveSource, PathArchiveSource
from .base_objects import BASE_OBJECTS
from .campaign_budget import CampaignByteBudget, record_campaign_budget_issue
from .campaign_sources import campaign_inner_maps
from .client_object_data import merge_client_base_objects
from .external_listfile import validate_external_names
from .extraction_diagnostics import (
    DiagnosticSeverity,
    ExtractionDiagnostic,
    read_component,
    record_component_failure,
    record_component_parse_issue,
    record_diagnostic,
)
from .load_context import MapLoadContext
from .map_archive_reader import DeclaredSizeArchive, MapArchiveReader
from .map_components import (
    _add_preplaced,
    _add_script_refs,
    _add_w3f,
    _add_w3i,
    _map_name,
)
from .map_data import MapData
from .mpq import MPQArchive
from .mpq_files import list_archive_files
from .object_candidates import OBJECT_EXTS, collect_object_candidates
from .object_pipeline import populate_object_pipeline
from .references import build_reference_graph
from .script_sources import analysis_script_texts, collect_readable_scripts
from .wts import parse_wts, validate_wts_component

_MAX_CAMPAIGN_CHILDREN: Final = 256
_MAX_CAMPAIGN_CHILD_BYTES: Final = 512 * 1024 * 1024
_MAX_CAMPAIGN_READ_BYTES: Final = 512 * 1024 * 1024
_CAMPAIGN_CHILD_ERRORS: Final = (KeyError, OSError, ValueError, IndexError, struct.error)


def load_map(
    path: str,
    _depth: int = 0,
    shared_index: dict | None = None,
    load_context: MapLoadContext | None = None,
) -> MapData:
    path = os.fspath(path)
    if load_context is None:
        load_context = MapLoadContext()
    from .author_plaintext_bundle import (
        PlaintextOverlayArchive,
        load_author_plaintext_bundle,
    )

    bundle = None
    if _depth == 0 and load_context.author_bundle_path is not None:
        bundle = load_author_plaintext_bundle(load_context.author_bundle_path, path)
    try:
        base_archive = MPQArchive(path)
    except (OSError, ValueError):
        if bundle is None:
            raise
        base_archive = None
    archive: MapArchiveReader = (
        PlaintextOverlayArchive(path, bundle, base_archive)
        if bundle is not None
        else base_archive
    )
    if archive is None:
        raise FileNotFoundError(path)
    try:
        return _load_map_impl(archive, path, _depth, shared_index, load_context)
    finally:
        archive.close()


def _load_map_impl(
    archive: MapArchiveReader,
    path: str,
    _depth: int,
    shared_index: dict | None,
    load_context: MapLoadContext,
) -> MapData:
    md = MapData(path=path, name=_map_name(archive), archive_source=PathArchiveSource(path))
    script_collection = collect_readable_scripts(archive, md=md)
    wts = {}
    if script_collection.wts_raw is not None:
        parsed_wts = read_component(
            md,
            "wts",
            "war3map.wts",
            lambda: validate_wts_component(
                script_collection.wts_raw,
                parse_wts(script_collection.wts_raw),
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
    base_objects = merge_client_base_objects(BASE_OBJECTS, load_context.client_base_objects)
    populate_object_pipeline(md, candidates, base_objects)

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
            md, "reference-graph", "objects/scripts/preplaced", exc, stage="analyze",
        )

    md.all_files = list_archive_files(archive, external_names=external_report.confirmed)

    if _depth == 0 and path.lower().endswith(".w3n"):
        inner_maps = _campaign_inner_maps(archive, md.all_files, md.w3f)
        if len(inner_maps) > _MAX_CAMPAIGN_CHILDREN:
            record_component_parse_issue(
                md,
                "campaign-child",
                path,
                f"campaign child count {len(inner_maps)} exceeds {_MAX_CAMPAIGN_CHILDREN}",
                stage="enumerate",
            )
        budget = CampaignByteBudget(_MAX_CAMPAIGN_CHILD_BYTES, _MAX_CAMPAIGN_READ_BYTES)
        for inner in inner_maps[:_MAX_CAMPAIGN_CHILDREN]:
            source = None
            try:
                remaining_bytes = budget.remaining
                declared_size = None
                if isinstance(archive, DeclaredSizeArchive):
                    declared_size = archive.declared_file_size(inner)
                reserved_bytes = budget.reserve_read(declared_size)
                if reserved_bytes is None:
                    record_campaign_budget_issue(md, inner)
                    continue
                data = read_component(
                    md,
                    "campaign-child",
                    inner,
                    lambda child_name=inner: archive.read_file(child_name),
                    stage="read",
                )
                if data is None:
                    continue
                budget.reconcile_read(reserved_bytes, len(data))
                if len(data) > remaining_bytes:
                    record_campaign_budget_issue(md, inner)
                    continue
                source = BytesArchiveSource(inner, data)
                child_context = replace(load_context, author_bundle_path=None)
                with source.open() as child_archive:
                    sub = _load_map_impl(
                        child_archive,
                        inner,
                        _depth + 1,
                        md.obj_index,
                        child_context,
                    )
                sub.archive_source = source
                sub.name = inner
                sub.path = inner
                md.sub_maps.append(sub)
                budget.charge_retained(len(data))
            except _CAMPAIGN_CHILD_ERRORS as exc:
                if source is not None:
                    source.close()
                record_diagnostic(
                    md,
                    ExtractionDiagnostic(
                        component="campaign-child",
                        source=inner,
                        stage="open/parse",
                        severity=DiagnosticSeverity.WARNING,
                        message=f"{type(exc).__name__}: {exc}".rstrip(),
                        recoverable=True,
                        exception_type=type(exc).__name__,
                    ),
                )
                continue

    return md


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

"""Map archive lifecycle and recursive extraction orchestration."""
from __future__ import annotations

import os
from dataclasses import replace

from .archive_source import BytesArchiveSource, PathArchiveSource
from .base_objects import BASE_OBJECTS
from .campaign_sources import campaign_inner_maps
from .client_object_data import merge_client_base_objects
from .extraction_diagnostics import (
    DiagnosticSeverity,
    ExtractionDiagnostic,
    record_diagnostic,
)
from .external_listfile import validate_external_names
from .load_context import MapLoadContext
from .map_archive_reader import MapArchiveReader
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
from .wts import parse_wts


def load_map(
    path: str,
    _depth: int = 0,
    shared_index: dict | None = None,
    load_context: MapLoadContext | None = None,
) -> MapData:
    path = os.fspath(path)
    if load_context is None:
        load_context = MapLoadContext()
    from .author_plaintext_bundle import PlaintextOverlayArchive, load_author_plaintext_bundle

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
    script_collection = collect_readable_scripts(archive)
    wts = {}
    if script_collection.wts_raw is not None:
        try:
            wts = parse_wts(script_collection.wts_raw)
        except (UnicodeError, ValueError):
            wts = {}

    md = MapData(path=path, name=_map_name(archive), archive_source=PathArchiveSource(path))
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
            ),
        )
    md.author_bundle_files = getattr(archive, "author_bundle_files", ())
    external_report = validate_external_names(archive, load_context.external_names)
    md.external_listfile = external_report if load_context.external_names else None

    candidates = list(collect_object_candidates(archive, wts, prefix="war3map"))
    if archive.has_file("war3campaign.wts") or any(
        archive.has_file("war3campaign." + ext) for ext in OBJECT_EXTS
    ):
        cwts = {}
        if archive.has_file("war3campaign.wts"):
            try:
                cwts = parse_wts(archive.read_file("war3campaign.wts"))
            except (KeyError, OSError, UnicodeError, ValueError):
                cwts = {}
        candidates.extend(collect_object_candidates(archive, cwts, prefix="war3campaign"))
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
    except Exception:  # noqa: BROAD_EXCEPT_OK - optional reference analysis cannot abort extraction.
        md.ref_low_coverage = True

    md.all_files = list_archive_files(archive, external_names=external_report.confirmed)

    if _depth == 0 and path.lower().endswith(".w3n"):
        for inner in _campaign_inner_maps(archive, md.all_files, md.w3f):
            source = None
            try:
                data = archive.read_file(inner)
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
            except Exception:  # noqa: BROAD_EXCEPT_OK - one corrupt campaign child must not hide siblings.
                if source is not None:
                    source.close()
                continue

    return md


def _campaign_inner_maps(archive: MapArchiveReader, known_names=(), w3f=None):
    """从战役里找出内含的地图文件名。优先 listfile，其次扫常见名。"""
    candidates = tuple(known_names) + tuple(archive.list_files())
    found = list(campaign_inner_maps(w3f, candidates))
    if found:
        return found
    for i in range(1, 30):
        for pattern in (f"Map{i}.w3x", f"Map{i:02d}.w3x", f"Chapter{i}.w3x"):
            if archive.has_file(pattern):
                found.append(pattern)
    return found

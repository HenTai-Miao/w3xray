"""Map archive lifecycle and recursive extraction orchestration."""
from __future__ import annotations

import os
import tempfile
from dataclasses import replace

from .archive_source import BytesArchiveSource, PathArchiveSource
from .external_listfile import validate_external_names
from .load_context import MapLoadContext
from .map_archive_reader import MapArchiveReader
from .map_components import (
    _add_preplaced,
    _add_script_refs,
    _add_w3f,
    _add_w3i,
    _add_wct,
    _best_script_text,
    _map_name,
)
from .map_data import MapData
from .mpq import MPQArchive
from .mpq_files import list_archive_files
from .object_candidates import OBJECT_EXTS, collect_object_candidates
from .object_pipeline import populate_object_pipeline
from .references import build_reference_graph
from .wts import parse_wts

SCRIPT_FILES = ["war3map.j", "war3map.lua", "war3map.wts", "war3map.wtg", "war3map.wct"]


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
    wts = {}
    if archive.has_file("war3map.wts"):
        try:
            wts = parse_wts(archive.read_file("war3map.wts"))
        except Exception:
            wts = {}

    md = MapData(path=path, name=_map_name(archive), archive_source=PathArchiveSource(path))
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
            except Exception:
                cwts = {}
        candidates.extend(collect_object_candidates(archive, cwts, prefix="war3campaign"))
    populate_object_pipeline(md, candidates)

    for fn in SCRIPT_FILES:
        if archive.has_file(fn):
            try:
                md.scripts[fn] = archive.read_file(fn).decode("utf-8", "replace")
            except Exception:
                pass

    script_text = _best_script_text(md.scripts)
    if script_text:
        _add_script_refs(md, script_text, shared_index)

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
    _add_wct(md, archive)

    script_text = _best_script_text(md.scripts)
    if script_text:
        try:
            from .script_scan import scan_script_features

            md.script_features, _ = scan_script_features(script_text)
        except Exception:
            md.script_features = []

    try:
        build_reference_graph(md)
    except Exception:
        pass

    md.all_files = list_archive_files(archive, external_names=external_report.confirmed)

    if _depth == 0 and path.lower().endswith(".w3n"):
        for inner in _campaign_inner_maps(archive, md.all_files):
            tmp = None
            try:
                data = archive.read_file(inner)
                fd, tmp = tempfile.mkstemp(suffix=".w3x", prefix="_w3n_")
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                child_context = replace(load_context, author_bundle_path=None)
                sub = load_map(tmp, _depth + 1, shared_index=md.obj_index, load_context=child_context)
                sub.archive_source = BytesArchiveSource(inner, data)
                sub.name = inner
                sub.path = inner
                md.sub_maps.append(sub)
            except Exception:
                pass
            finally:
                if tmp:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

    return md


def _campaign_inner_maps(archive: MapArchiveReader, known_names=()):
    """从战役里找出内含的地图文件名。优先 listfile，其次扫常见名。"""
    found = []
    candidates = tuple(known_names) + tuple(archive.list_files())
    seen = set()
    for name in candidates:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        if name.lower().endswith((".w3x", ".w3m")):
            found.append(name)
    if found:
        return found
    for i in range(1, 30):
        for pattern in (f"Map{i}.w3x", f"Map{i:02d}.w3x", f"Chapter{i}.w3x"):
            if archive.has_file(pattern):
                found.append(pattern)
    return found

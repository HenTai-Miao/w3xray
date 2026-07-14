"""Public compatibility facade for map extraction and script analysis."""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from types import ModuleType
from typing import TYPE_CHECKING

from . import map_loader
from .archive_export import (
    _export_all_impl as _export_all_impl,
    _export_recovered_named_files as _export_recovered_named_files,
    _imported_names as _imported_names,
    _safe_export_path as _safe_export_path,
    export_all_files as export_all_files,
    export_loaded_map_files as export_loaded_map_files,
    tmp_extract_dir as tmp_extract_dir,
)
from .map_archive_reader import MapArchiveReader
from .map_components import (
    _add_preplaced as _add_preplaced,
    _add_script_refs as _add_script_refs,
    _add_w3f as _add_w3f,
    _add_w3i as _add_w3i,
    _add_wct as _add_wct,
    _best_script_text as _best_script_text,
    _map_name as _map_name,
)
from .map_data import GameObject, MapData
from .map_loader import (
    _campaign_inner_maps as _campaign_inner_maps,
    _load_map_impl as _load_map_impl,
    load_map as load_map,
)
from .object_candidates import collect_binary_object_candidates
from .object_pipeline import add_base_objects as _pipeline_add_base_objects
from .object_pipeline import merge_object_candidates
from .script_sources import (
    ScriptCollection as ScriptCollection,
    analysis_script_texts,
    collect_readable_scripts,
)
from .wts import map_wts_table, parse_wts, resolve

MPQArchive = map_loader.MPQArchive

if TYPE_CHECKING:
    from .script_scan import ChatCommand, Recipe


class _ApiModule(ModuleType):
    """Keep the historical MPQArchive monkeypatch seam routed to the loader."""

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name == "MPQArchive":
            map_loader.MPQArchive = value


sys.modules[__name__].__class__ = _ApiModule


def _expand_codes(value: str, names: Mapping[str, str]) -> str:
    """把逗号分隔的码列表逐项还原成「名字(码)」；非列表或未知码原样保留。"""
    if not isinstance(value, str) or "," not in value:
        return value
    parts = []
    for tok in value.split(","):
        token = tok.strip()
        name = names.get(token)
        parts.append(f"{name}({token})" if name else token)
    return ", ".join(parts)


def _standard_script_text(archive: MapArchiveReader) -> str | None:
    collection = collect_readable_scripts(archive)
    md = MapData(path=archive.path, name=archive.path, scripts=dict(collection.texts))
    return _joined_analysis_script_text(md)


def _build_objects(
    archive: MapArchiveReader,
    ext: str,
    wts: dict[int, str],
    prefix: str = "war3map",
) -> list[GameObject]:
    """Compatibility wrapper for callers that still request one binary object file."""
    candidates = collect_binary_object_candidates(archive, wts, ext, prefix=prefix)
    return list(merge_object_candidates(candidates, {}))


def _add_base_objects(md: MapData) -> None:
    """Compatibility wrapper for explicit named-base population."""
    _pipeline_add_base_objects(md)


def quick_map_name(path: str) -> str:
    """只读文件头快速取地图名(不解析整个 MPQ)，用于目录列表。"""
    try:
        with open(path, "rb") as f:
            head = f.read(2048)
        if head[:4] == b"HM3W":
            end = head.index(b"\x00", 8)
            name = head[8:end].decode("utf-8", "replace").strip()
            if name and not name.startswith("TRIGSTR"):
                return name
    except (OSError, ValueError):
        return os.path.basename(path)
    return os.path.basename(path)


def _read_script(archive: MapArchiveReader) -> str | None:
    return _standard_script_text(archive)


def _map_wts(md: MapData) -> dict[int, str]:
    """Return the retained WTS table, with published text as a legacy fallback."""
    return map_wts_table(md)


def commands_from_map(md: MapData) -> list[ChatCommand]:
    """从已解析的 MapData 扫描隐藏聊天指令（复用 md.scripts，不重开 MPQ）。"""
    from .script_scan import scan_chat_commands

    commands = []
    seen = set()
    for _source, text in analysis_script_texts(md):
        for command in scan_chat_commands(text):
            key = (command.command, command.exact)
            if key in seen:
                continue
            seen.add(key)
            commands.append(command)
    commands.sort(key=lambda command: (
        len(command.command) == 0,
        not command.command.startswith("-"),
        command.command,
    ))
    wts = _map_wts(md)
    if wts:
        for command in commands:
            if command.hint:
                command.hint = str(resolve(command.hint, wts))
    return commands


def recipes_from_map(md: MapData) -> list[Recipe]:
    """从已解析的 MapData 识别物品合成配方（复用 md.scripts，不重开 MPQ）。"""
    from .script_scan import scan_recipes as scan_recipes_from_text

    recipes = []
    seen = set()
    for source, text in analysis_script_texts(md):
        for recipe in scan_recipes_from_text(text, source=source):
            key = (
                recipe.source,
                recipe.line,
                tuple(sorted(recipe.ingredients)),
                recipe.result,
            )
            if key in seen:
                continue
            seen.add(key)
            recipes.append(recipe)
    return recipes


def scan_commands(path: str) -> list[ChatCommand]:
    """扫描地图脚本里的隐藏聊天指令（独立入口，会自行打开 MPQ）。"""
    with MPQArchive(path) as archive:
        collection = collect_readable_scripts(archive)
    ui_strings = None
    if collection.wts_raw is not None:
        try:
            ui_strings = parse_wts(collection.wts_raw)
        except (UnicodeError, ValueError):
            ui_strings = {}
    md = MapData(
        path=path,
        name=path,
        scripts=dict(collection.texts),
        ui_strings=ui_strings,
    )
    return commands_from_map(md)


def scan_recipes(path: str) -> list[Recipe]:
    """识别地图脚本里的物品合成配方（独立入口，会自行打开 MPQ）。"""
    with MPQArchive(path) as archive:
        collection = collect_readable_scripts(archive)
    md = MapData(path=path, name=path, scripts=dict(collection.texts))
    return recipes_from_map(md)


def _joined_analysis_script_text(md: MapData) -> str | None:
    texts = analysis_script_texts(md)
    if not texts:
        return None
    return "\n\n".join(f"// ===== {name} =====\n{text}" for name, text in texts)

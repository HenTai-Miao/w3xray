"""Public compatibility facade for map extraction and script analysis."""
from __future__ import annotations

import os
import sys
from types import ModuleType

from . import map_loader
from .archive_export import (
    _export_all_impl as _export_all_impl,
    _export_recovered_named_files as _export_recovered_named_files,
    _imported_names as _imported_names,
    _safe_export_path as _safe_export_path,
    export_all_files as export_all_files,
    tmp_extract_dir as tmp_extract_dir,
)
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
from .map_data import GameObject, MapData
from .map_loader import _campaign_inner_maps, _load_map_impl, load_map
from .object_candidates import collect_binary_object_candidates
from .object_pipeline import add_base_objects as _pipeline_add_base_objects
from .object_pipeline import merge_object_candidates
from .wts import parse_wts, resolve

MPQArchive = map_loader.MPQArchive


class _ApiModule(ModuleType):
    """Keep the historical MPQArchive monkeypatch seam routed to the loader."""

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name == "MPQArchive":
            map_loader.MPQArchive = value


sys.modules[__name__].__class__ = _ApiModule


def _expand_codes(value: str, names: dict) -> str:
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
    for fn in ("war3map.j", "war3map.lua"):
        if archive.has_file(fn):
            try:
                text = archive.read_file(fn).decode("utf-8", "replace")
            except Exception:
                continue
            if text.strip("\x00\r\n\t "):
                return text
    return None


def _build_objects(
    archive: MapArchiveReader,
    ext: str,
    wts: dict,
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
    except Exception:
        pass
    return os.path.basename(path)


def _read_script(archive: MapArchiveReader):
    return _standard_script_text(archive)


def _map_wts(md: MapData) -> dict:
    """从 md.scripts 里的 war3map.wts 文本解析字符串表（commands 提示还原用）。"""
    raw = md.scripts.get("war3map.wts")
    if not raw:
        return {}
    try:
        return parse_wts(raw.encode("utf-8", "replace"))
    except Exception:
        return {}


def commands_from_map(md: MapData) -> list:
    """从已解析的 MapData 扫描隐藏聊天指令（复用 md.scripts，不重开 MPQ）。"""
    from .script_scan import scan_chat_commands

    text = _best_script_text(md.scripts)
    if not text:
        return []
    commands = scan_chat_commands(text)
    wts = _map_wts(md)
    if wts:
        for command in commands:
            if command.hint:
                command.hint = str(resolve(command.hint, wts))
    return commands


def recipes_from_map(md: MapData) -> list:
    """从已解析的 MapData 识别物品合成配方（复用 md.scripts，不重开 MPQ）。"""
    from .script_scan import scan_recipes as scan_recipes_from_text

    text = _best_script_text(md.scripts)
    return scan_recipes_from_text(text) if text else []


def scan_commands(path: str) -> list:
    """扫描地图脚本里的隐藏聊天指令（独立入口，会自行打开 MPQ）。"""
    from .script_scan import scan_chat_commands

    with MPQArchive(path) as archive:
        text = _read_script(archive)
    return scan_chat_commands(text) if text else []


def scan_recipes(path: str) -> list:
    """识别地图脚本里的物品合成配方（独立入口，会自行打开 MPQ）。"""
    from .script_scan import scan_recipes as scan_recipes_from_text

    with MPQArchive(path) as archive:
        text = _read_script(archive)
    return scan_recipes_from_text(text) if text else []

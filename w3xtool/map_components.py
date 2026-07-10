"""Cohesive map-load parsing helpers shared by the loader and API facade."""
from __future__ import annotations

import os
from collections.abc import Mapping

from .map_archive_reader import MapArchiveReader
from .map_data import GameObject, MapData
from .script_sources import WCT_TEXT_NAME, collect_readable_scripts

try:
    from .base_names import BASE_NAMES
except ImportError:
    BASE_NAMES = {}


def _best_script_text(scripts: Mapping[str, str]) -> str | None:
    """Return the first non-empty primary script for legacy callers."""
    for name in ("war3map.j", "war3map.lua"):
        text = scripts.get(name)
        if text and text.strip("\x00\r\n\t "):
            return text
    return None


def _add_script_refs(md: MapData, script_text: str, shared_index: dict | None = None):
    """把脚本里引用、但对象数据缺失的 物品/单位 代码补进分类。

    战役子地图：若该码在战役共享对象(shared_index)里有定义，用其真名/分类/字段
    （标〔战役共享〕）；否则只能按脚本引用补一个光秃秃的码。
    """
    from .script_scan import scan_object_refs

    refs = scan_object_refs(script_text)
    for cat, codes in refs.items():
        for code in sorted(codes):
            if code in md.obj_index:
                continue
            shared = shared_index.get(code) if shared_index else None
            if shared is not None:
                obj = GameObject(
                    category=shared.category, ext="campaign",
                    obj_id=code, base_id=shared.base_id, name=shared.name,
                    is_custom=shared.is_custom,
                    fields=[("来源", "战役共享对象")] + list(shared.fields),
                    search_text=shared.search_text, icon=shared.icon)
                md.objects.setdefault(shared.category, []).append(obj)
            else:
                name = BASE_NAMES.get(code) or code
                obj = GameObject(
                    category=cat, ext="script", obj_id=code, base_id=code,
                    name=name, is_custom=(code not in BASE_NAMES),
                    fields=[("来源", "脚本引用（无对象数据，可能缺属性/名称）")],
                    search_text=f"{code} {name}")
                md.objects.setdefault(cat, []).append(obj)
            md.obj_index[code] = obj


def _map_name(archive: MapArchiveReader) -> str:
    # 从 HM3W 头读地图名
    try:
        data = archive._data
        if data[:4] == b"HM3W":
            end = data.index(b"\x00", 8)
            return data[8:end].decode("utf-8", "replace")
    except (AttributeError, TypeError, ValueError):
        return os.path.basename(archive.path)
    return os.path.basename(archive.path)


def _add_w3i(md: MapData, archive: MapArchiveReader, wts: dict):
    """解析 war3map.w3i 地图信息并存入 md.w3i；地图名优先取 w3i（比 HM3W 头权威）。

    HM3W 头里的名常是占位/旧名甚至 TRIGSTR；编辑器里设的真实名在 w3i（经 wts 还原）。
    """
    if not archive.has_file("war3map.w3i"):
        return
    try:
        from .w3i import parse_w3i

        info = parse_w3i(archive.read_file("war3map.w3i"), wts)
    except (KeyError, OSError, ValueError):
        return
    if info is None:
        return
    md.w3i = info
    nm = (info.map_name or "").strip()
    if nm and not nm.startswith("TRIGSTR_"):
        md.name = nm


def _add_w3f(md: MapData, archive: MapArchiveReader, wts: dict):
    """解析战役信息 war3campaign.w3f（仅 .w3n 顶层有）并存入 md.w3f。"""
    if not archive.has_file("war3campaign.w3f"):
        return
    try:
        from .w3i import parse_w3f

        info = parse_w3f(archive.read_file("war3campaign.w3f"), wts)
    except (KeyError, OSError, ValueError):
        return
    if info is not None:
        md.w3f = info
        nm = (info.name or "").strip()
        if nm and not nm.startswith("TRIGSTR_") and (not md.name or md.name == os.path.basename(md.path)):
            md.name = nm


def _add_wct(md: MapData, archive: MapArchiveReader):
    """Compatibility wrapper that publishes only collector-decoded WCT text."""
    readable = collect_readable_scripts(archive).texts.get(WCT_TEXT_NAME)
    if readable is not None:
        md.scripts[WCT_TEXT_NAME] = readable


def _add_preplaced(md: MapData, archive: MapArchiveReader):
    """解析预放置实例：war3map.doo（装饰物/可破坏物）+ war3mapUnits.doo（单位）并并入 md。

    对象定义（w3u/w3t…）只说"有哪些"，.doo 才说"摆在哪、归谁、初始多少血/金"。
    单条记录损坏不拖垮整图（doo.parse_* 内部已逐条容错）。
    """
    from .doo import parse_doodads, parse_units

    if archive.has_file("war3map.doo"):
        try:
            md.doodads = parse_doodads(archive.read_file("war3map.doo"))
        except (KeyError, OSError, ValueError):
            md.doodads = []
    if archive.has_file("war3mapUnits.doo"):
        try:
            md.units = parse_units(archive.read_file("war3mapUnits.doo"))
        except (KeyError, OSError, ValueError):
            md.units = []

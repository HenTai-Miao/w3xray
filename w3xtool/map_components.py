"""Cohesive map-load parsing helpers shared by the loader and API facade."""

from __future__ import annotations

import os
import struct
from collections.abc import Mapping

from .base_names import BASE_NAMES
from .extraction_diagnostics import (
    read_component,
    record_component_parse_issue,
    require_component_result,
)
from .map_archive_reader import MapArchiveReader
from .map_data import GameObject, MapData
from .script_sources import WCT_TEXT_NAME, collect_readable_scripts


def _best_script_text(scripts: Mapping[str, str]) -> str | None:
    """Return the first non-empty primary script for legacy callers."""
    for name in ("war3map.j", "war3map.lua"):
        text = scripts.get(name)
        if text and text.strip("\x00\r\n\t "):
            return text
    return None


def _add_script_refs(
    md: MapData,
    script_text: str,
    shared_index: Mapping[tuple[str, str], GameObject] | None = None,
) -> None:
    """把脚本里引用、但对象数据缺失的 物品/单位 代码补进分类。

    战役子地图：若该码在战役共享对象(shared_index)里有定义，用其真名/分类/字段
    （标〔战役共享〕）；否则只能按脚本引用补一个光秃秃的码。
    """
    from .script_scan import scan_object_refs

    refs = scan_object_refs(script_text)
    for cat, codes in refs.items():
        for code in sorted(codes):
            if (cat, code) in md.obj_identity_index:
                continue
            shared = shared_index.get((cat, code)) if shared_index else None
            if shared is not None:
                obj = GameObject(
                    category=shared.category,
                    ext="campaign",
                    obj_id=code,
                    base_id=shared.base_id,
                    name=shared.name,
                    is_custom=shared.is_custom,
                    fields=[("来源", "战役共享对象")] + list(shared.fields),
                    search_text=shared.search_text,
                    icon=shared.icon,
                )
                md.objects.setdefault(shared.category, []).append(obj)
            else:
                name = BASE_NAMES.get(code) or code
                obj = GameObject(
                    category=cat,
                    ext="script",
                    obj_id=code,
                    base_id=code,
                    name=name,
                    is_custom=(code not in BASE_NAMES),
                    fields=[("来源", "脚本引用（无对象数据，可能缺属性/名称）")],
                    search_text=f"{code} {name}",
                )
                md.objects.setdefault(cat, []).append(obj)
            _ = md.obj_index.setdefault(code, obj)
            md.obj_identity_index[(obj.category, code)] = obj


def _map_name(archive: MapArchiveReader) -> str:
    # 从 HM3W 头读地图名
    try:
        data = archive._data
        if data[:4] == b"HM3W":
            end = data.find(b"\x00", 8)
            if end >= 0:
                return data[8:end].decode("utf-8", "replace")
    except AttributeError, TypeError, ValueError:
        return os.path.basename(archive.path)
    return os.path.basename(archive.path)


def _add_w3i(md: MapData, archive: MapArchiveReader, wts: dict[int, str]) -> None:
    """解析 war3map.w3i 地图信息并存入 md.w3i；地图名优先取 w3i（比 HM3W 头权威）。

    HM3W 头里的名常是占位/旧名甚至 TRIGSTR；编辑器里设的真实名在 w3i（经 wts 还原）。
    """
    if not archive.has_file("war3map.w3i"):
        return
    from .w3i import parse_w3i

    info = read_component(
        md,
        "w3i",
        "war3map.w3i",
        lambda: require_component_result(
            parse_w3i(archive.read_file("war3map.w3i"), wts),
            "war3map.w3i",
        ),
    )
    if info is None:
        return
    md.w3i = info
    if info.parse_issue:
        record_component_parse_issue(md, "w3i", "war3map.w3i", info.parse_issue)
    nm = (info.map_name or "").strip()
    if nm and not nm.startswith("TRIGSTR_"):
        md.name = nm


def _add_w3f(md: MapData, archive: MapArchiveReader, wts: dict[int, str]) -> None:
    """解析战役信息 war3campaign.w3f（仅 .w3n 顶层有）并存入 md.w3f。"""
    if not archive.has_file("war3campaign.w3f"):
        return
    from .w3i import parse_w3f

    info = read_component(
        md,
        "w3f",
        "war3campaign.w3f",
        lambda: require_component_result(
            parse_w3f(archive.read_file("war3campaign.w3f"), wts),
            "war3campaign.w3f",
        ),
    )
    if info is None:
        return
    md.w3f = info
    if info.diagnostic is not None:
        record_component_parse_issue(
            md,
            "w3f",
            "war3campaign.w3f",
            f"W3F parse diagnostic: {info.diagnostic.value}",
        )
    nm = (info.name or "").strip()
    if (
        nm
        and not nm.startswith("TRIGSTR_")
        and (not md.name or md.name == os.path.basename(md.path))
    ):
        md.name = nm


def _add_wct(md: MapData, archive: MapArchiveReader) -> None:
    """Compatibility wrapper that publishes only collector-decoded WCT text."""
    readable = collect_readable_scripts(archive, md=md).texts.get(WCT_TEXT_NAME)
    if readable is not None:
        md.scripts[WCT_TEXT_NAME] = readable


def _add_preplaced(md: MapData, archive: MapArchiveReader) -> None:
    """解析预放置实例：war3map.doo（装饰物/可破坏物）+ war3mapUnits.doo（单位）并并入 md。

    对象定义（w3u/w3t…）只说"有哪些"，.doo 才说"摆在哪、归谁、初始多少血/金"。
    单条记录损坏不拖垮整图（doo.parse_* 内部已逐条容错）。
    """
    from .doo import parse_doodads, parse_units

    if archive.has_file("war3map.doo"):
        payload = read_component(
            md,
            "preplaced",
            "war3map.doo",
            lambda: archive.read_file("war3map.doo"),
            stage="read",
        )
        if payload is not None:
            md.doodads = parse_doodads(payload)
            issue = _placement_parse_issue(payload, len(md.doodads))
            if issue is not None:
                record_component_parse_issue(md, "preplaced", "war3map.doo", issue)
    if archive.has_file("war3mapUnits.doo"):
        payload = read_component(
            md,
            "preplaced",
            "war3mapUnits.doo",
            lambda: archive.read_file("war3mapUnits.doo"),
            stage="read",
        )
        if payload is not None:
            md.units = parse_units(payload)
            issue = _placement_parse_issue(payload, len(md.units))
            if issue is not None:
                record_component_parse_issue(md, "preplaced", "war3mapUnits.doo", issue)


def _placement_parse_issue(data: bytes, recovered: int) -> str | None:
    if len(data) < 16 or data[:4] != b"W3do":
        return "invalid placement header"
    version, subversion = struct.unpack_from("<ii", data, 4)
    if (version, subversion) not in {(7, 9), (8, 11)}:
        return f"unsupported placement version: {version}/{subversion}"
    declared = struct.unpack_from("<i", data, 12)[0]
    if declared < 0 or declared > len(data):
        return f"invalid placement count: {declared}"
    if recovered != declared:
        return f"recovered {recovered} of {declared} placements"
    return None

"""高层 API：把一张地图/战役解析成便于搜索、展示、导出的结构。"""
from __future__ import annotations

import os
import tempfile
from dataclasses import replace

from .load_context import MapLoadContext
from .external_listfile import validate_external_names
from .archive_export import (
    _export_all_impl as _export_all_impl,
    _export_recovered_named_files as _export_recovered_named_files,
    _imported_names as _imported_names,
    _safe_export_path as _safe_export_path,
    export_all_files as export_all_files,
    tmp_extract_dir as tmp_extract_dir,
)
from .mpq import MPQArchive
from .archive_source import BytesArchiveSource, PathArchiveSource
from .map_data import GameObject, MapData
from .map_archive_reader import MapArchiveReader
from .mpq_files import list_archive_files
from .wts import parse_wts, resolve
from .references import build_reference_graph
from .object_candidates import OBJECT_EXTS, collect_binary_object_candidates, collect_object_candidates
from .object_pipeline import add_base_objects as _pipeline_add_base_objects
from .object_pipeline import merge_object_candidates, populate_object_pipeline
try:
    from .base_names import BASE_NAMES
except Exception:
    BASE_NAMES = {}
SCRIPT_FILES = ["war3map.j", "war3map.lua", "war3map.wts", "war3map.wtg", "war3map.wct"]


def _expand_codes(value: str, names: dict) -> str:
    """把逗号分隔的码列表逐项还原成「名字(码)」；非列表或未知码原样保留。

    用于 abilityList/unitList 等多值字段——展示时比一串 4cc 可读。
    """
    if not isinstance(value, str) or "," not in value:
        return value
    parts = []
    for tok in value.split(","):
        t = tok.strip()
        nm = names.get(t)
        parts.append(f"{nm}({t})" if nm else t)
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


def _best_script_text(scripts: dict):
    for name in ("war3map.j", "war3map.lua"):
        text = scripts.get(name)
        if text and text.strip("\x00\r\n\t "):
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


def _add_script_refs(md: "MapData", script_text: str, shared_index: dict | None = None):
    """把脚本里引用、但对象数据缺失的 物品/单位 代码补进分类。

    战役子地图：若该码在战役共享对象(shared_index)里有定义，用其真名/分类/字段
    （标〔战役共享〕）；否则只能按脚本引用补一个光秃秃的码。
    """
    from .script_scan import scan_object_refs
    refs = scan_object_refs(script_text)
    for cat, codes in refs.items():
        for code in sorted(codes):
            if code in md.obj_index:
                continue                      # 对象数据已有，跳过
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
    except Exception:
        pass
    return os.path.basename(archive.path)


def quick_map_name(path: str) -> str:
    """只读文件头快速取地图名(不解析整个 MPQ)，用于目录列表。"""
    try:
        with open(path, "rb") as f:
            head = f.read(2048)
        if head[:4] == b"HM3W":
            end = head.index(b"\x00", 8)
            nm = head[8:end].decode("utf-8", "replace").strip()
            if nm and not nm.startswith("TRIGSTR"):
                return nm
    except Exception:
        pass
    return os.path.basename(path)


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
        archive.close()                      # 释放句柄/mmap/临时副本，别等 GC


def _load_map_impl(archive: MapArchiveReader, path: str, _depth: int,
                   shared_index: dict | None, load_context: MapLoadContext) -> MapData:
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

    # 战役级共享对象使用独立 WTS 表；所有来源随后只物化一次。
    if archive.has_file("war3campaign.wts") or any(
            archive.has_file("war3campaign." + e) for e in OBJECT_EXTS):
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

    # 脚本兜底：把脚本引用、但对象数据里没有的 物品/单位 代码补进来
    # （战役子地图会回退查战役共享对象 shared_index 取真名）
    script_text = _best_script_text(md.scripts)
    if script_text:
        _add_script_refs(md, script_text, shared_index)

    # 地图信息（名/作者/玩家/脚本语言…）；地图名优先取 w3i（比 HM3W 头权威）
    _add_w3i(md, archive, wts)
    # 战役信息（仅 .w3n 顶层有 war3campaign.w3f）
    _add_w3f(md, archive, wts)
    # 预放置实例（单位/装饰物"摆在哪、归谁"）—— 对象定义之外的另一维信息
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
    # war3map.wct 自定义脚本解码成可读文本并入脚本（原始 wct 是二进制）
    _add_wct(md, archive)

    # 脚本特征：检测脚本用到的暴雪 BJ 机制（对战开局/随机刷怪/中立建筑…），供地图信息展示。
    script_text = _best_script_text(md.scripts)
    if script_text:
        try:
            from .script_scan import scan_script_features
            md.script_features, _ = scan_script_features(script_text)
        except Exception:
            md.script_features = []

    # 对象引用分析（只读）：正向/反向引用 + 孤立自定义对象。失败优雅降级，不拖垮加载。
    try:
        build_reference_graph(md)
    except Exception:
        pass

    md.all_files = list_archive_files(archive, external_names=external_report.confirmed)

    # 战役 .w3n：递归解析内含的 .w3x（防止无限递归）
    if _depth == 0 and path.lower().endswith(".w3n"):
        for inner in _campaign_inner_maps(archive, md.all_files):
            tmp = None
            try:
                data = archive.read_file(inner)
                # 唯一临时名(防同名子图互相覆盖)，统一放系统临时目录；用完即删。
                fd, tmp = tempfile.mkstemp(suffix=".w3x", prefix="_w3n_")
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                # 把战役共享对象索引传给子地图，让它的脚本引用能取到真名
                child_context = replace(load_context, author_bundle_path=None)
                sub = load_map(tmp, _depth + 1, shared_index=md.obj_index, load_context=child_context)
                sub.archive_source = BytesArchiveSource(inner, data)
                sub.name = inner
                sub.path = inner             # 临时文件即将删除，保留战役成员的逻辑名
                md.sub_maps.append(sub)
            except Exception:
                pass
            finally:
                if tmp:                      # 子图内容已读入内存，删掉临时副本
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
    for n in candidates:
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        if n.lower().endswith((".w3x", ".w3m")):
            found.append(n)
    if found:
        return found
    # 退路：尝试常见命名
    for i in range(1, 30):
        for pat in (f"Map{i}.w3x", f"Map{i:02d}.w3x", f"Chapter{i}.w3x"):
            if archive.has_file(pat):
                found.append(pat)
    return found


def _read_script(archive: MapArchiveReader):
    return _standard_script_text(archive)


def _map_wts(md: "MapData") -> dict:
    """从 md.scripts 里的 war3map.wts 文本解析字符串表（commands 提示还原用）。"""
    raw = md.scripts.get("war3map.wts")
    if not raw:
        return {}
    try:
        return parse_wts(raw.encode("utf-8", "replace"))
    except Exception:
        return {}


def commands_from_map(md: "MapData") -> list:
    """从已解析的 MapData 扫描隐藏聊天指令（复用 md.scripts，不重开 MPQ）。"""
    from .script_scan import scan_chat_commands
    txt = _best_script_text(md.scripts)
    if not txt:
        return []
    cmds = scan_chat_commands(txt)
    wts = _map_wts(md)                       # 把提示里的 TRIGSTR_n 还原成真文本
    if wts:
        for c in cmds:
            if c.hint:
                c.hint = str(resolve(c.hint, wts))
    return cmds


def recipes_from_map(md: "MapData") -> list:
    """从已解析的 MapData 识别物品合成配方（复用 md.scripts，不重开 MPQ）。"""
    from .script_scan import scan_recipes as _sr
    txt = _best_script_text(md.scripts)
    return _sr(txt) if txt else []


def scan_commands(path: str) -> list:
    """扫描地图脚本里的隐藏聊天指令（独立入口，会自行打开 MPQ）。"""
    from .script_scan import scan_chat_commands
    with MPQArchive(path) as archive:
        txt = _read_script(archive)
    return scan_chat_commands(txt) if txt else []


def scan_recipes(path: str) -> list:
    """识别地图脚本里的物品合成配方（独立入口，会自行打开 MPQ）。"""
    from .script_scan import scan_recipes as _sr
    with MPQArchive(path) as archive:
        txt = _read_script(archive)
    return _sr(txt) if txt else []


def _add_w3i(md: "MapData", archive: MapArchiveReader, wts: dict):
    """解析 war3map.w3i 地图信息并存入 md.w3i；地图名优先取 w3i（比 HM3W 头权威）。

    HM3W 头里的名常是占位/旧名甚至 TRIGSTR；编辑器里设的真实名在 w3i（经 wts 还原）。
    """
    if not archive.has_file("war3map.w3i"):
        return
    try:
        from .w3i import parse_w3i
        info = parse_w3i(archive.read_file("war3map.w3i"), wts)
    except Exception:
        return
    if info is None:
        return
    md.w3i = info
    nm = (info.map_name or "").strip()
    if nm and not nm.startswith("TRIGSTR_"):
        md.name = nm


def _add_w3f(md: "MapData", archive: MapArchiveReader, wts: dict):
    """解析战役信息 war3campaign.w3f（仅 .w3n 顶层有）并存入 md.w3f。"""
    if not archive.has_file("war3campaign.w3f"):
        return
    try:
        from .w3i import parse_w3f
        info = parse_w3f(archive.read_file("war3campaign.w3f"), wts)
    except Exception:
        return
    if info is not None:
        md.w3f = info
        nm = (info.name or "").strip()
        if nm and not nm.startswith("TRIGSTR_") and (not md.name or md.name == os.path.basename(md.path)):
            md.name = nm


def _add_wct(md: "MapData", archive: MapArchiveReader):
    """解析 war3map.wct 自定义脚本，把解码后的可读 JASS/Lua 文本并入 md.scripts。

    wct 是二进制（原样导出是乱码）；解出全局块 + 各触发器自定义代码块拼成一份带分节
    注释的文本，文件名带 .txt 便于「导出脚本」直接看。解析失败/无 wct 时静默跳过。
    """
    if not archive.has_file("war3map.wct"):
        return
    try:
        from .wct import parse_wct
        w = parse_wct(archive.read_file("war3map.wct"))
    except Exception:
        return
    parts = []
    if w.custom_code.strip():
        parts.append("// ===== 全局自定义脚本 =====\n" + w.custom_code)
    for i, t in enumerate(w.triggers):
        if t.strip():
            parts.append(f"// ===== 触发器自定义脚本 #{i + 1} =====\n" + t)
    if parts:
        md.scripts["war3map.wct(自定义代码).txt"] = "\n\n".join(parts)


def _add_preplaced(md: "MapData", archive: MapArchiveReader):
    """解析预放置实例：war3map.doo（装饰物/可破坏物）+ war3mapUnits.doo（单位）并并入 md。

    对象定义（w3u/w3t…）只说"有哪些"，.doo 才说"摆在哪、归谁、初始多少血/金"。
    单条记录损坏不拖垮整图（doo.parse_* 内部已逐条容错）。
    """
    from .doo import parse_doodads, parse_units
    if archive.has_file("war3map.doo"):
        try:
            md.doodads = parse_doodads(archive.read_file("war3map.doo"))
        except Exception:
            md.doodads = []
    if archive.has_file("war3mapUnits.doo"):
        try:
            md.units = parse_units(archive.read_file("war3mapUnits.doo"))
        except Exception:
            md.units = []

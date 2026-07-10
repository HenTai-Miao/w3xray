"""高层 API：把一张地图/战役解析成便于搜索、展示、导出的结构。"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field, replace

from .load_context import MapLoadContext
from .external_listfile import ExternalListfileReport, validate_external_names
from .archive_export import (
    _export_all_impl as _export_all_impl,
    _export_recovered_named_files as _export_recovered_named_files,
    _imported_names as _imported_names,
    _safe_export_path as _safe_export_path,
    export_all_files as export_all_files,
    tmp_extract_dir as tmp_extract_dir,
)
from .mpq import MPQArchive, FLAG_EXISTS
from .map_archive_reader import MapArchiveReader
from .mpq_files import list_archive_files
from .w3obj import parse_object_data, EXT_CATEGORY
from .wts import parse_wts, resolve
from .fields import NAME_FIELD, label_for, is_concat_type, field_type
from .references import extract_refs_by_type, extract_refs_by_column, build_reference_graph
from .textobj import _sub_westring
try:
    from .base_names import BASE_NAMES
except Exception:
    BASE_NAMES = {}
try:
    from .base_objects import BASE_OBJECTS
except Exception:
    BASE_OBJECTS = {}

OBJECT_EXTS = ["w3u", "w3t", "w3a", "w3q", "w3b", "w3d", "w3h"]
ICON_FIELD = {"w3u": "uico", "w3t": "iico", "w3a": "aart", "w3q": "gar1",
              "w3h": "fart", "w3b": "bgsc", "w3d": "dfil"}
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


def _fmt_value(v) -> str:
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return f"{v:.4g}"
    return str(v)


@dataclass
class GameObject:
    category: str
    ext: str
    obj_id: str
    base_id: str
    name: str
    is_custom: bool
    fields: list = field(default_factory=list)   # [(label, value_str)]
    search_text: str = ""
    icon: str = ""                                # 图标路径(BLP)
    ref_fields: list = field(default_factory=list)  # 引用字段 [(field_id/列名, [被引用码…])]

    @property
    def decimal(self):
        """4 字符码对应的十进制整数(big-endian)，用于和 box 一致显示。"""
        b = self.obj_id.encode("latin-1", "ignore")[:4].ljust(4, b"\x00")
        return int.from_bytes(b, "big")


@dataclass
class MapData:
    path: str
    name: str
    objects: dict = field(default_factory=dict)   # category -> [GameObject]
    scripts: dict = field(default_factory=dict)   # filename -> text
    all_files: list = field(default_factory=list)
    external_listfile: ExternalListfileReport | None = None
    sub_maps: list = field(default_factory=list)   # 战役内含的子地图 MapData
    obj_index: dict = field(default_factory=dict)  # type_id -> GameObject
    doodads: list = field(default_factory=list)    # 预放置装饰物/可破坏物 (doo.Doodad)
    units: list = field(default_factory=list)       # 预放置单位 (doo.Unit)
    regions: list = field(default_factory=list)     # war3map.w3r 区域
    cameras: list = field(default_factory=list)     # war3map.w3c 镜头
    sounds: list = field(default_factory=list)      # war3map.w3s 声音
    game_configs: list = field(default_factory=list)  # .wgc 游戏/AI 测试配置
    trigger_summary: object = None                  # war3map.wtg 触发器树摘要
    preview_icons: object = None                    # war3map.mmp 小地图标记摘要
    import_summary: object = None                   # 地图/战役导入资源摘要
    w3i: object = None                              # 地图信息 (w3i.W3iInfo)，无则 None
    w3f: object = None                              # 战役信息 (w3i.W3fInfo)，仅 .w3n 有
    references: dict = field(default_factory=dict)  # 正向引用 obj_id -> [(字段标签, [(码, 名字|None)])]
    referenced_by: dict = field(default_factory=dict)  # 反向 码 -> [(引用者ID, 引用者名, 字段标签)]
    orphans: list = field(default_factory=list)     # 孤立的自定义对象 [GameObject]
    ref_low_coverage: bool = False                  # 引用覆盖低(如 SLK 优化图)，孤立判定不可全信
    script_features: list = field(default_factory=list)  # 脚本用到的暴雪BJ机制(对战开局/随机刷怪…)
    author_bundle_files: tuple[str, ...] = ()

    def category_counts(self):
        return {c: len(v) for c, v in self.objects.items()}


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


def _build_objects(archive: MapArchiveReader, ext: str, wts: dict, prefix: str = "war3map"):
    fn = prefix + "." + ext
    if not archive.has_file(fn):
        return []
    try:
        raw = archive.read_file(fn)
        parsed = parse_object_data(raw, ext)
    except Exception as e:
        # 单个对象文件解析失败时不拖垮整张图；但打条告警(cli/控制台可见)，
        # 避免"解析失败"被完全静默成"没有该类对象"。
        import sys
        print(f"[w3xray] 警告：解析 {fn} 失败（{type(e).__name__}: {e}），"
              f"该类对象可能不全", file=sys.stderr)
        return []
    category = EXT_CATEGORY.get(ext, ext)
    name_field = NAME_FIELD.get(ext)
    result = []
    for o in parsed:
        obj_id = o.new_id if (o.is_custom and o.new_id.strip("\x00")) else o.old_id
        # 解析名称
        name = ""
        for m in o.mods:
            if m.field_id == name_field and m.level in (0, 1):
                name = _sub_westring(str(resolve(m.value, wts)))
                if name:
                    break
        if not name:
            # 回退到游戏原版名（基础码优先，再用新码）
            name = BASE_NAMES.get(o.old_id) or BASE_NAMES.get(obj_id) or obj_id
        # 字段明细
        fields_list = []
        icon = ""
        icon_field = ICON_FIELD.get(ext)
        for m in o.mods:
            label = label_for(m.field_id)
            val = resolve(m.value, wts)
            if isinstance(val, str) and "WESTRING_" in val:
                val = _sub_westring(val)
            if m.field_id == icon_field and isinstance(val, str) and not icon:
                icon = val
            if m.level:
                label = f"{label} (等级{m.level})"
            # 多值字段（技能/单位列表等）：把逗号分隔的码逐项还原成「原版名(码)」更易读
            if isinstance(val, str) and is_concat_type(m.field_id):
                val = _expand_codes(val, BASE_NAMES)
            fields_list.append((label, _fmt_value(val)))
        # 原样保留大小写：模糊搜索不分大小写、引号精准搜索区分大小写（在 fuzzy_score 内处理）
        search_text = " ".join([obj_id, o.old_id, name] +
                               [str(v) for _, v in fields_list])
        # 引用字段（类型驱动）：趁此处还有原始 field_id/value，抽出指向别的对象的码
        ref_fields = extract_refs_by_type(o.mods, field_type)
        result.append(GameObject(
            category=category, ext=ext, obj_id=obj_id, base_id=o.old_id,
            name=str(name), is_custom=o.is_custom, fields=fields_list,
            search_text=search_text, icon=icon, ref_fields=ref_fields))
    return result


def _add_text_objects(md: "MapData", archive: MapArchiveReader):
    """扫描地图里的"文本格式对象档"(INI: [码] Name=.. Tip=.. Ubertip=..)，解析为带名对象。

    很多地图把 单位/物品/技能/科技 存成文本档(文件名不固定)，靠内容识别。
    """
    from .textobj import looks_like_text_object, parse_text_objects, classify, clean_text

    DISPLAY = [("Name", "名称"), ("Tip", "提示"), ("Ubertip", "说明"),
               ("Hotkey", "快捷键"), ("Art", "图标"), ("Description", "描述"),
               ("EditorSuffix", "后缀"), ("Cooldown", "冷却"), ("Cost", "消耗"),
               ("manaN", "魔法"), ("Name1", "名称"), ("Tip1", "提示")]
    added_total = 0
    covered = set()
    for block in archive.block_table:
        if not (block.flags & FLAG_EXISTS):
            continue
        head = archive.peek_block(block, 16)
        if not head or not looks_like_text_object(head):
            continue
        data = archive.decompress_block(block)
        if not data or b"Name=" not in data[:8000]:
            continue
        try:
            text = data.decode("utf-8", "replace")
        except Exception:
            continue
        objs = parse_text_objects(text)
        objs = [(c, f) for c, f in objs if f]
        if len(objs) < 8:
            continue
        field_keys = set()
        for _c, _f in objs:
            field_keys.update(_f.keys())
        cat = classify([c for c, _ in objs], field_keys)
        bucket = md.objects.setdefault(cat, [])
        cat_added = 0
        for code, fields in objs:
            if code in md.obj_index:
                continue
            name = clean_text(fields.get("Name", "")) or BASE_NAMES.get(code) or code
            name = name.split("\n")[0][:60]
            disp = []
            for key, label in DISPLAY:
                if key in fields and fields[key]:
                    disp.append((label, clean_text(fields[key])))
            # 其余字段也带上
            shown = {k for k, _ in DISPLAY}
            for k, v in fields.items():
                if k not in shown and v:
                    disp.append((k, clean_text(v)))
            search = (code + " " + name + " " +
                      clean_text(fields.get("Ubertip", "")) + " " +
                      clean_text(fields.get("Tip", "")))
            icon = (fields.get("Art") or fields.get("art") or "").split(",")[0].strip()
            # 引用字段（列名驱动）：文本对象键是 SLK 列名，按分类的引用列表抽码
            ref_fields = extract_refs_by_column(fields, cat)
            obj = GameObject(category=cat, ext="txt", obj_id=code, base_id=code,
                             name=name, is_custom=True, fields=disp,
                             search_text=search, icon=icon, ref_fields=ref_fields)
            bucket.append(obj)
            md.obj_index[code] = obj
            added_total += 1
            cat_added += 1
        if cat_added >= 8:
            covered.add(cat)
    return covered


_BINARY_EXTS = {"w3u", "w3t", "w3a", "w3q", "w3b", "w3d", "w3h"}


def _add_slk_objects(md: "MapData", archive: MapArchiveReader, wts: dict):
    """解析地图内嵌的 *Data.slk 对象数据（SLK 优化图），并入/增补对象表。

    SLK 优化图把对象数据转成 SLK；二进制/文本路径都读不到，故技能等只剩名字、丢了字段与
    引用（如 AHwe 召唤的单位）。这里按分类解出 SLK，逐对象：码已存在(且非二进制权威)则增补
    字段/引用，否则新建。引用复用 references.extract_refs_by_column（按 SLK 列名抽）。
    """
    from .slk_objects import (parse_category_objects, slk_col_label,
                              has_any_slk_objects, is_noise_col)
    if not has_any_slk_objects(archive):
        return
    for category in ("单位", "物品", "技能", "科技", "可破坏物", "增益", "装饰物"):
        objs = parse_category_objects(archive, category)
        if not objs:
            continue
        bucket = md.objects.setdefault(category, [])
        for code, row in objs.items():
            ref_fields = extract_refs_by_column(row, category)
            existing = md.obj_index.get(code)
            if existing is not None:
                if existing.ext in _BINARY_EXTS:
                    continue                     # 二进制对象权威，不动
                # 增补：把 SLK 字段里现有标签没有的并进来（跳过编辑器噪声列），引用按需补
                have = {lab for lab, _ in existing.fields}
                added = False
                for col, val in row.items():
                    if is_noise_col(col, category):
                        continue
                    lab = slk_col_label(col)
                    if lab not in have and str(val) != "":
                        existing.fields.append((lab, str(val)))
                        added = True
                if added and ("数据来源", "war3map *Data.slk") not in existing.fields:
                    existing.fields.append(("数据来源", "war3map *Data.slk"))
                if ref_fields:
                    # 并入 SLK 引用并去重（不再"已有就整体丢弃"），保留已有引用
                    have_refs = {(k, tuple(cs)) for k, cs in existing.ref_fields}
                    for k, cs in ref_fields:
                        if (k, tuple(cs)) not in have_refs:
                            existing.ref_fields.append((k, cs))
                            have_refs.add((k, tuple(cs)))
                continue
            # 新建：SLK 独有的对象
            name = ""
            raw_name = row.get("Name") or row.get("Name1") or ""
            if raw_name:
                name = _sub_westring(str(resolve(raw_name, wts)))
            if not name:
                name = BASE_NAMES.get(code) or code
            icon = (row.get("Art") or row.get("art") or row.get("ico") or "").split(",")[0].strip()
            fields_list = [(slk_col_label(c), str(v)) for c, v in row.items()
                           if str(v) != "" and not is_noise_col(c, category)]
            search = code + " " + str(name) + " " + " ".join(str(v) for _, v in fields_list)
            obj = GameObject(category=category, ext="slk", obj_id=code, base_id=code,
                             name=str(name), is_custom=True, fields=fields_list,
                             search_text=search, icon=icon, ref_fields=ref_fields)
            bucket.append(obj)
            md.obj_index[code] = obj


def _add_base_objects(md: "MapData"):
    """把游戏原版对象(默认字段)中地图未包含的补进来，标记原版。

    无显示名的原版对象（游戏数据表里有、但 *Strings/*Func 没给名字的系统内部对象）
    跳过——它们对用户是光秃秃的码，加进来只是噪声。
    """
    for code, (cat, fields) in BASE_OBJECTS.items():
        if code in md.obj_index:
            continue
        name = BASE_NAMES.get(code)
        if not name:                  # 无名的系统内部对象，不加（避免每张图都冒光秃秃码）
            continue
        search = (code + " " + name + " " +
                  " ".join(str(v) for _, v in fields))
        obj = GameObject(category=cat, ext="base", obj_id=code, base_id=code,
                         name=str(name), is_custom=False,
                         fields=[(str(k), str(v)) for k, v in fields],
                         search_text=search)
        md.objects.setdefault(cat, []).append(obj)
        md.obj_index[code] = obj


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


def _add_binary_objects(md: "MapData", archive: MapArchiveReader, wts: dict,
                        text_cats: set, prefix: str):
    """解析 <prefix>.w3u/w3t/... 二进制对象档并并入 md；文本档已覆盖的类别跳过。"""
    for ext in OBJECT_EXTS:
        cat = EXT_CATEGORY.get(ext, ext)
        if cat in text_cats:
            continue
        objs = _build_objects(archive, ext, wts, prefix=prefix)
        if not objs:
            continue
        md.objects.setdefault(cat, [])
        md.objects[cat].extend(objs)
        for o in objs:
            md.obj_index.setdefault(o.obj_id, o)
            md.obj_index.setdefault(o.base_id, o)


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

    md = MapData(path=path, name=_map_name(archive))
    md.author_bundle_files = getattr(archive, "author_bundle_files", ())
    external_report = validate_external_names(archive, load_context.external_names)
    md.external_listfile = external_report if load_context.external_names else None

    # 先解析文本格式对象档（带名、权威）。返回它覆盖的类别
    text_cats = set()
    try:
        text_cats = _add_text_objects(md, archive) or set()
    except Exception:
        text_cats = set()

    # 再解析二进制对象数据；某类别已被文本档(带名)覆盖则跳过(避免无名残留污染)
    _add_binary_objects(md, archive, wts, text_cats, "war3map")

    # 战役级共享对象：顶层 war3campaign.* + war3campaign.wts（普通图无此文件，自动跳过）
    if archive.has_file("war3campaign.wts") or any(
            archive.has_file("war3campaign." + e) for e in OBJECT_EXTS):
        cwts = {}
        if archive.has_file("war3campaign.wts"):
            try:
                cwts = parse_wts(archive.read_file("war3campaign.wts"))
            except Exception:
                cwts = {}
        _add_binary_objects(md, archive, cwts, text_cats, "war3campaign")

    # 内嵌 SLK 对象数据（SLK 优化图）：补字段与引用；失败优雅降级。
    try:
        _add_slk_objects(md, archive, wts)
    except Exception:
        pass

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

    # 基础对象库：仅在地图本身解析出内容时才补原版对象
    own = sum(len(v) for v in md.objects.values())
    if own > 0:
        _add_base_objects(md)

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
                sub.name = inner
                sub.path = inner             # 临时文件即将删除，path 改用逻辑名(子图不可再 open)
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

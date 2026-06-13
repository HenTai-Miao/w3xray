"""高层 API：把一张地图/战役解析成便于搜索、展示、导出的结构。"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field

from .mpq import MPQArchive, FLAG_EXISTS
from .w3obj import parse_object_data, EXT_CATEGORY
from .wts import parse_wts, resolve
from .fields import NAME_FIELD, label_for, is_concat_type
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
KNOWN_EXPORT_FILES = [
    "war3map.w3u", "war3map.w3t", "war3map.w3a", "war3map.w3q",
    "war3map.w3b", "war3map.w3d", "war3map.w3h", "war3map.j",
    "war3map.lua", "war3map.wts", "war3map.w3i", "war3map.w3e",
    "war3mapUnits.doo", "war3map.doo", "war3map.shd", "war3map.mmp",
    "war3mapMap.blp", "war3map.wpm", "(listfile)",
]


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
    sub_maps: list = field(default_factory=list)   # 战役内含的子地图 MapData
    obj_index: dict = field(default_factory=dict)  # type_id -> GameObject
    doodads: list = field(default_factory=list)    # 预放置装饰物/可破坏物 (doo.Doodad)
    units: list = field(default_factory=list)       # 预放置单位 (doo.Unit)
    w3i: object = None                              # 地图信息 (w3i.W3iInfo)，无则 None
    w3f: object = None                              # 战役信息 (w3i.W3fInfo)，仅 .w3n 有

    def category_counts(self):
        return {c: len(v) for c, v in self.objects.items()}


def _standard_script_text(archive: MPQArchive) -> str | None:
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


def _build_objects(archive: MPQArchive, ext: str, wts: dict, prefix: str = "war3map"):
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
        result.append(GameObject(
            category=category, ext=ext, obj_id=obj_id, base_id=o.old_id,
            name=str(name), is_custom=o.is_custom, fields=fields_list,
            search_text=search_text, icon=icon))
    return result


def _add_text_objects(md: "MapData", archive: MPQArchive):
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
            obj = GameObject(category=cat, ext="txt", obj_id=code, base_id=code,
                             name=name, is_custom=True, fields=disp,
                             search_text=search, icon=icon)
            bucket.append(obj)
            md.obj_index[code] = obj
            added_total += 1
            cat_added += 1
        if cat_added >= 8:
            covered.add(cat)
    return covered


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


def _map_name(archive: MPQArchive) -> str:
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


def _add_binary_objects(md: "MapData", archive: MPQArchive, wts: dict,
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


def load_map(path: str, _depth: int = 0, shared_index: dict | None = None) -> MapData:
    path = os.fspath(path)
    archive = MPQArchive(path)
    try:
        return _load_map_impl(archive, path, _depth, shared_index)
    finally:
        archive.close()                      # 释放句柄/mmap/临时副本，别等 GC


def _load_map_impl(archive: MPQArchive, path: str, _depth: int,
                   shared_index: dict | None) -> MapData:
    wts = {}
    if archive.has_file("war3map.wts"):
        try:
            wts = parse_wts(archive.read_file("war3map.wts"))
        except Exception:
            wts = {}

    md = MapData(path=path, name=_map_name(archive))

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
    # war3map.wct 自定义脚本解码成可读文本并入脚本（原始 wct 是二进制）
    _add_wct(md, archive)

    md.all_files = archive.list_files()

    # 战役 .w3n：递归解析内含的 .w3x（防止无限递归）
    if _depth == 0 and path.lower().endswith(".w3n"):
        for inner in _campaign_inner_maps(archive):
            tmp = None
            try:
                data = archive.read_file(inner)
                # 唯一临时名(防同名子图互相覆盖)，统一放系统临时目录；用完即删。
                fd, tmp = tempfile.mkstemp(suffix=".w3x", prefix="_w3n_")
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                # 把战役共享对象索引传给子地图，让它的脚本引用能取到真名
                sub = load_map(tmp, _depth + 1, shared_index=md.obj_index)
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


def _campaign_inner_maps(archive: MPQArchive):
    """从战役里找出内含的地图文件名。优先 listfile，其次扫常见名。"""
    found = []
    for n in archive.list_files():
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


def _read_script(archive: MPQArchive):
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


def _add_w3i(md: "MapData", archive: MPQArchive, wts: dict):
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


def _add_w3f(md: "MapData", archive: MPQArchive, wts: dict):
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


def _add_wct(md: "MapData", archive: MPQArchive):
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


def _add_preplaced(md: "MapData", archive: MPQArchive):
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


def _imported_names(archive: MPQArchive) -> list:
    """从 war3map.imp 解析导入文件名，供导出时补全 (listfile) 缺失的自定义文件。

    优化/保护图常删掉 (listfile)，但 war3map.imp 仍记着每个导入文件的路径。
    imp 里多为相对名（不带 war3mapImported\\ 前缀），直查不到时补前缀再试（与 w3x2lni 一致）。
    """
    if not archive.has_file("war3map.imp"):
        return []
    try:
        from .imp import parse_imp
        raw = archive.read_file("war3map.imp")
    except Exception:
        return []
    names = []
    for name in parse_imp(raw):
        names.append(name)
        if not archive.has_file(name):
            names.append("war3mapImported\\" + name)
    return names


def _safe_export_path(out_dir: str, name: str):
    """把地图内部文件名安全地映射到 out_dir 下的路径。

    地图文件名来自不可信的 (listfile)，可能是绝对路径或含 ..\\，
    直接 os.path.join 会写到目录外（任意文件写入）。这里拒绝穿越/绝对路径，
    并用 commonpath 做兜底校验；安全时返回目标绝对路径，否则返回 None。
    """
    out_root = os.path.realpath(out_dir)
    norm = name.replace("\\", "/").strip("/")
    parts = [p for p in norm.split("/") if p and p != "."]
    if not parts:
        return None
    if any(p == ".." for p in parts):
        return None
    if ":" in parts[0]:                      # 盘符 / 绝对路径
        return None
    dest = os.path.realpath(os.path.join(out_root, *parts))
    if out_root != dest and os.path.commonpath([out_root, dest]) != out_root:
        return None
    return dest


def tmp_extract_dir(name: str, *sub: str, clean: bool = False) -> str:
    """提取产物的临时目录：%TEMP%/w3xtool提取/<安全名>/...（提取的都是临时文件）。

    clean=True 先清空该目录再重建：不同地图经文件名清洗后可能撞同一个 safe_name
    （如都叫"(unknown)"或重名），不清就会把上一张图的残留文件混进这次导出，
    导致打开的文件夹里有别的图的东西、且"已导出 N 个"计数把残留也算进去。
    """
    safe_name = "".join(c if c not in '\\/:*?"<>|' else "_" for c in (name or "map")).strip() or "map"
    root = os.path.join(tempfile.gettempdir(), "w3xtool提取", safe_name, *sub)
    if clean and os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)
    return root


def export_all_files(path: str, out_dir: str | None = None, _depth: int = 0) -> str:
    """把地图里能列出的文件全部解包到 out_dir（默认 TMP）；战役 .w3n 递归解出每张子图内部文件。

    返回实际导出的目录路径。
    """
    archive = MPQArchive(path)
    try:
        return _export_all_impl(archive, out_dir, _depth)
    finally:
        archive.close()


def _export_all_impl(archive: MPQArchive, out_dir: str | None, _depth: int) -> str:
    if out_dir is None:
        out_dir = tmp_extract_dir(_map_name(archive), clean=True)   # 顶层导出先清空，避免混入同名图残留
    os.makedirs(out_dir, exist_ok=True)
    names = set(archive.list_files())
    # 补充已知关键文件（listfile 常不全）
    names.update(KNOWN_EXPORT_FILES)
    # 再补 war3map.imp 里登记的导入文件（listfile 被删时这是唯一的自定义文件名来源）
    names.update(_imported_names(archive))
    sub_maps = []
    for n in sorted(names):
        if not archive.has_file(n):
            continue
        dest = _safe_export_path(out_dir, n)
        if dest is None:                     # 拒绝路径穿越/绝对路径
            continue
        try:
            data = archive.read_file(n)
        except Exception:
            continue
        os.makedirs(os.path.dirname(dest) or out_dir, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        if n.lower().endswith((".w3x", ".w3m")):
            sub_maps.append(n)

    # 战役：把每张子图内部文件也递归解出到 out_dir/<子图名>/（仅顶层递归一层）
    if _depth == 0:
        for n in sub_maps:
            inner_dir = _safe_export_path(out_dir, os.path.splitext(n)[0])
            if inner_dir is None:
                continue
            blob = os.path.join(out_dir, n.replace("\\", os.sep).replace("/", os.sep))
            if not os.path.exists(blob):
                continue
            try:
                export_all_files(blob, inner_dir, _depth + 1)
            except Exception:
                pass
    return out_dir

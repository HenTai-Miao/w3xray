"""Text exports for map/resource/config investigation workflows."""

from __future__ import annotations

from typing import Final

from .api import GameObject, MapData
from .map_identity import build_map_identity
from .object_id_summary import preplaced_code_counts
from .object_id_usage import build_object_id_usage, code_decimal
from .save_analysis import build_save_report

_FORMAT_DESCRIPTIONS: Final = {
    "war3map.w3i": ("地图信息", "地图名、作者、玩家、队伍、尺寸、脚本语言"),
    "war3campaign.w3f": ("战役信息", "战役名、作者、章节与难度"),
    "war3map.wts": ("字符串表", "TRIGSTR 文本映射，UI 文本和触发文本常在这里"),
    "war3map.wtg": ("触发器树", "GUI 触发器、变量、分类和触发器头"),
    "war3map.wct": ("自定义脚本", "触发编辑器中的自定义脚本文本块"),
    "war3map.j": ("JASS 脚本", "触发逻辑、读写存档、聊天指令、对象创建"),
    "war3map.lua": ("Lua 脚本", "Lua 触发逻辑、读写存档、对象引用"),
    "war3map.w3u": ("单位对象", "单位 ID、名称、模型、图标、技能列表"),
    "war3map.w3t": ("物品对象", "物品 ID、名称、图标、使用技能"),
    "war3map.w3a": ("技能对象", "技能 ID、提示文本、图标、召唤单位/增益"),
    "war3map.w3q": ("科技对象", "科技 ID、图标、研究需求"),
    "war3map.w3b": ("可破坏物对象", "可破坏物 ID、模型、贴图"),
    "war3map.w3d": ("装饰物对象", "装饰物 ID、模型、路径"),
    "war3map.w3h": ("增益对象", "Buff ID、图标、提示文本"),
    "war3mapunits.doo": ("预放置单位", "地图上摆放的单位、物品栏、掉落、坐标"),
    "war3map.doo": ("预放置装饰/可破坏物", "地图装饰物、可破坏物、掉落和坐标"),
    "war3map.imp": ("导入资源表", "导入素材原始路径和自定义路径"),
    "war3campaign.imp": ("战役导入资源表", "战役顶层导入素材原始路径和自定义路径"),
    "war3map.w3r": ("区域", "区域 ID、名称、范围"),
    "war3map.w3c": ("镜头", "摄像机名称、位置、角度"),
    "war3map.w3s": ("声音", "声音名、路径、音乐/音效标志"),
    "war3map.mmp": ("小地图标记", "出生点、金矿、中立建筑标记"),
    "war3map.w3e": ("地形", "地图尺寸、地表纹理、悬崖纹理"),
    "war3map.wpm": ("路径网格", "可通行、可建造、飞行路径数据"),
    "testconfig.wgc": ("游戏配置", "测试配置、玩家槽、速度、自定义 AI"),
}
_TEXT_CONFIG_EXTS: Final = {
    "json": ("文本配置", "工具配置、面板数据、外部化参数"),
    "plist": ("属性列表", "重制版/工具链文本配置"),
    "skin": ("界面皮肤", "自定义 UI 皮肤或主题配置"),
}
_AI_EXTS: Final = {"ai": ("AI脚本", "电脑玩家 AI 脚本路径与策略配置")}

_OBJECT_ORDER: Final = ("单位", "物品", "技能", "科技", "可破坏物", "装饰物", "增益")


def format_config_format_index(md: MapData) -> str:
    """Return a compact index of map config/data files found in the archive."""
    lines = ["配置/数据格式索引", "文件\t类型\t用途"]
    entries = config_format_entries(md)
    for name, title, detail in entries:
        lines.append(f"{name}\t{title}\t{detail}")
    if not entries:
        lines.append("（未发现已知配置/数据格式文件）")
    return "\n".join(lines) + "\n"


def config_format_entries(md: MapData) -> tuple[tuple[str, str, str], ...]:
    """Return known config/data files as ``(name, title, detail)`` rows."""
    rows: list[tuple[str, str, str]] = []
    for name in sorted(md.all_files, key=str.lower):
        info = _format_info(name.lower())
        if info is None:
            continue
        title, detail = info
        rows.append((name, title, detail))
    return tuple(rows)


def format_map_object_id_index(md: MapData) -> str:
    """Return a TSV index for map identity and all parsed object IDs."""
    object_lookup = _object_lookup(md)
    id_usage = build_object_id_usage(md)
    save_codes = set(build_save_report(md).object_codes)
    referenced_codes = set(md.referenced_by)
    preplaced_codes = _preplaced_codes(md)
    rows = ["类型\t分类\tID\t10进制\t名称\t来源\t使用情况\t详情"]
    rows.append("\t".join(("地图", md.name, md.path, "", "", "", "", "")))
    rows.extend(_map_summary_rows(md))
    for category, objects in _ordered_objects(md):
        for obj in objects:
            rows.append(_object_row(
                category,
                obj,
                id_usage.details_for(obj.obj_id),
                obj.obj_id in save_codes,
                obj.obj_id in referenced_codes,
                obj.obj_id in preplaced_codes,
            ))
    for code in sorted(code for code in id_usage.codes if code not in object_lookup):
        rows.append(_unknown_script_row(code, id_usage.details_for(code), code in save_codes))
    return "\n".join(rows) + "\n"


def _format_info(lowered: str) -> tuple[str, str] | None:
    exact = _FORMAT_DESCRIPTIONS.get(lowered)
    if exact is not None:
        return exact
    if lowered.endswith(".wgc"):
        return _FORMAT_DESCRIPTIONS["testconfig.wgc"]
    if lowered.endswith(".slk"):
        return ("SLK 表", "优化图对象数据、平衡常数、文本/字段表")
    ext = _extension(lowered)
    if ext in _TEXT_CONFIG_EXTS:
        return _TEXT_CONFIG_EXTS[ext]
    if ext in _AI_EXTS:
        return _AI_EXTS[ext]
    if lowered.endswith(".txt") and "triggerdata" in lowered:
        return ("触发器参数表", "GUI 触发器函数参数定义")
    return None


def _map_summary_rows(md: MapData) -> list[str]:
    counts = md.category_counts()
    object_count = sum(counts.values())
    rows = [
        _map_summary_row("内部文件数", str(len({name.lower() for name in md.all_files})), "内部文件清单"),
        _map_summary_row("脚本文件数", str(len(md.scripts)), "脚本"),
        _map_summary_row("对象总数", str(object_count), "对象表"),
    ]
    identity = build_map_identity(md.path)
    if identity.readable:
        rows.extend((
            _map_summary_row("文件字节", str(identity.size), "源文件"),
            _map_summary_row("CRC32", identity.crc32, "源文件"),
            _map_summary_row("SHA1", identity.sha1, "源文件"),
        ))
    rows.extend(_map_summary_row(f"{category}数量", str(count), "对象表") for category, count in counts.items())
    return rows


def _map_summary_row(label: str, value: str, source: str) -> str:
    return "\t".join(("地图", _tsv(label), _tsv(value), "", "", _tsv(source), "", ""))


def _ordered_objects(md: MapData):
    emitted = set()
    for category in _OBJECT_ORDER:
        if category in md.objects:
            emitted.add(category)
            yield category, md.objects[category]
    for category, objects in sorted(md.objects.items()):
        if category not in emitted:
            yield category, objects


def _object_row(
    category: str,
    obj: GameObject,
    script_details: tuple[str, ...],
    in_save_report: bool,
    referenced: bool,
    preplaced: bool,
) -> str:
    usages = _usage_labels(bool(script_details), in_save_report, referenced, preplaced)
    return "\t".join((
        "对象",
        _tsv(category),
        _tsv(obj.obj_id),
        str(obj.decimal),
        _tsv(obj.name),
        _tsv(obj.ext),
        _tsv(",".join(usages)),
        _tsv(",".join(script_details)),
    ))


def _unknown_script_row(code: str, details: tuple[str, ...], in_save_report: bool) -> str:
    usages = _usage_labels(True, in_save_report, False, False)
    detail = ",".join(details) + "；未在对象表中解析"
    return "\t".join((
        "脚本引用",
        "未知",
        _tsv(code),
        str(code_decimal(code)),
        "",
        _tsv(_source_names(details)),
        _tsv(",".join(usages)),
        _tsv(detail),
    ))


def _usage_labels(
    scripted: bool,
    in_save_report: bool,
    referenced: bool,
    preplaced: bool,
) -> tuple[str, ...]:
    labels: list[str] = []
    if scripted:
        labels.append("脚本引用")
    if in_save_report:
        labels.append("存档/ID线索")
    if referenced:
        labels.append("对象字段被引用")
    if preplaced:
        labels.append("预放置")
    if not labels:
        labels.append("对象表")
    return tuple(labels)


def _object_lookup(md: MapData) -> dict[str, GameObject]:
    lookup = {obj.obj_id: obj for objects in md.objects.values() for obj in objects}
    for code, obj in md.obj_index.items():
        if isinstance(code, str) and isinstance(obj, GameObject):
            lookup.setdefault(code, obj)
    return lookup


def _preplaced_codes(md: MapData) -> set[str]:
    return set(preplaced_code_counts(md))


def _source_names(details: tuple[str, ...]) -> str:
    return ",".join(sorted({detail.split(":", 1)[0] for detail in details}))


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _extension(path: str) -> str:
    if "." not in path:
        return ""
    return path.rsplit(".", 1)[-1]

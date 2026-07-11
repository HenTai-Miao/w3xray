"""解析地图内嵌的 *Data.slk 对象数据（SLK 优化图）。

「拖入无反应解决方法」类工具把对象数据转成 SLK 重打包；本工具原本只读二进制
.w3a/.w3u 与 INI 文本对象，读不了内嵌 SLK → 那类图的字段/引用读不全。本模块补上：
按分类找出 MPQ 里的 *Data.slk，用 slk.parse_slk 解出，多文件按对象码合并。

只负责"找文件 + 解析 + 合并"，返回 {对象码: {SLK列名: 值}}；统一对象候选管线负责
构建、取名和并入 MapData。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol

from .extraction_diagnostics import ComponentParseError, read_component, record_component_parse_issue
from .slk import parse_slk
from .war3_encoding import decode_warcraft_string

if TYPE_CHECKING:
    from .map_data import MapData


class SlkArchive(Protocol):
    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...

# 分类 → 该类的 SLK 文件（单位跨多文件，按对象码合并列）。
SLK_CATEGORY_FILES = {
    "技能": ["AbilityData.slk"],
    "物品": ["ItemData.slk"],
    "增益": ["AbilityBuffData.slk"],
    "可破坏物": ["DestructableData.slk"],
    "科技": ["UpgradeData.slk"],
    "装饰物": ["Doodads.slk"],
    "单位": ["UnitData.slk", "UnitBalance.slk", "UnitUI.slk",
             "UnitWeapons.slk", "UnitAbilities.slk"],
}

# SLK 文件在 MPQ 里可能裸放或在 Units\ / Doodads\ 下（不区分大小写）。
_PREFIXES = ["", "Units\\", "Doodads\\"]

# 常用 SLK 列名（无等级后缀）→ 中文标签。带等级后缀的列(Cast2/BuffID1…)交给 SLK_BASE_LABELS。
SLK_COL_LABELS = {
    "Name": "名称", "Tip": "提示", "Ubertip": "说明", "Hotkey": "快捷键",
    "Art": "图标", "art": "图标", "race": "种族", "levels": "等级数",
    "Cooldown": "冷却", "Requires": "依赖", "Name1": "名称",
    "HP": "生命", "hitPoints": "生命", "manaN": "魔法上限", "def": "护甲",
    "goldcost": "金币", "lumbercost": "木材", "Level": "等级", "ico": "图标",
}

# 带等级后缀的列：去掉末位数字后的"基名" → 中文标签（Cast2→施法间隔(等级2)）。
SLK_BASE_LABELS = {
    "Cast": "施法间隔", "Cool": "冷却", "Cost": "魔法消耗", "Dur": "持续时间",
    "HeroDur": "英雄持续", "Area": "作用范围", "Rng": "施法距离",
    "BuffID": "buff效果", "EfctID": "效果", "UnitID": "召唤/创建单位",
    "DataA": "数据A", "DataB": "数据B", "DataC": "数据C", "DataD": "数据D",
    "DataE": "数据E", "DataF": "数据F", "DataG": "数据G", "DataH": "数据H", "DataI": "数据I",
    "targs": "目标类型", "Requires": "依赖", "dmgplus": "攻击力加成",
}

# 编辑器噪声列（来自工具包 Config.ini [AlwaysEmpty]，按分类）+ 冗余 code。展示时跳过。
_ALWAYS_EMPTY = {
    "技能": "comments,version,useInEditor,hero,item,sort,race,InBeta",
    "物品": "comments,scriptname,version,InBeta",
    "增益": "comments,isEffect,version,useInEditor,sort,race,InBeta",
    "可破坏物": "comments,EditorSuffix,InBeta,version",
    "装饰物": "comment,InBeta,version",
    "科技": "comments,sort,version,InBeta",
    "单位": ("sort,comment,comments,InBeta,version,sortBalance,sort2,"
            "sortUI,inEditor,hiddenInEditor,sortWeap,sortAbil"),
}
SLK_NOISE_COLS = {cat: set(s.split(",")) | {"code"} for cat, s in _ALWAYS_EMPTY.items()}


_LEVEL_SUFFIX = re.compile(r"^(.*?)(\d+)$")    # 去掉整段末尾数字(支持多位等级，如 DataA10)


def slk_col_label(col: str) -> str:
    """SLK 列名 → 中文标签：精确表 → 等级后缀(去整段数字查基名+等级N) → 原样列名。"""
    if col in SLK_COL_LABELS:
        return SLK_COL_LABELS[col]
    m = _LEVEL_SUFFIX.match(col or "")
    if m and m.group(1) in SLK_BASE_LABELS:
        return f"{SLK_BASE_LABELS[m.group(1)]} (等级{m.group(2)})"
    return col


def is_noise_col(col: str, category: str) -> bool:
    """该列是否为编辑器噪声(按分类的 [AlwaysEmpty] + 冗余 code)，展示时应跳过。"""
    return col in SLK_NOISE_COLS.get(category, {"code"})


def _find_name(archive: SlkArchive, name: str) -> str | None:
    """按几种前缀/大小写在 MPQ 里找该 SLK 的实际内部名；只查存在性，不读内容。"""
    bases = tuple(dict.fromkeys((name, name.lower(), name.upper())))
    for pre in _PREFIXES:
        for b in bases:
            fn = pre + b
            if archive.has_file(fn):
                return fn
    return None


def _read_text(archive: SlkArchive, name: str, md: MapData | None = None) -> tuple[str, str] | None:
    """在 MPQ 里找并读出该 SLK 文本；找不到/解码失败返回 None。"""
    fn = _find_name(archive, name)
    if fn is None:
        return None
    if md is not None:
        text = read_component(
            md,
            "slk",
            fn,
            lambda: decode_warcraft_string(archive.read_file(fn)),
        )
        return (fn, text) if text is not None else None
    try:
        return fn, decode_warcraft_string(archive.read_file(fn))
    except (KeyError, OSError, UnicodeError, ValueError):
        return None


def _looks_like_code(key: str) -> bool:
    """对象码恒为 4 字符可见 ASCII；剔除表头/占位等非对象行键。"""
    return len(key) == 4 and all(0x20 <= ord(c) < 0x7F for c in key)


def parse_category_objects(
    archive: SlkArchive,
    category: str,
    *,
    md: MapData | None = None,
) -> dict[str, dict[str, str]]:
    """解析某分类的全部 SLK 文件，按对象码合并列，返回 {码: {列名: 值}}。

    单位类跨 UnitData/UnitBalance/UnitUI/UnitWeapons/UnitAbilities 合并同码行。
    某文件缺失/解析失败时跳过该文件（不拖垮整类）。
    """
    files = SLK_CATEGORY_FILES.get(category, [])
    merged: dict[str, dict[str, str]] = {}
    for fn in files:
        source_text = _read_text(archive, fn, md)
        if source_text is None:
            continue
        source, text = source_text
        if md is not None:
            parsed = read_component(md, "slk", source, lambda: _parse_slk_component(text), stage="parse")
            if parsed is None:
                continue
            rows = parsed
        else:
            rows = parse_slk(text)
        if md is not None and text.rstrip().splitlines()[-1].strip() != "E":
            record_component_parse_issue(md, "slk", source, "missing SLK terminator")
        for code, row in rows.items():
            if not _looks_like_code(code):
                continue
            merged.setdefault(code, {}).update(row)
    return merged


def _parse_slk_component(text: str) -> dict[str, dict[str, str]]:
    if not text.lstrip().startswith("ID;"):
        raise ComponentParseError("missing SLK ID header")
    return parse_slk(text)


def has_any_slk_objects(archive: SlkArchive) -> bool:
    """快速判断这张图是否带内嵌 SLK 对象数据（任一分类文件存在）。只查存在性，不读内容。"""
    for files in SLK_CATEGORY_FILES.values():
        for fn in files:
            if _find_name(archive, fn) is not None:
                return True
    return False

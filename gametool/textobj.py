"""解析"文本格式对象数据档"（部分地图/工具把 单位/物品/技能/科技 存成 INI 文本）。

格式：
    [I000]
    Art=...
    Name=|cff808000骨玉权杖|r
    Tip=...
    Ubertip=攻击力+26000|n智力+1200|n...

这些文件名不固定，靠"内容"识别：以 [4字符码] 开头、含 Name= 字段。
按段代码首字母粗分类型：A=技能 R=科技 I=物品 其余=单位。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Final

_COLOR = re.compile(r"\|c[0-9a-fA-F]{8}|\|r", re.IGNORECASE)
_SECTION_HEAD = re.compile(rb"^\[[A-Za-z0-9]{3,4}\]")
_WESTRING = re.compile(r"WESTRING_[A-Za-z0-9_]+")
try:
    from .westrings import WESTRINGS as _westrings
except ImportError:  # 仅当数据文件缺失时兜底；语法/导入错误等真实 bug 不再被静默吞掉
    _westrings = {}

WESTRINGS: Final[Mapping[str, str]] = _westrings


def _sub_westring(s: str) -> str:
    if "WESTRING_" not in s:
        return s
    return _WESTRING.sub(lambda m: WESTRINGS.get(m.group(0), m.group(0)), s)


def clean_text(s: str) -> str:
    s = _sub_westring(s)
    s = _COLOR.sub("", s)
    s = s.replace("|n", "\n").replace("\\n", "\n")
    return s.strip()


def looks_like_text_object(head: bytes) -> bool:
    """根据头部字节判断是否是文本对象档。"""
    h = head.lstrip(b"\xef\xbb\xbf")  # 去 BOM
    return bool(_SECTION_HEAD.match(h))


def parse_text_objects(text: str) -> list[tuple[str, dict[str, str]]]:
    """解析为 [(code, {field: value})]。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    objs: list[tuple[str, dict[str, str]]] = []
    code: str | None = None
    fields: dict[str, str] = {}
    for line in text.split("\n"):
        s = line.strip()
        if len(s) >= 5 and s[0] == "[" and s[-1] == "]" and " " not in s[1:-1]:
            inner = s[1:-1]
            if 3 <= len(inner) <= 4:
                if code is not None:
                    objs.append((code, fields))
                code = inner
                fields = {}
                continue
        if code is not None and "=" in line and not line.lstrip().startswith("//"):
            k, _, v = line.partition("=")
            k = k.strip()
            if k and k not in fields:
                fields[k] = v
    if code is not None:
        objs.append((code, fields))
    return objs


# 各类型的"特征字段"（通用字段 Art/Name/Tip/Ubertip/Requires 不算，会重叠）
_UNIT_MARKERS = {
    "propernames",
    "awakentip",
    "revivetip",
    "scorescreenicon",
    "buildingsoundlabel",
    "attachmentanimprops",
    "animprops",
    "trains",
    "builds",
    "researches",
    "upgrade",
    "sellunits",
    "sellitems",
    "movetp",
    "spd",
    "def",
    "deftype",
    "regenhp",
    "sight",
    "fmade",
    "fused",
    "isbldg",
    "dmgplus1",
    "loopingsoundfadein",
    "propwindow",
    "weapson",
}
_ABILITY_MARKERS = {
    "order",
    "targetart",
    "casterart",
    "specialart",
    "efctid",
    "buffs",
    "animnames",
    "targetattach",
    "marker",
    "casterattach",
    "areaeffectart",
    "lightningeffect",
    "dataa1",
    "datab1",
    "targs",
}
# 科技强字段（升级特有；Requires* 物品/单位也有，不能当标志）
_UPGRADE_MARKERS = {
    "effect",
    "goldbase",
    "goldmod",
    "lumberbase",
    "lumbermod",
    "benefit1",
    "base1",
    "mod1",
}


def classify(codes: Iterable[str], field_keys: Iterable[str] | None = None) -> str:
    """判定类型。明确是 单位/技能/科技 才归该类，其余一律"物品"(默认)。

    依据：单位/技能特有字段 + 代码前缀(A=技能 R=科技 n/o/h/e/u=单位)。
    物品文件多只有通用字段(Art/Name/Tip/Ubertip)，故作默认。
    """
    code_list = tuple(codes)
    fk = set(k.lower() for k in (field_keys or []))

    def hits(markers: set[str]) -> int:
        return len(fk & markers)

    su = hits(_UNIT_MARKERS)
    sa = hits(_ABILITY_MARKERS)
    sg = hits(_UPGRADE_MARKERS)
    # 代码前缀投票（强信号）
    c = Counter(code[0] for code in code_list if code)
    if c:
        top, n = c.most_common(1)[0]
        frac = n / max(1, len(code_list))
        if top == "A" and frac > 0.5:
            sa += 3
        elif top == "R" and frac > 0.5:
            sg += 3
        elif top in "neohuNEOHU" and frac > 0.45:
            su += 2
    scores = {"单位": su, "技能": sa, "科技": sg}
    best = max(scores, key=lambda k: scores[k])
    if scores[best] <= 0:
        return "物品"  # 无单位/技能/科技 信号 → 默认物品
    return best

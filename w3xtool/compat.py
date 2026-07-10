"""版本兼容报告：面向经典版本的只读风险提示。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import TYPE_CHECKING

from .script_sources import analysis_script_texts

if TYPE_CHECKING:
    from .api import MapData

_JASS_FUNCTION_RE = re.compile(
    r"\bfunction\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"takes\s+(?P<params>.*?)\s+returns\s+(?P<returns>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<body>.*?)\bendfunction\b",
    re.IGNORECASE | re.DOTALL,
)
_RETURN_RE = re.compile(r"^\s*return\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE | re.MULTILINE)
_HANDLE_TYPES = frozenset((
    "handle",
    "agent",
    "event",
    "player",
    "widget",
    "unit",
    "destructable",
    "item",
    "ability",
    "buff",
    "force",
    "group",
    "trigger",
    "triggercondition",
    "triggeraction",
    "timer",
    "location",
    "region",
    "rect",
    "boolexpr",
    "sound",
    "effect",
    "unitpool",
    "itempool",
    "quest",
    "questitem",
    "defeatcondition",
    "timerdialog",
    "leaderboard",
    "multiboard",
    "multiboarditem",
    "trackable",
    "dialog",
    "button",
    "texttag",
    "lightning",
    "image",
    "ubersplat",
    "fogstate",
    "fogmodifier",
    "hashtable",
))


class CompatSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class CompatItem:
    severity: CompatSeverity
    code: str
    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class CompatReport:
    target_patch: str
    items: tuple[CompatItem, ...]

    @property
    def by_code(self) -> dict[str, CompatItem]:
        return {item.code: item for item in self.items}

    @property
    def warnings(self) -> tuple[CompatItem, ...]:
        return tuple(item for item in self.items if item.severity == CompatSeverity.WARNING)


def build_compat_report(md: MapData, target_patch: str = "1.24E") -> CompatReport:
    """生成目标版本兼容性报告；当前默认面向 1.24E。"""
    items: list[CompatItem] = [
        CompatItem(
            CompatSeverity.INFO,
            "target.summary",
            "目标版本",
            f"按 {target_patch} 经典版能力做静态兼容检查。",
        )
    ]
    w3i = getattr(md, "w3i", None)
    if w3i is None:
        items.append(CompatItem(
            CompatSeverity.WARNING,
            "w3i.missing",
            "缺少地图信息",
            "无法确认 w3i 格式版本、脚本语言和大地图标志。",
        ))
    else:
        items.extend(_w3i_items(w3i, target_patch))
    if _uses_lua(md, w3i):
        items.append(CompatItem(
            CompatSeverity.WARNING,
            "script.lua",
            "Lua 脚本不兼容",
            f"{target_patch} 不支持 war3map.lua，需要 JASS 脚本才能在该目标版本运行。",
        ))
    items.extend(_return_bug_items(md, target_patch))
    items.extend(_asset_items(md, target_patch))
    return CompatReport(target_patch, tuple(items))


def _w3i_items(w3i, target_patch: str) -> tuple[CompatItem, ...]:
    items: list[CompatItem] = []
    version = getattr(w3i, "version", 0)
    if version >= 28:
        items.append(CompatItem(
            CompatSeverity.WARNING,
            "w3i.newer_format",
            "地图信息格式偏新",
            f"w3i 版本 {version} 属于 1.31+ 格式，{target_patch} 可能无法直接读取。",
        ))
    if getattr(w3i, "large_map", False):
        items.append(CompatItem(
            CompatSeverity.WARNING,
            "map.large",
            "大地图标志",
            f"地图启用了大地图标志，{target_patch} 环境可能存在尺寸或编辑器兼容风险。",
        ))
    return tuple(items)


def _uses_lua(md: MapData, w3i) -> bool:
    script_type = str(getattr(w3i, "script_type", "") if w3i is not None else "")
    return script_type.lower() == "lua" or any(
        name.casefold() == "war3map.lua"
        for name, _text in analysis_script_texts(md)
    )


def _return_bug_items(md: MapData, target_patch: str) -> tuple[CompatItem, ...]:
    names = tuple(sorted({
        name
        for _name, script in analysis_script_texts(md)
        for name in _return_bug_functions(script)
    }))
    if not names:
        return ()
    shown = "、".join(names[:8])
    suffix = "" if len(names) <= 8 else f" 等 {len(names)} 个"
    return (CompatItem(
        CompatSeverity.WARNING,
        "script.return_bug",
        "疑似 1.20E return bug",
        f"发现 {shown}{suffix} 使用句柄/整数 return bug 类型转换；"
        f"{target_patch} 已修复该漏洞，通常需要改为 hashtable 或安全索引方案。",
    ),)


def _return_bug_functions(script: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _JASS_FUNCTION_RE.finditer(script):
        returns_type = match.group("returns").lower()
        params = _parse_jass_params(match.group("params"))
        if not params:
            continue
        for returned_name in _RETURN_RE.findall(match.group("body")):
            param_type = params.get(returned_name.lower())
            if param_type and _is_return_bug_cast(param_type, returns_type):
                found.append(match.group("name"))
                break
    return tuple(found)


def _parse_jass_params(raw: str) -> dict[str, str]:
    text = raw.strip()
    if not text or text.lower() == "nothing":
        return {}
    params: dict[str, str] = {}
    for part in text.split(","):
        words = part.strip().split()
        if len(words) != 2:
            continue
        param_type, param_name = words
        params[param_name.lower()] = param_type.lower()
    return params


def _is_return_bug_cast(param_type: str, returns_type: str) -> bool:
    if param_type == returns_type:
        return False
    return (
        param_type == "integer" and returns_type in _HANDLE_TYPES
        or returns_type == "integer" and param_type in _HANDLE_TYPES
        or param_type in _HANDLE_TYPES and returns_type in _HANDLE_TYPES
    )


def _asset_items(md: MapData, target_patch: str) -> tuple[CompatItem, ...]:
    dds_files = sorted(
        name for name in (getattr(md, "all_files", []) or [])
        if str(name).lower().endswith(".dds")
    )
    if not dds_files:
        return ()
    return (CompatItem(
        CompatSeverity.WARNING,
        "asset.dds",
        "DDS 贴图资源",
        f"发现 {len(dds_files)} 个 DDS 资源；{target_patch} 经典环境通常应优先使用 BLP/TGA。",
    ),)

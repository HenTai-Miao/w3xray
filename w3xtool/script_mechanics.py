"""Script-side Warcraft III BJ mechanism detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

try:
    from .jass_natives import BJ_CODE_CONSTANTS, BJ_FEATURES, BJ_FUNC_CODES
except ImportError:
    BJ_CODE_CONSTANTS, BJ_FEATURES, BJ_FUNC_CODES = {}, {}, {}

# 单遍提取全部 ASCII 标识符；环视保证与 \bname\b 的 Unicode 词边界语义一致。
_IDENTIFIER_TOKEN_RE = re.compile(r"(?<!\w)([A-Za-z_][A-Za-z0-9_]*)(?!\w)")

_NEED_MARKS = {
    "ChooseRandomItem": ("随机物品池", "按物品等级/类别从暴雪默认随机物品表选择，不直接给出固定 4cc。"),
    "ChooseRandomItemBJ": ("随机物品池", "按物品等级/类别从暴雪默认随机物品表选择，不直接给出固定 4cc。"),
    "ChooseRandomItemEx": ("随机物品池", "按物品等级/类别从暴雪默认随机物品表选择，不直接给出固定 4cc。"),
    "ChooseRandomItemExBJ": ("随机物品池", "按物品等级/类别从暴雪默认随机物品表选择，不直接给出固定 4cc。"),
    "ChooseRandomCreep": ("随机野怪池", "按等级从暴雪默认野怪池选择，不直接给出固定 4cc。"),
    "ChooseRandomCreepBJ": ("随机野怪池", "按等级从暴雪默认野怪池选择，不直接给出固定 4cc。"),
    "ChooseRandomNPBuilding": ("随机中立建筑池", "从暴雪默认中立建筑池选择，不直接给出固定 4cc。"),
    "InitNeutralBuildings": ("中立建筑初始化", "初始化商店、酒馆等中立建筑库存，具体对象来自暴雪默认池。"),
}


@dataclass(frozen=True, slots=True)
class ScriptNeedMark:
    function: str
    label: str
    detail: str


def scan_script_features(script: str) -> tuple[list[str], set[str]]:
    """Return user-facing BJ feature labels and implicit object codes."""
    features: list[str] = []
    implicit: set[str] = set()
    seen: set[str] = set()
    for fname, label in BJ_FEATURES.items():
        if _has_name(script, fname):
            if label not in seen:
                seen.add(label)
                features.append(label)
            implicit.update(BJ_FUNC_CODES.get(fname, []))
    for cname, code in BJ_CODE_CONSTANTS.items():
        if _has_name(script, cname):
            implicit.add(code)
    return features, implicit


def scan_script_need_marks(script: str) -> tuple[ScriptNeedMark, ...]:
    """Detect BJ helpers that depend on Warcraft III runtime default pools."""
    marks: list[ScriptNeedMark] = []
    seen: set[str] = set()
    for fname, (label, detail) in _NEED_MARKS.items():
        if not _has_name(script, fname) or label in seen:
            continue
        seen.add(label)
        marks.append(ScriptNeedMark(fname, label, detail))
    return tuple(marks)


def merge_implicit_object_refs(out: dict[str, set[str]], script: str) -> None:
    """Add classifiable implicit BJ object codes into scan_object_refs output."""
    _features, implicit = scan_script_features(script)
    try:
        from .base_objects import BASE_OBJECTS
    except ImportError:
        BASE_OBJECTS = {}
    for code in implicit:
        entry = BASE_OBJECTS.get(code)
        if entry is None:
            continue
        cat = entry[0]
        if cat in out:
            out[cat].add(code)
    for cname, code in BJ_CODE_CONSTANTS.items():
        if "ELEVATOR" in cname and _has_name(script, cname):
            out["可破坏物"].add(code)


def format_script_mechanism_report(script: str) -> str:
    features, implicit = scan_script_features(script)
    marks = scan_script_need_marks(script)
    lines = [f"脚本特征：{len(features)}", f"隐式对象码：{len(implicit)}", f"运行时默认池：{len(marks)}"]
    if features:
        lines.append("")
        lines.append("特征：")
        lines.extend(f"- {feature}" for feature in features)
    if implicit:
        lines.append("")
        lines.append("隐式对象码：")
        lines.append(", ".join(sorted(implicit)))
    if marks:
        lines.append("")
        lines.append("运行时默认池：")
        lines.extend(f"- {mark.label}: {mark.function} · {mark.detail}" for mark in marks)
    return "\n".join(lines) + "\n"


def _has_name(script: str, name: str) -> bool:
    """Return whether ``name`` occurs as a whole identifier token.

    BJ 特征表有近两千个函数名；逐名全文 re.search 是 O(名数×脚本长度)，
    压缩单行脚本上单这一步就要数秒。先把脚本标识符提成集合再做成员判断。
    """
    if name.isascii() and name.isidentifier():
        return name in _script_identifiers(script)
    return re.search(r"\b" + re.escape(name) + r"\b", script) is not None


@lru_cache(maxsize=16)
def _script_identifiers(script: str) -> frozenset[str]:
    return frozenset(_IDENTIFIER_TOKEN_RE.findall(script))

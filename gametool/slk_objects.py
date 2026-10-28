"""解析地图内嵌的 *Data.slk 对象数据（SLK 优化图）。

「拖入无反应解决方法」类工具把对象数据转成 SLK 重打包；本工具原本只读二进制
.w3a/.w3u 与 INI 文本对象，读不了内嵌 SLK → 那类图的字段/引用读不全。本模块补上：
按分类找出 MPQ 里的 *Data.slk，用 slk.parse_slk 解出，多文件按对象码合并。

只负责"找文件 + 解析 + 合并"，返回 {对象码: {SLK列名: 值}}；统一对象候选管线负责
构建、取名和并入 MapData。
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, replace
from typing import Protocol

from .extraction_diagnostics import (
    read_component,
    DiagnosticTarget,
    record_component_parse_issue,
)
from .object_codes import valid_object_code
from .slk_evidence import SlkEvidence, parse_slk_evidence
from .slk_evidence_models import SlkDiagnostic
from .war3_encoding import decode_warcraft_string


class _DiagnosticHost(DiagnosticTarget, Protocol):
    """Structural surface of MapData used here (breaks map_data import cycle)."""


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
    "单位": [
        "UnitData.slk",
        "UnitBalance.slk",
        "UnitUI.slk",
        "UnitWeapons.slk",
        "UnitAbilities.slk",
    ],
}

# SLK 文件在 MPQ 里可能裸放或在 Units\ / Doodads\ 下（不区分大小写）。
_PREFIXES = ["", "Units\\", "Doodads\\"]

_CATEGORY_KEY_HEADERS = {
    "技能": {"abilityid"},
    "物品": {"itemid"},
    "增益": {"buffid"},
    "可破坏物": {"destructableid"},
    "科技": {"upgradeid"},
    "装饰物": {"doodid"},
    "单位": {"unitid"},
}
_COMMON_KEY_HEADERS = {"id", "code", "alias"}


@dataclass(frozen=True, slots=True)
class SlkSourceEvidence:
    """A declared archive/category binding plus its complete source evidence."""

    source: str
    category: str
    table: SlkEvidence
    identity_confirmed: bool


# 常用 SLK 列名（无等级后缀）→ 中文标签。带等级后缀的列(Cast2/BuffID1…)交给 SLK_BASE_LABELS。
SLK_COL_LABELS = {
    "Name": "名称",
    "Tip": "提示",
    "Ubertip": "说明",
    "Hotkey": "快捷键",
    "Art": "图标",
    "art": "图标",
    "race": "种族",
    "levels": "等级数",
    "Cooldown": "冷却",
    "Requires": "依赖",
    "Name1": "名称",
    "HP": "生命",
    "hitPoints": "生命",
    "manaN": "魔法上限",
    "def": "护甲",
    "goldcost": "金币",
    "lumbercost": "木材",
    "Level": "等级",
    "ico": "图标",
}

# 带等级后缀的列：去掉末位数字后的"基名" → 中文标签（Cast2→施法间隔(等级2)）。
SLK_BASE_LABELS = {
    "Cast": "施法间隔",
    "Cool": "冷却",
    "Cost": "魔法消耗",
    "Dur": "持续时间",
    "HeroDur": "英雄持续",
    "Area": "作用范围",
    "Rng": "施法距离",
    "BuffID": "buff效果",
    "EfctID": "效果",
    "UnitID": "召唤/创建单位",
    "DataA": "数据A",
    "DataB": "数据B",
    "DataC": "数据C",
    "DataD": "数据D",
    "DataE": "数据E",
    "DataF": "数据F",
    "DataG": "数据G",
    "DataH": "数据H",
    "DataI": "数据I",
    "targs": "目标类型",
    "Requires": "依赖",
    "dmgplus": "攻击力加成",
}

# 编辑器噪声列（来自工具包 Config.ini [AlwaysEmpty]，按分类）+ 冗余 code。展示时跳过。
_ALWAYS_EMPTY = {
    "技能": "comments,version,useInEditor,hero,item,sort,race,InBeta",
    "物品": "comments,scriptname,version,InBeta",
    "增益": "comments,isEffect,version,useInEditor,sort,race,InBeta",
    "可破坏物": "comments,EditorSuffix,InBeta,version",
    "装饰物": "comment,InBeta,version",
    "科技": "comments,sort,version,InBeta",
    "单位": (
        "sort,comment,comments,InBeta,version,sortBalance,sort2,"
        "sortUI,inEditor,hiddenInEditor,sortWeap,sortAbil"
    ),
}
SLK_NOISE_COLS = {cat: set(s.split(",")) | {"code"} for cat, s in _ALWAYS_EMPTY.items()}


_LEVEL_SUFFIX = re.compile(
    r"^(.*?)(\d+)$"
)  # 去掉整段末尾数字(支持多位等级，如 DataA10)


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


def _read_text(
    archive: SlkArchive, name: str, md: DiagnosticTarget | None = None
) -> tuple[str, str, bytes] | None:
    """在 MPQ 里找并读出该 SLK 文本；找不到/解码失败返回 None。"""
    fn = _find_name(archive, name)
    if fn is None:
        return None

    def read() -> tuple[str, str, bytes]:
        payload = archive.read_file(fn)
        return fn, decode_warcraft_string(payload), payload

    if md is not None:
        return read_component(md, "slk", fn, read)
    try:
        return read()
    except KeyError, OSError, UnicodeError, ValueError:
        return None


def _looks_like_code(key: str) -> bool:
    """Use the shared case-sensitive four-byte Latin-1 identity boundary."""
    return valid_object_code(key)


def parse_category_evidence(
    archive: SlkArchive,
    category: str,
    *,
    md: DiagnosticTarget | None = None,
) -> tuple[SlkSourceEvidence, ...]:
    """Read every present category file, retaining raw bytes and source issues.

    A malformed source remains inspectable and cannot bind guessed object IDs.
    ``md`` receives every issue with complete escaped raw records and offsets.
    """
    result: list[SlkSourceEvidence] = []
    for name in SLK_CATEGORY_FILES.get(category, []):
        source_text = _read_text(archive, name, md)
        if source_text is None:
            continue
        source, text, payload = source_text
        table = parse_slk_evidence(text, raw_bytes=payload)
        header = next(
            (column.name for column in table.columns if column.number == 1), None
        )
        allowed = _COMMON_KEY_HEADERS | _CATEGORY_KEY_HEADERS.get(category, set())
        identity_confirmed = (
            not any(issue.code == "missing_id" for issue in table.diagnostics)
            and header is not None
            and header.casefold() in allowed
        )
        issues = list(table.diagnostics)
        if header is not None and header.casefold() not in allowed:
            issues.append(
                SlkDiagnostic(
                    "unsupported_key_header",
                    f"{category} object table has no declared object-ID key role: {header!r}",
                    cell_indexes=tuple(range(len(table.cells))),
                    conflict=True,
                )
            )
        for row in table.rows:
            if row.key is not None and not _looks_like_code(row.key):
                issues.append(
                    SlkDiagnostic(
                        "invalid_object_id",
                        "declared object identity is not four-byte Latin-1",
                        cell_indexes=row.cell_indexes,
                        conflict=True,
                    )
                )
        table = replace(table, diagnostics=tuple(issues))
        if md is not None:
            for issue in issues:
                detail = json.loads(table.diagnostic_text(issue))
                detail["category"] = category
                record_component_parse_issue(
                    md, "slk", source, json.dumps(detail, ensure_ascii=True)
                )
        result.append(SlkSourceEvidence(source, category, table, identity_confirmed))
    return tuple(result)


def parse_category_objects(
    archive: SlkArchive,
    category: str,
    *,
    md: DiagnosticTarget | None = None,
) -> dict[str, dict[str, str]]:
    """解析某分类的全部 SLK 文件，按对象码合并列，返回 {码: {列名: 值}}。

    单位类跨 UnitData/UnitBalance/UnitUI/UnitWeapons/UnitAbilities 合并同码行。
    某文件缺失/解析失败时跳过该文件（不拖垮整类）。
    """
    sources = parse_category_evidence(archive, category, md=md)
    merged: dict[str, dict[str, str]] = {}
    values: dict[tuple[str, str], list[tuple[SlkSourceEvidence, str, str]]] = {}
    blocked: set[tuple[str, str]] = set()
    origins: (
        dict[tuple[str, str], list[tuple[SlkSourceEvidence, tuple[int, ...]]]] | None
    ) = None
    for source in sources:
        if not source.identity_confirmed:
            continue
        blocked.update(source.table.blocked_fields)
        for row in source.table.objects:
            code = row.key
            if not _looks_like_code(code):
                continue
            merged.setdefault(code, {})
            kinds = dict(row.value_kinds)
            for name, value in row.fields:
                values.setdefault((code, name), []).append((source, value, kinds[name]))
    for identity, evidence in values.items():
        code, name = identity
        unique = {(value, kind) for _source, value, kind in evidence}
        if len(unique) == 1 and identity not in blocked:
            merged[code][name] = next(iter(unique))[0]
            continue
        if md is not None:
            if origins is None:
                origins = _field_origins(sources)
            _record_merge_conflict(md, category, code, name, origins.get(identity, []))
    return merged


def _field_origins(
    sources: tuple[SlkSourceEvidence, ...],
) -> dict[tuple[str, str], list[tuple[SlkSourceEvidence, tuple[int, ...]]]]:
    """Index every field origin once, rather than rescanning all rows per issue."""
    result: dict[tuple[str, str], list[tuple[SlkSourceEvidence, tuple[int, ...]]]] = {}
    for source in sources:
        if not source.identity_confirmed:
            continue
        table = source.table
        columns = {column.number: column for column in table.columns}
        grouped: dict[tuple[str, str], dict[int, None]] = {}
        for row in table.rows:
            if row.key is None:
                continue
            key_indexes = tuple(
                index for index in row.cell_indexes if table.cells[index].x == 1
            )
            for index in row.cell_indexes:
                cell = table.cells[index]
                column = columns.get(cell.x) if cell.x is not None else None
                if column is None or cell.x == 1:
                    continue
                for name in column.candidate_names:
                    indexes = grouped.setdefault((row.key, name), {})
                    indexes.update(
                        dict.fromkeys((*column.cell_indexes, *key_indexes, index))
                    )
        for identity, indexes in grouped.items():
            result.setdefault(identity, []).append((source, tuple(indexes)))
    return result


def _record_merge_conflict(
    md: DiagnosticTarget,
    category: str,
    code: str,
    name: str,
    evidence: list[tuple[SlkSourceEvidence, tuple[int, ...]]],
) -> None:
    origins: list[dict[str, object]] = []
    names: list[str] = []
    for source, indexes in evidence:
        table = source.table
        issue = SlkDiagnostic("source_field_evidence", "", cell_indexes=indexes)
        origins.append(
            {
                "source": source.source,
                "evidence": json.loads(table.diagnostic_text(issue)),
            }
        )
        names.append(source.source)
    detail = {
        "code": "cross_source_field_conflict",
        "category": category,
        "object_id": code,
        "field": name,
        "sources": origins,
    }
    record_component_parse_issue(
        md, "slk", " | ".join(names), json.dumps(detail, ensure_ascii=True)
    )


def has_any_slk_objects(archive: SlkArchive) -> bool:
    """快速判断这张图是否带内嵌 SLK 对象数据（任一分类文件存在）。只查存在性，不读内容。"""
    for files in SLK_CATEGORY_FILES.values():
        for fn in files:
            if _find_name(archive, fn) is not None:
                return True
    return False

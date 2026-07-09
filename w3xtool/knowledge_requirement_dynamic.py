"""Map-specific status evaluation for knowledge-pack requirement rows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .extraction_completeness import (
    ExtractionCompletenessReport,
    build_extraction_completeness_report,
)

if TYPE_CHECKING:
    from .api import MapData
    from .knowledge_requirements import ExtractionCapabilities, RequirementCoverage


@dataclass(frozen=True, slots=True)
class _MapFacts:
    files: int
    objects: int
    scripts: int
    placements: int
    world: int
    triggers: int
    variables: int
    eca: int
    has_terrain: bool
    source_readable: bool
    completeness_warnings: int


def build_dynamic_rows(
    md: MapData | None,
    capabilities: ExtractionCapabilities,
) -> tuple[RequirementCoverage, ...]:
    """Build technical rows whose status comes from this load."""
    from .knowledge_requirements import RequirementCoverage

    summary = getattr(md, "trigger_summary", None) if md is not None else None
    functions = tuple(getattr(summary, "eca_functions", ()) or ())
    triggers = tuple(getattr(summary, "triggers", ()) or ())
    partial = bool(
        getattr(summary, "missing_schema_functions", ())
        or getattr(summary, "parse_failures", ())
        or getattr(summary, "has_unexpanded_functions", False)
    )
    eca_status = "部分提取" if partial else ("已提取" if functions else "未发现")
    eca_note = f"触发器 {len(triggers)}，已展开 ECA {len(functions)}。"
    if capabilities.has_trigger_strings:
        eca_note += " TriggerStrings 本地化可用。"
    elif capabilities.has_trigger_schema:
        eca_note += " TriggerStrings 缺失，仅保留函数和参数。"
    listfile = capabilities.external_listfile
    listfile_status = "未提供"
    listfile_note = "未选择外部 listfile。"
    if listfile is not None:
        listfile_status = "部分采用" if listfile.missing or listfile.unsafe else "已验证"
        listfile_note = (
            f"确认 {len(listfile.confirmed)}，缺失 {len(listfile.missing)}，"
            f"不安全 {len(listfile.unsafe)}，重复 {len(listfile.duplicates)}。"
        )
    casc_status = (
        "可用"
        if capabilities.game_data_kind in {"casclib", "native_casc"}
        else ("使用散文件" if capabilities.game_data_kind == "extracted_dir" else "源数据缺失")
    )
    diagnosis = _diagnosis_label(capabilities.archive_diagnosis_kind)
    return (
        RequirementCoverage("WTG ECA", eca_status, ("触发器ECA.tsv",), ("触发器树.tsv",), eca_note),
        RequirementCoverage("外部 listfile", listfile_status, ("内部文件清单.txt",), (), listfile_note),
        RequirementCoverage("原生 CASC", casc_status, (), ("触发器ECA.tsv", "资源/"), "只读游戏基础数据源。"),
        RequirementCoverage("归档诊断", diagnosis, ("提取完整性.txt",), (), "开档失败时仅报告有界静态证据。"),
        RequirementCoverage("运行时解密", "不支持", (), ("提取完整性.txt",), "仅做静态诊断与原始负载保留。"),
    )


def evaluate_requirement_rows(
    rows: tuple[RequirementCoverage, ...],
    md: MapData | None,
    completeness: ExtractionCompletenessReport | None = None,
) -> tuple[RequirementCoverage, ...]:
    """Downgrade generic catalog claims when this map has no matching data."""
    if md is None:
        return rows
    facts = _map_facts(md, completeness)
    suffix = (
        f" 当前地图：内部文件 {facts.files}，对象 {facts.objects}，"
        f"脚本 {facts.scripts}，ECA {facts.eca}。"
    )
    evaluated = []
    for row in rows:
        available = _request_available(row.request, facts)
        if row.request == "核对提取是否完整":
            status = _completeness_status(facts)
        elif available is False:
            status = "未发现数据"
        else:
            status = row.status
        evaluated.append(replace(row, status=status, note=row.note + suffix))
    return tuple(evaluated)


def _map_facts(
    md: MapData,
    completeness: ExtractionCompletenessReport | None = None,
) -> _MapFacts:
    summary = getattr(md, "trigger_summary", None)
    files = tuple(getattr(md, "all_files", ()) or ())
    resolved_completeness = (
        completeness
        if completeness is not None
        else build_extraction_completeness_report(md)
    )
    return _MapFacts(
        files=len(files),
        objects=sum(len(items) for items in (getattr(md, "objects", {}) or {}).values()),
        scripts=len(getattr(md, "scripts", {}) or {}),
        placements=len(getattr(md, "units", ()) or ()) + len(getattr(md, "doodads", ()) or ()),
        world=sum(len(getattr(md, name, ()) or ()) for name in ("regions", "cameras", "sounds")),
        triggers=len(tuple(getattr(summary, "triggers", ()) or ())),
        variables=len(tuple(getattr(summary, "variables", ()) or ())),
        eca=len(tuple(getattr(summary, "eca_functions", ()) or ())),
        has_terrain=any(name.lower().endswith((".w3e", ".wpm", ".shd")) for name in files),
        source_readable=resolved_completeness.source_readable,
        completeness_warnings=len(resolved_completeness.warnings),
    )


def _request_available(request: str, facts: _MapFacts) -> bool | None:
    match request:
        case "提取/整理 UI 文本":
            return bool(facts.scripts or facts.objects)
        case "提取/整理图标和资源":
            return bool(facts.files or facts.scripts or facts.objects)
        case "整理配置文件格式":
            return bool(facts.files)
        case "分析本地存档读写":
            return bool(facts.scripts)
        case "分析地图 ID":
            return True
        case "分析物品/技能/单位 ID":
            return bool(facts.objects or facts.placements)
        case request_name if request_name.startswith("分析脚本"):
            return bool(facts.scripts)
        case "分析预放置单位/装饰物":
            return bool(facts.placements)
        case "分析触发器和全局变量":
            return bool(facts.triggers or facts.variables or facts.eca)
        case "分析区域/镜头/声音":
            return bool(facts.world)
        case "分析地形和路径网格":
            return facts.has_terrain
        case "核对提取是否完整":
            return True
        case _:
            return None


def _completeness_status(facts: _MapFacts) -> str:
    if not facts.source_readable:
        return "部分覆盖（源不可读）"
    if facts.completeness_warnings:
        return "部分覆盖（有警告）"
    return "已覆盖（诊断+兜底导出）"


def _diagnosis_label(kind: str) -> str:
    return {
        "": "未运行",
        "missing": "文件缺失",
        "permission": "权限受限",
        "read_error": "读取失败",
        "no_header": "未找到 MPQ 头",
        "table_damage": "结构损坏",
        "unsupported": "版本不支持",
    }.get(kind, kind)

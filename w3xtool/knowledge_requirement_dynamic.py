"""Map-specific status evaluation for knowledge-pack requirement rows."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, assert_never

from .extraction_completeness import (
    ExtractionCompletenessReport,
)
from .knowledge_requirement_facts import build_runtime_fact_rows
from .knowledge_requirement_map_facts import (
    build_map_requirement_facts,
    completeness_status,
    request_available,
)
from .knowledge_requirement_models import ExtractionCapabilities, RequirementCoverage
from .knowledge_results import KnowledgeWriteStatus

if TYPE_CHECKING:
    from .map_data import MapData


def build_dynamic_rows(
    md: MapData | None,
    capabilities: ExtractionCapabilities,
) -> tuple[RequirementCoverage, ...]:
    """Build technical rows whose status comes from this load."""
    summary = md.trigger_summary if md is not None else None
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
        listfile_status = (
            "部分采用" if listfile.missing or listfile.unsafe else "已验证"
        )
        listfile_note = (
            f"确认 {len(listfile.confirmed)}，缺失 {len(listfile.missing)}，"
            f"不安全 {len(listfile.unsafe)}，重复 {len(listfile.duplicates)}。"
        )
    casc_status = (
        "可用"
        if capabilities.game_data_kind in {"casclib", "native_casc"}
        else (
            "使用散文件"
            if capabilities.game_data_kind == "extracted_dir"
            else "源数据缺失"
        )
    )
    diagnosis = _diagnosis_label(capabilities.archive_diagnosis_kind)
    return (
        *build_runtime_fact_rows(md, capabilities),
        _publication_row(capabilities),
        RequirementCoverage(
            "WTG ECA", eca_status, ("触发器ECA.tsv",), ("触发器树.tsv",), eca_note
        ),
        RequirementCoverage(
            "外部 listfile", listfile_status, ("内部文件清单.txt",), (), listfile_note
        ),
        RequirementCoverage(
            "原生 CASC",
            casc_status,
            (),
            ("触发器ECA.tsv", "资源/"),
            "只读游戏基础数据源。",
        ),
        RequirementCoverage(
            "归档诊断",
            diagnosis,
            ("提取完整性.txt",),
            (),
            "开档失败时仅报告有界静态证据。",
        ),
        RequirementCoverage(
            "运行时解密",
            "不支持",
            (),
            ("提取完整性.txt",),
            "仅做静态诊断与原始负载保留。",
        ),
    )


def _publication_row(capabilities: ExtractionCapabilities) -> RequirementCoverage:
    report = capabilities.write_report
    if report is None:
        return RequirementCoverage(
            "资料包发布",
            "未运行",
            ("资料包写入结果.tsv",),
            ("组件诊断.tsv",),
            "尚无本次写盘结果。",
        )
    status = _publication_status_label(report.status)
    note = f"成功 {report.written_count}，失败 {report.failed_count}。"
    first_failure = next((item for item in report.items if not item.written), None)
    if first_failure is not None:
        note += (
            f" 首个失败：{first_failure.path}（{first_failure.error or '未知错误'}）。"
        )
    return RequirementCoverage(
        "资料包发布",
        status,
        ("资料包写入结果.tsv",),
        ("组件诊断.tsv",),
        note,
    )


def _publication_status_label(status: KnowledgeWriteStatus) -> str:
    match status:  # noqa: MATCH_OK - assert_never below proves exhaustiveness.
        case KnowledgeWriteStatus.COMPLETE:
            return "完整"
        case KnowledgeWriteStatus.PARTIAL:
            return "部分完成"
        case KnowledgeWriteStatus.FAILED:
            return "失败"
    assert_never(status)


def evaluate_requirement_rows(
    rows: tuple[RequirementCoverage, ...],
    md: MapData | None,
    completeness: ExtractionCompletenessReport | None = None,
) -> tuple[RequirementCoverage, ...]:
    """Downgrade generic catalog claims when this map has no matching data."""
    if md is None:
        return rows
    facts = build_map_requirement_facts(md, completeness)
    suffix = (
        f" 当前地图：内部文件 {facts.files}，对象 {facts.objects}，"
        f"脚本 {facts.scripts}，ECA {facts.eca}，全文 {facts.text_records}，"
        f"装备关系 {facts.relation_records}。"
    )
    evaluated: list[RequirementCoverage] = []
    for row in rows:
        available = request_available(row.request, facts)
        if row.request == "核对提取是否完整":
            status = completeness_status(facts)
        elif row.request == "提取完整对象说明" and facts.text_partial:
            status = "部分覆盖"
        elif row.request == "分析装备掉落与获取" and (
            facts.relation_partial or facts.text_partial
        ):
            status = "部分覆盖"
        elif available is False:
            status = "未发现数据"
        else:
            status = row.status
        evaluated.append(replace(row, status=status, note=row.note + suffix))
    return tuple(evaluated)


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

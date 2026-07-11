"""Map-specific extraction facts for requirement coverage."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from .archive_source import BytesArchiveSource
from .extraction_diagnostics import DiagnosticSeverity
from .knowledge_requirement_models import ExtractionCapabilities, RequirementCoverage
from .script_sources import WCT_TEXT_NAME, analysis_script_texts
from .ui_texts import build_ui_text_report

if TYPE_CHECKING:
    from .map_data import MapData

_TRIGSTR_RE: Final = re.compile(r"\bTRIGSTR_\d+\b", re.IGNORECASE)


def build_runtime_fact_rows(
    md: MapData | None,
    capabilities: ExtractionCapabilities,
) -> tuple[RequirementCoverage, ...]:
    """Return evidence rows derived from this exact extraction result."""
    return (
        _object_source_row(md),
        _wts_row(md),
        _script_source_row(md),
        _campaign_row(md),
        _inventory_row(capabilities),
        _diagnostic_row(md),
    )


def _object_source_row(md: MapData | None) -> RequirementCoverage:
    counts = md.object_source_counts if md is not None else {}
    binary = counts.get("binary", 0)
    slk = counts.get("slk", 0)
    text = counts.get("text", 0)
    base = counts.get("base", 0)
    status = "已合并" if binary + slk + text + base else "未发现"
    note = f"二进制 {binary}，SLK {slk}，文本 {text}，基础 {base}。"
    return _row("对象来源", status, ("对象ID/",), ("对象文本与图标.tsv",), note)


def _wts_row(md: MapData | None) -> RequirementCoverage:
    if md is None:
        return _row("WTS 还原", "未运行", ("UI文本引用.tsv",), (), "尚无地图结果。")
    report = build_ui_text_report(md)
    object_unresolved = sum(
        len(_TRIGSTR_RE.findall(value))
        for items in md.objects.values()
        for item in items
        for value in item.field_values.values()
    )
    total = report.reference_count + object_unresolved
    unresolved = report.unresolved_count + object_unresolved
    if unresolved:
        status = "部分还原"
    elif total:
        status = "全部还原"
    else:
        status = "未发现引用"
    return _row(
        "WTS 还原",
        status,
        ("UI文本_TRIGSTR.tsv", "UI文本引用.tsv"),
        ("对象文本与图标.tsv",),
        f"引用 {total}，已还原 {total - unresolved}，未解析 {unresolved}。",
    )


def _script_source_row(md: MapData | None) -> RequirementCoverage:
    sources = analysis_script_texts(md) if md is not None else ()
    jass = sum(name.casefold().endswith(".j") for name, _text in sources)
    lua = sum(name.casefold().endswith(".lua") for name, _text in sources)
    wct = sum(name == WCT_TEXT_NAME for name, _text in sources)
    status = "已提取" if sources else "未发现"
    return _row(
        "脚本来源",
        status,
        ("脚本清单.txt",),
        ("脚本可读文本/",),
        f"JASS {jass}，Lua {lua}，WCT {wct}。",
    )


def _campaign_row(md: MapData | None) -> RequirementCoverage:
    declared = len(tuple(getattr(getattr(md, "w3f", None), "maps", ()) or ())) if md is not None else 0
    children = tuple(md.sub_maps) if md is not None else ()
    readable = sum(_child_source_readable(child) for child in children)
    failed = sum(item.component == "campaign-child" for item in md.diagnostics) if md is not None else 0
    if declared == 0 and not children and failed == 0:
        status = "未发现"
    elif failed or readable < max(declared, len(children)):
        status = "部分加载"
    else:
        status = "已加载"
    note = f"声明 {declared}，已加载且可重开 {readable}，失败 {failed}。"
    return _row("战役子图", status, ("地图信息.txt",), ("组件诊断.tsv",), note)


def _child_source_readable(child: MapData) -> bool:
    source = child.archive_source
    if source is None:
        return False
    if isinstance(source, BytesArchiveSource):
        return not source.is_closed
    return True


def _inventory_row(capabilities: ExtractionCapabilities) -> RequirementCoverage:
    labels = {
        "full_root": "完整 Root 视图",
        "known_paths": "已知路径视图",
        "unavailable": "不可枚举",
        "": "未运行",
    }
    status = labels.get(capabilities.game_data_inventory_view, "不可枚举")
    return _row("客户端数据清单", status, (), ("资源/",), "按实际 inventory 能力报告。")


def _diagnostic_row(md: MapData | None) -> RequirementCoverage:
    diagnostics = tuple(md.diagnostics) if md is not None else ()
    warnings = sum(item.severity is DiagnosticSeverity.WARNING for item in diagnostics)
    errors = sum(item.severity is DiagnosticSeverity.ERROR for item in diagnostics)
    status = "有错误" if errors else ("有警告" if warnings else "无异常")
    return _row(
        "组件诊断",
        status,
        ("组件诊断.tsv",),
        (),
        f"警告 {warnings}，错误 {errors}，总计 {len(diagnostics)}。",
    )


def _row(
    request: str,
    status: str,
    primary: tuple[str, ...],
    secondary: tuple[str, ...],
    note: str,
) -> RequirementCoverage:
    return RequirementCoverage(request, status, primary, secondary, note)

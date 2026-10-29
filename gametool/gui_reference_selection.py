"""Complete selected reference evidence and source-bound offline query handoffs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, replace
import json
from pathlib import Path
from typing import Any

from .batch_tsv import format_tsv_rows
from .object_codes import valid_object_code
from .pack_query_objects import OBJECT_TABLES
from .reference_cli import (
    _require_report_destination,
    format_reference_record,
    reference_result_to_dict,
)
from .reference_models import ReferenceSearchResult
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteStatus
from .search import encode_literal_query


def _selected_indices(
    result: ReferenceSearchResult, indices: Iterable[int]
) -> tuple[int, ...]:
    selected = tuple(indices)
    if not selected:
        raise ValueError("请先在左侧列表选择完整条目；Ctrl / Shift 可多选。")
    if any(
        type(index) is not int or not 0 <= index < len(result.records)
        for index in selected
    ):
        raise ValueError("所选条目已不属于本次结果；请刷新后重新选择。")
    # List positions preserve independent same-code/category/scope evidence.
    return tuple(sorted(set(selected)))


def reference_selection_to_dict(
    result: ReferenceSearchResult, indices: Iterable[int]
) -> dict[str, Any]:
    """Retain whole records and the complete original source/diagnostic context."""
    selected = _selected_indices(result, indices)
    payload = reference_result_to_dict(
        replace(result, records=tuple(result.records[index] for index in selected))
    )
    payload["selection"] = {
        "indices": list(selected),
        "selected": len(selected),
        "displayed": len(result.records),
        "matched": result.matched,
        "omitted_by_query": result.omitted,
    }
    return payload


def format_reference_selection(
    result: ReferenceSearchResult, indices: Iterable[int]
) -> str:
    """Render selected records plus their lossless evidence and full context."""
    selected = _selected_indices(result, indices)
    payload = reference_selection_to_dict(result, selected)
    lines = [
        "GameXRay 离线参考 · 选中完整证据",
        f"选中 {len(selected)} / 当前列表 {len(result.records)}；查询匹配 {result.matched}。",
        "列表序号从 1 开始；结构化 selection.indices 从 0 开始。",
        "== 详情 ==",
    ]
    for index in selected:
        lines.extend(
            (f"\n列表第 {index + 1} 条", format_reference_record(result.records[index]))
        )
    lines.extend(("", "== 原始记录 =="))
    for index in selected:
        lines.extend(
            (
                f"列表第 {index + 1} 条 · 完整记录 JSON（含全部字段、原始行与诊断）",
                "```json",
                json.dumps(asdict(result.records[index]), ensure_ascii=False, indent=2),
                "```",
            )
        )
    context = {key: value for key, value in payload.items() if key != "records"}
    lines.extend(
        (
            "",
            "== 来源 ==",
            "完整查询、选择、来源台账与地图/章节范围：",
            "```json",
            json.dumps(context, ensure_ascii=False, indent=2),
            "```",
            "",
            "== 诊断 ==",
            *result.diagnostics,
        )
    )
    if not result.catalog_complete:
        lines.append("来源不完整；保留已确认记录，请核对完整来源与范围诊断。")
    elif not result.diagnostics:
        lines.append("本次来源读取完整；静态证据不证明当前游戏的实时值。")
    return "\n".join(lines) + "\n"


def format_reference_selection_tsv(
    result: ReferenceSearchResult, indices: Iterable[int]
) -> str:
    """One context row and whole-record rows; every cell uses the shared codec."""
    selected = _selected_indices(result, indices)
    payload = reference_selection_to_dict(result, selected)
    context = {key: value for key, value in payload.items() if key != "records"}

    def rows():
        yield (
            "记录类型",
            "列表序号",
            "kind",
            "category",
            "id",
            "label",
            "scope",
            "sources_json",
            "完整证据_json",
        )
        yield (
            "catalog",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            json.dumps(context, ensure_ascii=False),
        )
        for index in selected:
            record = result.records[index]
            yield (
                "record",
                str(index + 1),
                record.kind,
                record.category,
                record.id,
                record.label,
                record.scope,
                json.dumps(record.sources, ensure_ascii=False),
                json.dumps(asdict(record), ensure_ascii=False),
            )

    return format_tsv_rows(rows())


def write_reference_selection(
    path: str | Path, result: ReferenceSearchResult, indices: Iterable[int]
) -> None:
    """Use the existing input protection and safe report publication boundary."""
    destination = Path(path).absolute()
    selected = _selected_indices(result, indices)
    _require_report_destination(destination, result)
    suffix = destination.suffix.casefold()
    if suffix == ".json":
        content = (
            json.dumps(
                reference_selection_to_dict(result, selected),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    elif suffix == ".tsv":
        content = format_reference_selection_tsv(result, selected)
    else:
        content = format_reference_selection(result, selected)
    _require_report_destination(destination, result)
    written = write_text_safely(str(destination.parent), destination.name, content)
    if written.status != SafeWriteStatus.WRITTEN:
        raise OSError(f"参考报告写入失败: {written.status.value} {written.error}")


def reference_pack_query_target(
    result: ReferenceSearchResult, index: int, pack_dir: str
) -> tuple[str, str, str] | None:
    """Bind one record to its actual pack or immediate campaign child only."""
    if result.map_path or not pack_dir or not 0 <= index < len(result.records):
        return None
    record = result.records[index]
    if (
        record.kind != "objects"
        or record.state not in {"map-evidence", "field-only"}
        or record.category not in OBJECT_TABLES
        or not valid_object_code(record.id)
    ):
        return None
    root, scope = Path(pack_dir).absolute(), Path(record.scope)
    if (
        not scope.is_absolute()
        or root not in tuple(Path(path) for path in result.input_roots)
        or not (scope == root or scope.parent == root / "子地图")
    ):
        return None
    expected = {
        scope / "对象ID" / f"{record.category}.tsv",
        scope / "对象字段.tsv",
    }
    if not any(
        source.id in record.sources
        and source.state == "map-evidence"
        and source.fingerprint_basis == "file-bytes"
        and not source.member_path
        and bool(source.sha256)
        and Path(source.path) in expected
        for source in result.sources
    ):
        return None
    command = {
        "物品": "item",
        "单位": "units",
        "英雄": "heroes",
        "技能": "skills",
        "增益": "buffs",
        "科技": "tech",
    }.get(record.category, "search")
    query = encode_literal_query(record.id)
    if command == "search":
        query = f"{record.category}:{query}"
    return str(scope), command, query

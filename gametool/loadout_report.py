"""Stable source reads, whole-record queries and complete offline plan reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from .batch_tsv import format_tsv_rows
from .live_report_io import _parents, read_report_bytes
from .loadout_documents import LoadoutDocument, LoadoutRecord, inspect_loadout_document
from .report_file_proof import (
    cleanup_report_paths,
    report_metadata,
    report_parent_proof,
    require_report_payload,
)
from .search import compile_query
from .windows_output_paths import native_output_path, validate_output_root


@dataclass(frozen=True, slots=True)
class LoadoutReport:
    document: LoadoutDocument
    source_metadata: dict[str, Any]
    stable: bool
    source_diagnostics: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        return 0 if self.stable and self.document.complete else 2


@dataclass(frozen=True, slots=True)
class LoadoutSelection:
    report: LoadoutReport
    records: tuple[LoadoutRecord, ...]
    query: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "report_type": "offline-loadout-inspection",
            "report_is_plan": False,
            "input_error": False,
            "exit_code": self.report.exit_code,
            "source_stable": self.report.stable,
            "source_metadata": self.report.source_metadata,
            "source_diagnostics": list(self.report.source_diagnostics),
            "selection": {
                "query": self.query,
                "total_records": len(self.report.document.records),
                "matched_records": len(self.records),
                "ordinals": [record.ordinal for record in self.records],
            },
            "document": self.report.document.to_dict(),
        }


def _same_source(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _read_loadout_source(path: str | Path) -> tuple[bytes, dict[str, Any]]:
    """Use native Windows I/O without changing the reported source spelling."""
    validate_output_root(os.fspath(path))
    display_path = os.path.abspath(path)
    raw, metadata = read_report_bytes(native_output_path(display_path))
    metadata["path"] = display_path
    return raw, metadata


def revalidate_loadout_source(report: LoadoutReport) -> None:
    """Re-read every source byte, including changes with restored size/mtime."""
    if not report.stable:
        raise ValueError("来源未通过稳定复验；请重新读取后导出。")
    _raw, metadata = _read_loadout_source(report.source_metadata["path"])
    if not _same_source(report.source_metadata, metadata):
        raise ValueError("方案来源的完整字节或身份已变化；请点击读取 / 刷新后重试。")


def read_loadout_report(
    path: str | Path, *, text_encoding: str = "auto"
) -> LoadoutReport:
    raw, metadata = _read_loadout_source(path)
    document = inspect_loadout_document(
        raw, metadata["path"], text_encoding=text_encoding
    )
    report = LoadoutReport(document, metadata, True)
    try:
        revalidate_loadout_source(report)
    except (OSError, ValueError) as exc:
        return LoadoutReport(document, metadata, False, (str(exc),))
    return report


def _record_search_fields(
    document: LoadoutDocument, record: LoadoutRecord
) -> tuple[str, ...]:
    fields = [
        document.raw_token(record.node),
        record.kind,
        record.name or "",
        record.unit_code or "",
    ]
    fields.extend(slot.code or "" for slot in record.slots)
    fields.extend(slot.type_literal or "" for slot in record.slots)
    fields.extend(slot.charge_literal or "" for slot in record.slots)
    pending = [record.node]
    if document.root is not None:
        # Root extensions apply to the document, never to only its last record.
        # Exclude other records/codes so a query cannot match a different plan.
        pending.extend(
            member.node
            for member in document.nodes[document.root].members
            if member.key not in {"records", "codes"}
        )
    while pending:
        node = document.nodes[pending.pop()]
        if node.value is not None:
            fields.append(str(node.value))
        fields.extend(member.key for member in node.members)
        pending.extend(member.node for member in node.members)
        pending.extend(node.elements)
    return tuple(fields)


def select_loadout_report(report: LoadoutReport, query: str = "") -> LoadoutSelection:
    compiled = compile_query(query)
    if query.strip() and compiled.is_empty:
        raise ValueError('查询表达式没有关键词；可用 &&、||、%、括号或 ="精准词"。')
    records = tuple(
        record
        for record in report.document.records
        if compiled.score_fields(_record_search_fields(report.document, record))
        is not None
    )
    return LoadoutSelection(report, records, query)


def _visible(value: object) -> str:
    if value is None:
        return "未确认"
    if isinstance(value, str):
        return (
            json.dumps(value, ensure_ascii=False)
            .encode("utf-8", errors="backslashreplace")
            .decode("utf-8")
        )
    return str(value)


def format_loadout_report(selection: LoadoutSelection) -> str:
    document = selection.report.document
    states = {
        "confirmed": "完整确认声明",
        "partial": "部分损坏或存在歧义",
        "not-plan": "未识别为方案",
    }
    lines = [
        "# 离线装备方案",
        "",
        "## 来源与状态",
        f"来源: {document.source}",
        f"SHA256: {document.sha256}",
        f"字节数: {document.size}；文本编码: {document.encoding or '未确认'}；来源稳定: {selection.report.stable}",
        f"状态: {states[document.status]}；格式: {document.kind or '未识别'}；退出码: {selection.report.exit_code}",
        "该结构匹配仅依据文件声明，不证明文件由某个工具生成。离线方案不证明实际持有、可装备或物品效果。",
        f"全部记录: {len(document.records)}；匹配: {len(selection.records)}；搜索: {_visible(selection.query)}。全部诊断与来源始终保留。",
        "",
        "## 完整记录与槽位",
    ]
    if not selection.records:
        lines.append(
            "没有匹配方案；清空搜索查看全部记录，或选择包含 schema=1 与 codes/records 的原始方案 JSON。确认的空 records 数组表示零记录。"
        )
    for record in selection.records:
        lines.extend(
            [
                "",
                f"### 方案 {record.ordinal} · {_visible(record.name)}",
                f"格式: {record.kind}；状态: {record.state}；来源: {record.path}；JSON节点: {record.node}",
                f"单位: {_visible(record.unit_code)} ({record.unit_state})；requires_any_slot 原声明: {_visible(record.requires_any_slot)}",
            ]
        )
        for slot in record.slots:
            start, end = document.byte_spans[slot.node]
            lines.append(
                f"槽位 {slot.index} · 声明组 {slot.sequence}: 物品 {_visible(slot.code)}；类型 {slot.type_literal if slot.type_literal is not None else '未声明/未确认'}；数量 {slot.charge_literal if slot.charge_literal is not None else '未声明/未确认'}；状态 {slot.state}；源字节 {start}:{end}；JSON节点 {slot.node}"
            )
        for charge in record.charges:
            lines.append(
                f"数量原声明 · 组 {charge.sequence} / 项 {charge.index}: {charge.literal if charge.literal is not None else '未确认'}；状态 {charge.state}；JSON节点 {charge.node}"
            )
        lines.extend(("完整原记录:", document.raw_token(record.node)))
    lines.extend(("", "## 全部诊断"))
    lines.extend(selection.report.source_diagnostics)
    for note in document.diagnostics:
        lines.append(
            f"[{note.severity}/{note.code}] {note.path}: {note.message} · JSON节点 {note.node}"
        )
    if not document.diagnostics and not selection.report.source_diagnostics:
        lines.append("未发现声明结构或来源稳定性问题；此结论不确认游戏效果。")
    lines.extend(
        (
            "",
            "## 完整来源与证据",
            "下列报告保留全部原始字节、JSON、重复键、扩展字段、数量 token 及字符/字节位置；筛选不删除来源证据。",
            json.dumps(selection.to_dict(), ensure_ascii=False, indent=2),
            "",
            "## 继续查证",
            "更换或刷新原始方案文件可重新检查；用对应地图的 item 查询核对物品信息。导出是证据报告，不是可导入装备方案。",
        )
    )
    return "\n\n".join(lines) + "\n"


def loadout_report_payload(selection: LoadoutSelection, format: str = "json") -> str:
    if format == "json":
        return json.dumps(selection.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if format == "md":
        return format_loadout_report(selection)
    if format != "tsv":
        raise ValueError(f"未知报告格式 {format}；请选择 json、md 或 tsv。")
    document = selection.report.document
    rows = [
        (
            "记录类型",
            "方案序号",
            "名称",
            "单位代码",
            "声明组",
            "槽位",
            "物品代码",
            "类型原文",
            "数量原文",
            "状态",
            "完整证据JSON",
        )
    ]
    for record in selection.records:
        rows.append(
            (
                "record",
                str(record.ordinal),
                record.name or "",
                record.unit_code or "",
                "",
                "",
                "",
                "",
                "",
                record.state,
                json.dumps(
                    {"record": asdict(record), "raw": document.raw_token(record.node)},
                    ensure_ascii=False,
                ),
            )
        )
        for slot in record.slots:
            rows.append(
                (
                    "slot",
                    str(record.ordinal),
                    record.name or "",
                    record.unit_code or "",
                    str(slot.sequence),
                    str(slot.index),
                    slot.code or "",
                    slot.type_literal or "",
                    slot.charge_literal or "",
                    slot.state,
                    json.dumps(asdict(slot), ensure_ascii=False),
                )
            )
    rows.append(
        (
            "complete_source",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            document.status,
            json.dumps(selection.to_dict(), ensure_ascii=False),
        )
    )
    return format_tsv_rows(rows)


def write_loadout_export(
    path: str | Path, selection: LoadoutSelection, format: str = "json"
) -> Path:
    """Publish only a new complete report; re-prove input and output byte identity."""
    validate_output_root(os.fspath(path))
    destination = Path(os.path.abspath(path))
    destination_io = native_output_path(str(destination))
    if os.path.lexists(destination_io):
        raise ValueError("导出路径必须是不存在的新文件；原方案和已有报告保持不变。")
    revalidate_loadout_source(selection.report)
    proof = report_parent_proof(destination)
    data = loadout_report_payload(selection, format).encode("utf-8")
    revalidate_loadout_source(selection.report)
    digest = hashlib.sha256(data).hexdigest()
    with _parents(Path(destination_io)):
        descriptor, stage = tempfile.mkstemp(
            prefix=".gamexray-loadout-",
            suffix=".tmp",
            dir=native_output_path(str(destination.parent)),
        )
        owned = os.fstat(descriptor)
        owned_identity = owned.st_dev, owned.st_ino
        completed = created = False
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            expected = report_metadata(os.fstat(descriptor))
            if expected[2] != len(data) or report_parent_proof(destination) != proof:
                raise OSError("报告长度或输出目录变化；未确认发布。")
            _, named = require_report_payload(stage, descriptor, expected, digest)
            revalidate_loadout_source(selection.report)
            os.link(stage, destination_io)
            created = True
            linked, _ = require_report_payload(
                stage,
                descriptor,
                expected,
                digest,
                expected_named=named,
                allow_link_change_time=True,
            )
            require_report_payload(
                destination_io, descriptor, linked, digest, expected_named=named
            )
            if report_parent_proof(destination) != proof:
                raise OSError("报告父目录在发布时变化。")
            revalidate_loadout_source(selection.report)
            completed = True
        finally:
            primary = sys.exc_info()[1]
            os.close(descriptor)
            retained = cleanup_report_paths(
                (destination_io, stage) if created and not completed else (stage,),
                owned_identity,
            )
            if retained:
                message = "; ".join(retained)
                raise OSError(
                    f"{primary}; {message}" if primary is not None else message
                ) from primary
    return destination


__all__ = (
    "LoadoutReport",
    "LoadoutSelection",
    "format_loadout_report",
    "loadout_report_payload",
    "read_loadout_report",
    "revalidate_loadout_source",
    "select_loadout_report",
    "write_loadout_export",
)

"""Whole-file save queries, full diagnostics and source-preserving report export."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path

from .bounded_file import sha256_regular_file
from .pack_query_options import query_limit_error
from .real_save_files import (
    RealSaveFile,
    RealSaveReport,
    SaveFileKind,
    format_real_save_report_tsv,
)
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteResult, SafeWriteStatus
from .save_source_paths import iter_save_source_files, save_source_path_error
from .search import compile_query


@dataclass(frozen=True, slots=True)
class SaveReportSelection:
    """A view over complete file records; selection never trims diagnostics."""

    report: RealSaveReport
    files: tuple[RealSaveFile, ...]
    total_files: int
    matched_files: int
    omitted_files: int
    diagnostics: tuple[str, ...]
    query: str = ""
    kind: str = ""
    limit: int = 0

    def to_dict(self) -> dict[str, object]:
        selected = replace(
            self.report,
            files=tuple(record for record in self.files if record.source_stable),
            unverified_files=tuple(
                record for record in self.files if not record.source_stable
            ),
        ).to_dict()
        selected["diagnostics"] = list(self.diagnostics)
        selected["selection"] = {
            "query": self.query,
            "kind": self.kind,
            "limit": self.limit,
            "total_files": self.total_files,
            "matched_files": self.matched_files,
            "selected_files": len(self.files),
            "omitted_files": self.omitted_files,
            "unit": "whole-file-record",
        }
        return selected


@dataclass(frozen=True, slots=True)
class SaveReportWriteResult:
    """The published file and the exact source state represented in its bytes."""

    result: SafeWriteResult
    selection: SaveReportSelection

    @property
    def status(self) -> SafeWriteStatus:
        return self.result.status

    @property
    def path(self) -> str:
        return self.result.path

    @property
    def size(self) -> int:
        return self.result.size

    @property
    def error(self) -> str:
        return self.result.error


def _leaf_fields(value: object) -> Iterator[str]:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            for key, child in current.items():
                yield str(key)
                pending.append(child)
        elif isinstance(current, (tuple, list)):
            pending.extend(reversed(current))
        elif current is not None:
            yield str(current)


def _records(record: RealSaveFile) -> Iterator[RealSaveFile]:
    pending = [record]
    while pending:
        current = pending.pop()
        yield current
        pending.extend(reversed(current.members))


def save_report_diagnostics(report: RealSaveReport) -> tuple[str, ...]:
    """Keep every source/container/cache diagnostic, including filtered files."""
    output = list(report.warnings)
    for top in (*report.files, *report.unverified_files):
        for record in _records(top):
            pending: list[tuple[str, object]] = [("", record._record_dict())]
            while pending:
                location, value = pending.pop()
                if isinstance(value, dict):
                    for key, child in value.items():
                        path = f"{location}.{key}" if location else str(key)
                        if key == "diagnostics" or key == "diagnostic" and location:
                            output.extend(
                                f"{record.relative_path}: {path}: {note}"
                                for note in _leaf_fields(child)
                                if note
                            )
                        else:
                            pending.append((path, child))
                elif isinstance(value, (tuple, list)):
                    pending.extend(
                        (f"{location}[{index}]", child)
                        for index, child in reversed(tuple(enumerate(value)))
                    )
            if not record.complete and not record.diagnostics:
                output.append(f"{record.relative_path}: {record.diagnostic}")
            for unknown in record.unknown_ranges:
                output.append(f"{record.relative_path}: unknown {unknown}")
    return tuple(dict.fromkeys(output))


def select_save_report(
    report: RealSaveReport,
    query: str = "",
    kind: str = "",
    limit: int = 0,
) -> SaveReportSelection:
    """Compile once and match each complete file's separate evidence fields."""
    if problem := query_limit_error(limit):
        raise ValueError(problem)
    kind = kind.strip().lower()
    if kind and kind not in {item.value for item in SaveFileKind}:
        raise ValueError(f"未知存档类型：{kind}")
    compiled = compile_query(query)
    if query.strip() and compiled.is_empty:
        raise ValueError('查询表达式没有关键词；可用 &&、||、%、括号或 ="精准词"。')
    all_files = (*report.files, *report.unverified_files)
    matches: list[RealSaveFile] = []
    for record in all_files:
        if kind and record.kind.value != kind:
            continue
        if compiled.score_fields(tuple(_leaf_fields(record.to_dict()))) is not None:
            matches.append(record)
    selected = tuple(matches[:limit] if limit else matches)
    return SaveReportSelection(
        report,
        selected,
        len(all_files),
        len(matches),
        len(matches) - len(selected),
        save_report_diagnostics(report),
        query,
        kind,
        limit,
    )


def verify_save_report_sources(report: RealSaveReport) -> RealSaveReport:
    """Rehash all inputs before a later export, preserving the original snapshot."""
    warnings = list(report.warnings)
    source = Path(report.source).absolute()
    root = source if report.source_is_directory else source.parent
    confirmed: list[RealSaveFile] = []
    unverified = list(report.unverified_files)
    for record in report.files:
        path = root / record.relative_path
        try:
            if problem := save_source_path_error(path):
                raise ValueError(problem)
            metadata = path.lstat()
            identity = record.source_identity
            if identity is not None and tuple(
                identity[key]
                for key in ("device", "inode", "size", "mtime_ns", "ctime_ns", "mode")
            ) != (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
                metadata.st_mode,
            ):
                raise ValueError("来源身份或元数据改变")
            digest, _identity = sha256_regular_file(path)
            if digest != record.sha256:
                raise ValueError("完整输入 SHA256 改变")
            if problem := save_source_path_error(path):
                raise ValueError(problem)
        except (OSError, ValueError) as exc:
            note = f"导出前来源改变或不可读：{record.relative_path} ({exc})；保留原读取证据，需刷新。"
            warnings.append(note)
            unverified.append(
                replace(
                    record,
                    complete=False,
                    source_stable=False,
                    diagnostics=(*record.diagnostics, note),
                )
            )
        else:
            confirmed.append(record)
    candidates, issues = iter_save_source_files(source)
    warnings.extend(issues)
    names = tuple(path.relative_to(root).as_posix() for path in candidates)
    if report.source_files and names != report.source_files:
        warnings.append("导出前来源文件清单改变；请刷新后重新分析。")
    inventory_complete = report.inventory_complete and not warnings
    return replace(
        report,
        files=tuple(confirmed),
        unverified_files=tuple(unverified),
        warnings=tuple(dict.fromkeys(warnings)),
        inventory_complete=inventory_complete,
        complete=report.complete and inventory_complete,
    )


def save_output_error(report: RealSaveReport, output: str | Path) -> str:
    """Exports must never replace a source, its physical alias, or its map."""
    destination = Path(output).absolute()
    source = Path(report.source).absolute()
    if report.source_is_directory:
        try:
            destination.resolve().relative_to(source.resolve())
        except ValueError:
            pass
        else:
            return "报告输出必须位于来源目录之外，以保留存档和完整来源清单。"
    root = source if report.source_is_directory else source.parent
    protected = [source, *(root / name for name in report.source_files)]
    if report.map_path:
        protected.append(Path(report.map_path).absolute())
    for path in protected:
        if os.path.normcase(str(destination.resolve())) == os.path.normcase(
            str(path.resolve())
        ):
            return f"报告不能覆盖来源文件：{path}"
        try:
            if destination.exists() and path.exists() and destination.samefile(path):
                return f"报告不能覆盖来源文件的物理别名：{path}"
        except OSError as exc:
            return f"无法验证输出与来源身份：{exc}"
    current = destination.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    return save_source_path_error(current)


def format_save_file_details(record: RealSaveFile) -> str:
    """A full, standalone file view; nested archives use the flat parent index."""
    state = "完整" if record.complete else "未完整解析"
    return (
        f"# {record.relative_path}\n\n"
        f"## 来源与状态\n\n类型: {record.kind.value}\n大小: {record.size}\n"
        f"SHA256: {record.sha256}\n状态: {state}\n来源稳定: {record.source_stable}\n"
        f"诊断: {record.diagnostic}\n\n"
        "## 全部诊断\n\n"
        + "\n\n".join(
            save_report_diagnostics(RealSaveReport("", (record,), ()))
            or ("未发现结构诊断；语义以字段状态和原始来源为准。",)
        )
        + "\n\n"
        "## 完整结构与记录\n\n"
        "下列字段保留载体、全部记录、原始字节证据、偏移、编码和未知范围；"
        "命令文本只是静态候选，不证明密码有效或当前英雄状态。\n\n"
        "```json\n"
        + json.dumps(record.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)
        + "\n```\n"
    )


def format_save_report_markdown(selection: SaveReportSelection) -> str:
    report = selection.report
    output = [
        "# 离线存档工作台",
        f"来源: {report.source}",
        f"状态: {'完整' if report.complete else '未完成，保留已确认的证据'}",
        "地图关联: "
        + (
            report.map_path
            if report.map_associated
            else "未做地图关联；可选择地图后重新分析。"
        ),
        f"文件: 共 {selection.total_files}，匹配 {selection.matched_files}，显示 {len(selection.files)}，显式限制省略 {selection.omitted_files}。",
        "## 全部诊断",
        *(
            selection.diagnostics
            or ("来源复验未发现问题；私有格式的语义仍以各记录状态为准。",)
        ),
    ]
    if not selection.files:
        output.append(
            "没有匹配文件；清空搜索或类型筛选查看全部来源，也可选择其他存档目录。"
        )
    output.extend(format_save_file_details(record) for record in selection.files)
    return "\n\n".join(output) + "\n"


def save_report_payload(selection: SaveReportSelection, format: str = "json") -> str:
    if format == "json":
        return (
            json.dumps(
                selection.to_dict(), ensure_ascii=False, indent=2, allow_nan=False
            )
            + "\n"
        )
    if format == "md":
        return format_save_report_markdown(selection)
    if format == "tsv":
        report = replace(
            selection.report,
            files=tuple(row for row in selection.files if row.source_stable),
            unverified_files=tuple(
                row for row in selection.files if not row.source_stable
            ),
            warnings=selection.diagnostics,
        )
        return (
            format_real_save_report_tsv(report)
            + f"[筛选]\t匹配 {selection.matched_files}，显示 {len(selection.files)}，省略 {selection.omitted_files}\n"
        )
    raise ValueError(f"未知报告格式：{format}")


def write_save_report(
    selection: SaveReportSelection, output: str | Path, format: str = "json"
) -> SaveReportWriteResult:
    """Prove full source bytes around rendering, then publish outside the source."""
    if problem := save_output_error(selection.report, output):
        raise ValueError(problem)

    def refresh(previous: SaveReportSelection) -> SaveReportSelection:
        report = verify_save_report_sources(previous.report)
        records = {
            (row.relative_path, row.sha256): row
            for row in (*report.files, *report.unverified_files)
        }
        return replace(
            previous,
            report=report,
            files=tuple(
                records[(row.relative_path, row.sha256)] for row in previous.files
            ),
            diagnostics=save_report_diagnostics(report),
        )

    selection = refresh(selection)
    for _attempt in range(2):
        payload = save_report_payload(selection, format)
        verified = refresh(selection)
        if verified.report == selection.report:
            break
        selection = verified
    else:
        raise ValueError(
            "来源在报告序列化期间持续变化；已拒绝发布报告。原目标保持不变，请等来源稳定后刷新重试。"
        )
    if problem := save_output_error(selection.report, output):
        raise ValueError(problem)
    destination = Path(output).absolute()
    return SaveReportWriteResult(
        write_text_safely(str(destination.parent), destination.name, payload),
        selection,
    )


__all__ = (
    "SaveReportSelection",
    "SaveReportWriteResult",
    "format_save_file_details",
    "format_save_report_markdown",
    "save_output_error",
    "save_report_diagnostics",
    "save_report_payload",
    "select_save_report",
    "verify_save_report_sources",
    "write_save_report",
)

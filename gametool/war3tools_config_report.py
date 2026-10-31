"""Whole-record configuration queries and independently published reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from .batch_tsv import format_tsv_rows
from .hotkey_config_cli import (
    _cleanup_report_paths,
    _parent_proof,
    _report_metadata,
    _require_report_payload,
)
from .live_report_io import _parents
from .search import compile_query
from .war3tools_config import revalidate_war3tools_inspection
from .war3tools_config_models import (
    War3ToolsInspection,
    War3ToolsRecord,
    War3ToolsSetting,
)
from .windows_output_paths import native_output_path, validate_output_root


_CATEGORY_NAMES = {
    "camera": "镜头 相机",
    "cooldown": "冷却 技能 CD",
    "features": "功能 显示",
    "keymapping": "改键 快捷键 按键映射",
    "minimap": "小地图 信号",
    "settings": "常规设置",
    "ui": "界面 外观",
    "ground_item_highlight": "地面物品 高亮",
    "unknown": "未知配置",
}


@dataclass(frozen=True, slots=True)
class War3ToolsSelectedRecord:
    source: str
    relative_path: str
    record: War3ToolsRecord
    setting: War3ToolsSetting | None = None


@dataclass(frozen=True, slots=True)
class War3ToolsSelection:
    inspection: War3ToolsInspection
    records: tuple[War3ToolsSelectedRecord, ...]
    query: str = ""

    @property
    def exit_code(self) -> int:
        return self.inspection.exit_code

    def to_dict(self) -> dict[str, object]:
        return war3tools_report_to_dict(self)


def select_war3tools_report(
    inspection: War3ToolsInspection, query: str = ""
) -> War3ToolsSelection:
    """Evaluate the shared Boolean language once per complete physical record."""
    compiled = compile_query(query)
    if query.strip() and compiled.is_empty:
        raise ValueError(
            "查询表达式没有关键词；清空可列出全部，或使用 &&、||、%% 与括号。"
        )
    records: list[War3ToolsSelectedRecord] = []
    for file in inspection.files:
        settings = {setting.line: setting for setting in file.settings}
        for record in file.records:
            setting = settings.get(record.line)
            fields = [
                file.source.relative_path,
                record.kind,
                record.section,
                record.key or "",
                record.value or "",
                record.raw,
            ]
            if setting is not None:
                fields.extend(
                    (
                        setting.category,
                        _CATEGORY_NAMES.get(setting.category, ""),
                        setting.kind,
                        setting.label,
                        setting.state,
                        str(setting.interpreted)
                        if setting.interpreted is not None
                        else "",
                        setting.basis,
                    )
                )
            if compiled.score_fields(fields) is not None:
                records.append(
                    War3ToolsSelectedRecord(
                        file.source.path, file.source.relative_path, record, setting
                    )
                )
    return War3ToolsSelection(inspection, tuple(records), query)


def revalidate_war3tools_selection(
    selection: War3ToolsSelection,
) -> War3ToolsSelection:
    """Preserve selected evidence while attaching the final source proof."""
    return replace(
        selection,
        inspection=revalidate_war3tools_inspection(selection.inspection),
    )


def war3tools_report_to_dict(selection: War3ToolsSelection) -> dict[str, object]:
    result = selection.inspection.to_dict()
    result["selection"] = {
        "query": selection.query,
        "total_records": selection.inspection.records_total,
        "matched_records": len(selection.records),
        "records": [asdict(record) for record in selection.records],
    }
    return result


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def format_war3tools_report(selection: War3ToolsSelection) -> str:
    """Keep filtered records distinct from the full source and diagnostics."""
    result = selection.inspection
    lines = [
        "GameXRay · War3Tools 离线配置总览",
        result.notice,
        f"输入: {result.path}",
        f"配置文件 {result.files_total}；声明设置 {result.settings_total}；原文记录 {result.records_total}",
        f"来源稳定: {result.stable}；检查完整: {result.inspection_complete}；退出码: {result.exit_code}",
        f"查询: {_json(selection.query)}；匹配完整记录 {len(selection.records)}",
        "",
        "== 查询结果 ==",
    ]
    for row in selection.records:
        record = row.record
        lines.append(
            f"{row.relative_path}:{record.line} · {record.kind} · "
            f"字节 [{record.byte_offset}, {record.byte_end})"
        )
        if row.setting is not None:
            setting = row.setting
            lines.append(
                f"  [{setting.section}] {setting.label} ({setting.key}) = "
                f"{_json(setting.value)} · {_CATEGORY_NAMES.get(setting.category, setting.category)}/{setting.state}"
            )
            if setting.interpreted is not None:
                lines.append(f"  声明解释: {_json(setting.interpreted)}")
        lines.append("  完整原文: " + _json(record.raw))
    if not selection.records:
        lines.append(
            "未匹配记录；可清空查询列出全部，或按文件名、功能名、节名、键和值搜索。"
        )
    lines.extend(("", "== 全部按键声明与冲突 =="))
    lines.extend(_json(asdict(binding)) for binding in result.bindings)
    lines.extend(_json(asdict(conflict)) for conflict in result.conflicts)
    if not result.bindings:
        lines.append("没有取得可识别的按键声明；未知配置仍保留在完整原文中。")
    if not result.conflicts:
        lines.append("已识别声明中未发现同键冲突；这不证明运行时没有冲突。")
    lines.extend(("", "== 完整诊断（不受查询筛选影响） =="))
    lines.extend(_json(asdict(diagnostic)) for diagnostic in result.diagnostics)
    if not result.diagnostics:
        lines.append("无来源或解析诊断。")
    lines.extend(("", "== 全部文件库存 =="))
    lines.extend(_json(asdict(entry)) for entry in result.inventory)
    lines.extend(("", "== 完整来源（证据保留，不受查询筛选影响） =="))
    for file in result.files:
        source = file.source
        lines.extend(
            (
                f"来源: {source.relative_path}",
                f"SHA-256: {source.sha256}；字节: {source.size}；编码: {source.encoding}",
                "原文（JSON 字符串保留全部换行及控制字符）:"
                if source.raw_text is not None
                else "未解码来源；完整原始字节 Base64:",
                _json(source.raw_text)
                if source.raw_text is not None
                else source.raw_base64,
                "完整来源元数据及原始字节（含 BOM）:",
                _json(asdict(source)),
            )
        )
    lines.extend(
        (
            "",
            "== 使用与导出 ==",
            "配置含义未知或冲突时保留所有声明，不选择首项或末项代替游戏实际行为。",
            "JSON / TSV 报告含完整来源字节与记录；报告不是可直接导入的插件配置。",
            "目录分析的报告请选择来源目录之外的新文件名，避免改变被分析的配置集合。",
        )
    )
    return "\n".join(lines) + "\n"


def war3tools_report_payload(selection: War3ToolsSelection, format: str) -> str:
    if format == "json":
        return json.dumps(selection.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if format == "md":
        return format_war3tools_report(selection)
    if format != "tsv":
        raise ValueError("未知报告格式；请选择 json、md 或 tsv。")
    rows = [("类型", "来源", "行号", "节", "键", "值", "原文", "完整证据JSON")]
    for row in selection.records:
        record = row.record
        rows.append(
            (
                record.kind,
                row.relative_path,
                str(record.line),
                record.section,
                record.key or "",
                record.value or "",
                record.raw,
                _json(asdict(row)),
            )
        )
    rows.append(("complete_source", "", "", "", "", "", "", _json(selection.to_dict())))
    return format_tsv_rows(rows)


def _require_stable(selection: War3ToolsSelection) -> None:
    checked = revalidate_war3tools_selection(selection)
    if not checked.inspection.stable:
        raise ValueError("配置来源变化或不可读；保留旧快照，请重新读取后再导出。")


def write_war3tools_export(
    path: str | Path, selection: War3ToolsSelection, format: str = "json"
) -> Path:
    """Publish a new report only, with source and output identities re-proved."""
    validate_output_root(os.fspath(path))
    destination = Path(os.path.abspath(path))
    destination_io = native_output_path(str(destination))
    if os.path.lexists(destination_io):
        raise ValueError("导出路径必须是不存在的新文件；不能覆盖配置或已有报告。")
    source = Path(os.path.abspath(selection.inspection.path))
    if (
        selection.inspection.selection_kind == "directory"
        and destination.is_relative_to(source)
    ):
        raise ValueError("报告必须写到所选来源目录之外，避免改变配置文件库存。")
    _require_stable(selection)
    proof = _parent_proof(destination)
    if selection.inspection.selection_kind == "directory":
        root_identity = selection.inspection.root_identity
        if len(root_identity) >= 2 and any(
            (device, inode) == root_identity[:2] for _name, device, inode in proof
        ):
            raise ValueError("报告父目录是来源目录的物理别名；请选择独立的新文件位置。")
    data = war3tools_report_payload(selection, format).encode("utf-8")
    _require_stable(selection)
    digest = hashlib.sha256(data).hexdigest()
    with _parents(Path(destination_io)):
        descriptor, stage = tempfile.mkstemp(
            prefix=".gamexray-war3tools-",
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
            expected = _report_metadata(os.fstat(descriptor))
            if expected[2] != len(data) or _parent_proof(destination) != proof:
                raise OSError("报告长度或输出目录变化；未确认发布。")
            _, named = _require_report_payload(stage, descriptor, expected, digest)
            _require_stable(selection)
            os.link(stage, destination_io)
            created = True
            linked, _ = _require_report_payload(
                stage,
                descriptor,
                expected,
                digest,
                expected_named=named,
                allow_link_change_time=True,
            )
            _require_report_payload(
                destination_io, descriptor, linked, digest, expected_named=named
            )
            if _parent_proof(destination) != proof:
                raise OSError("报告父目录在发布时变化。")
            _require_stable(selection)
            completed = True
        finally:
            primary = sys.exc_info()[1]
            os.close(descriptor)
            retained = _cleanup_report_paths(
                (destination_io, stage) if created and not completed else (stage,),
                owned_identity,
            )
            if retained:
                message = "; ".join(retained)
                raise OSError(
                    f"{primary}; {message}" if primary is not None else message
                ) from primary
    return destination

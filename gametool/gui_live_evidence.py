"""Pure live-dialog presentation and handoffs; never access a game or Tk."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
import math

from .live_report_json import (
    ExactJsonNumber,
    format_report_json,
    integer_to_text,
    parse_report_json,
    values_equal,
)
from .object_codes import encode_object_id_query, valid_object_code


@dataclass(frozen=True, slots=True)
class ParsedLiveOutput:
    report: dict[str, object] | None
    json_text: str = ""
    diagnostic: str = ""


@dataclass(frozen=True, slots=True)
class LiveDialogMemory:
    """Session content only; reports never become persistent implicit captures."""

    report: Mapping[str, object] | None
    source: str
    raw_text: str
    comparison_text: str
    selected_unit: Mapping[str, object] | None
    selected_item: Mapping[str, object] | None
    tab: str


def parse_live_output(text: str) -> ParsedLiveOutput:
    """Decode the complete final root document, retaining its exact source text.

    The live CLI puts its indented JSON root at the start of a line. Select that
    root once and validate its entire tail; a malformed outer report must never
    become a plausible nested unit or a later fragment.
    """
    start = next(
        (
            i
            for i, char in enumerate(text)
            if char == "{" and (i == 0 or text[i - 1] in "\r\n")
        ),
        -1,
    )
    if start < 0:
        return ParsedLiveOutput(
            None, diagnostic="输出没有完整的结构化报告；可查看完整输出或重新探针。"
        )
    raw = text[start:].strip()
    try:
        value: object = parse_report_json(raw)
    except (ValueError, RecursionError) as exc:
        return ParsedLiveOutput(
            None, diagnostic=f"结构化报告无法解析: {exc}；完整输出仍可复制、导出。"
        )
    if not isinstance(value, dict):
        return ParsedLiveOutput(
            None, diagnostic="结构化报告根必须是对象；请查看完整输出。"
        )
    return ParsedLiveOutput(value, raw)


def _records(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(row for row in value if isinstance(row, Mapping))


def selected_records(report: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    """A declared empty selection is authoritative, including on partial reports."""
    if "selected_units" in report:
        return _records(report["selected_units"])
    old = report.get("selected_unit")
    return (old,) if isinstance(old, Mapping) else ()


def item_records(unit: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return _records(unit.get("items"))


def display_value(value: object) -> str:
    if value is None:
        return "未知 / 未提供"
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, list)):
        return format_report_json(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return integer_to_text(value)
    return str(value)


def address_text(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return f"0x{value:X}"
    return display_value(value)


def record_label(
    record: Mapping[str, object], index: int, *, item: bool = False
) -> str:
    name = record.get("name") if item else record.get("unit", record.get("name"))
    slot = f"槽 {display_value(record.get('slot'))} · " if item else ""
    return f"{index + 1}. {slot}{display_value(name)} [{display_value(record.get('code'))}] · {address_text(record.get('addr'))}"


def selection_status(report: Mapping[str, object]) -> str:
    rows = selected_records(report)
    complete = report.get("selection_complete")
    raw = report.get("selected_units")
    invalid = "selected_units" in report and (
        not isinstance(raw, list) or len(raw) != len(rows)
    )
    if invalid:
        state = f"选中列表含无效记录 · 已知 {len(rows)} 个单位，完整范围未知"
    elif complete is True and not rows:
        state = "当前没有选中单位"
    elif complete is True:
        state = f"完整选中列表 · {len(rows)} 个单位"
    elif complete is False:
        state = f"选中列表不完整 / 不可用 · 已知 {len(rows)} 个单位"
    else:
        state = f"选中范围未知 · 已知 {len(rows)} 个单位（旧报告或未提供完整性）"
    if report.get("input_error"):
        state += " · 输入/进程读取失败"
    return state


def _same_process(old: Mapping[str, object], new: Mapping[str, object]) -> bool:
    if old is new:
        return True
    left, right = old.get("process_identity"), new.get("process_identity")
    # A PID alone is reused by Windows; it cannot prove an instance identity.
    return isinstance(left, Mapping) and bool(left) and values_equal(left, right)


def preferred_selection(
    previous_report: Mapping[str, object] | None,
    previous_unit: Mapping[str, object] | None,
    report: Mapping[str, object],
) -> int | None:
    rows = selected_records(report)
    if not rows:
        return None
    if (
        previous_report is not None
        and previous_unit is not None
        and _same_process(previous_report, report)
    ):
        addr = previous_unit.get("addr")
        if addr is not None:
            matches = [
                index
                for index, row in enumerate(rows)
                if row.get("addr") == addr
                and row.get("code") == previous_unit.get("code")
            ]
            if len(matches) == 1:
                return matches[0]
    return 0


def _evidence_lines(value: object) -> list[str]:
    if value is None:
        return ["未提供逐字段证据；可在完整输出检查读取策略、档案和诊断。"]
    entries = (
        list(value.items())
        if isinstance(value, Mapping)
        else list(enumerate(value))
        if isinstance(value, list)
        else [("evidence", value)]
    )
    if not entries:
        return ["没有逐字段证据；不将未知字段显示为零。"]
    lines: list[str] = []
    for fallback, entry in entries:
        if not isinstance(entry, Mapping):
            lines.append(f"{fallback}: {display_value(entry)}")
            continue
        lines.append(
            f"{display_value(entry.get('label', entry.get('key', fallback)))} [{display_value(entry.get('key', fallback))}]"
        )
        for key, label in (
            ("value", "值"),
            ("value_type", "类型"),
            ("state", "状态"),
            ("source", "来源"),
            ("address", "地址"),
            ("diagnostics", "诊断"),
        ):
            cell = entry.get(key)
            lines.append(
                f"  {label}: {address_text(cell) if key == 'address' else display_value(cell)}"
            )
        for key, cell in entry.items():
            if key not in {
                "label",
                "key",
                "value",
                "value_type",
                "state",
                "source",
                "address",
                "diagnostics",
            }:
                lines.append(f"  {key}: {display_value(cell)}")
    return lines


def _resource_lines(report: Mapping[str, object]) -> list[str]:
    lines: list[str] = []
    for key, complete, title, explanation in (
        (
            "resources",
            "resources_complete",
            "资源扫描候选（未归属玩家）",
            "扫描候选保留精确数值；候选地址不证明所属玩家。",
        ),
        (
            "player_resources",
            "player_resources_complete",
            "按玩家槽的资源链证据",
            "槽位与字段状态以各自证据为准；未确认布局不证明玩家归属。",
        ),
    ):
        if key not in report:
            continue
        rows = report[key]
        lines += [
            "",
            f"【{title}】",
            explanation,
            "完整性: " + display_value(report.get(complete)),
        ]
        if not isinstance(rows, list):
            lines.append("未返回记录: " + display_value(rows))
            continue
        if not rows:
            lines.append("没有返回资源记录；请结合完整性与报告诊断判断。")
        for index, row in enumerate(rows, 1):
            lines.append(f"记录 {index}")
            if not isinstance(row, Mapping):
                lines.append("原始记录: " + display_value(row))
                continue
            lines += [
                f"  {name}: {address_text(value) if name == 'addr' else display_value(value)}"
                for name, value in row.items()
                if name != "evidence"
            ]
            lines.extend(_evidence_lines(row.get("evidence")))
    if report.get("player_rows") is not None:
        lines += ["", "【玩家资源摘要】", display_value(report["player_rows"])]
    return lines


def format_live_details(
    report: Mapping[str, object],
    unit: Mapping[str, object] | None,
    item: Mapping[str, object] | None = None,
) -> str:
    lines = ["【报告与选择状态】", selection_status(report)]
    for key, label in (
        ("captured_at", "捕获时间 UTC"),
        ("capture_finished_at", "捕获结束 UTC"),
        ("pid", "PID"),
        ("version", "游戏版本"),
        ("process_identity", "进程身份"),
        ("strategy_used", "读取策略"),
    ):
        lines.append(f"{label}: {display_value(report.get(key))}")
    lines += [
        "",
        "【选择诊断】",
        display_value(report.get("selection_diagnostics", [])),
        "选择链证据: " + display_value(report.get("selection_evidence")),
        "",
        "【报告诊断】",
        display_value(report.get("notes", [])),
    ]
    if unit is None:
        lines += [
            "",
            "【单位】",
            "没有可展示的选中实例。可重新探针、打开已保存报告，或查看完整输出中的档案/权限诊断。",
        ]
    else:
        lines += ["", "【单位】"]
        for key, label in (
            ("unit", "名称"),
            ("code", "四码"),
            ("owner", "所属玩家"),
            ("addr", "对象地址"),
            ("x", "X"),
            ("y", "Y"),
        ):
            lines.append(
                f"{label}: {address_text(unit.get(key)) if key == 'addr' else display_value(unit.get(key))}"
            )
        for key, value in unit.items():
            if key not in {
                "unit",
                "code",
                "owner",
                "addr",
                "x",
                "y",
                "items",
                "evidence",
            }:
                lines.append(f"{key}: {display_value(value)}")
        lines += [
            "",
            "【单位字段证据】",
            *_evidence_lines(unit.get("evidence")),
            "",
            "【完整背包】",
        ]
        items = item_records(unit)
        lines += [
            record_label(row, index, item=True) for index, row in enumerate(items)
        ]
        if not items:
            lines.append("本实例没有返回物品记录；是否完整以报告证据与诊断为准。")
        raw_items = unit.get("items")
        if not isinstance(raw_items, list) or len(raw_items) != len(items):
            lines.append("原始背包记录: " + display_value(raw_items))
    if item is not None:
        lines += ["", "【当前物品】"]
        lines += [
            f"{key}: {address_text(value) if key == 'addr' else display_value(value)}"
            for key, value in item.items()
            if key != "evidence"
        ]
        lines += ["", "【物品字段证据】", *_evidence_lines(item.get("evidence"))]
    if "evidence" in report:
        lines += ["", "【报告字段证据】", *_evidence_lines(report["evidence"])]
    lines.extend(_resource_lines(report))
    return "\n".join(lines)


def object_query(
    record: Mapping[str, object], action: str, *, item: bool = False
) -> str | None:
    code = record.get("code")
    if not isinstance(code, str) or not valid_object_code(code):
        return None
    command = (
        ("item" if item else "units")
        if action == "detail"
        else "drop"
        if action == "drop" or not item
        else "where"
    )
    return f"{command} {encode_object_id_query(code)}"


def _coordinate(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, ExactJsonNumber):
        return str(value)
    if isinstance(value, int):
        return integer_to_text(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    return None


def unit_near_query(unit: Mapping[str, object], radius: str = "500") -> str | None:
    x, y = _coordinate(unit.get("x")), _coordinate(unit.get("y"))
    if x is None or y is None:
        return None
    return f"near {x} {y}" + (f" {radius}" if radius else "")

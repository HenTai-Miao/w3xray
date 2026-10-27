"""Full technology evidence and exact static cost formulas without count expansion."""

from collections.abc import Callable
from decimal import Decimal, DecimalException, Inexact, MAX_EMAX, MIN_EMIN, localcontext
import json
from pathlib import Path
import re
from typing import Protocol

from .pack_query_object_details import (
    ObjectDetailSources,
    ObjectRecord,
    load_object_records,
    render_object_record,
)
from .pack_query_objects import valid_object_code
from .search import compile_query

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_SCALARS = {
    "glvl": "最大等级",
    "gglb": "基础金",
    "gglm": "金增量",
    "glmb": "基础木",
    "glmm": "木增量",
}


class TechDetailSources(ObjectDetailSources, Protocol):
    def _tech_base_fields(self) -> dict[str, dict[str, str]]: ...


def normalize_tech_level(value: str) -> str:
    value = value.strip()
    if (
        not value
        or not value.isascii()
        or not value.isdecimal()
        or not value.strip("0")
    ):
        raise ValueError("--level 需要正整数等级（不设数字上限）。")
    return value.lstrip("0")


def _number(value: str) -> Decimal | None:
    raw = value.strip().removeprefix("'").strip()
    if _NUMBER.fullmatch(raw) is None:
        return None
    try:
        with localcontext():
            result = Decimal(raw)
            return result if result.is_finite() else None
    except DecimalException:
        return None


def _text(value: Decimal) -> str:
    return (
        str(value.to_integral_value())
        if value == value.to_integral_value()
        else str(value)
    )


def _scalar(
    record: ObjectRecord, key: str, base: dict[str, str], notes: list[str]
) -> Decimal | None:
    fields = [field for field in record.evidence.fields if field.key == key]
    if not fields:
        return _number(base.get(_SCALARS[key], ""))
    values = [_number(field.value) for field in fields]
    if any(value is None for value in values) or len(set(values)) != 1:
        reason = "冲突" if len(set(values)) > 1 else "数值未确认"
        notes.append(
            f"  {key} {reason}，未选择其他记录或继承值；保留全部原文: "
            + json.dumps(
                [(field.value, field.source) for field in fields], ensure_ascii=False
            )
        )
        return None
    return values[0]


def _calculate(
    operation: Callable[[], Decimal], operands: tuple[Decimal, ...]
) -> Decimal | None:
    # Precision follows encoded coefficient sizes and the fixed polynomial degree.
    # Wide exponent gaps become exact symbolic expressions instead of rounded values.
    try:
        with localcontext() as context:
            context.prec = 32 + 4 * sum(
                len(value.as_tuple().digits) for value in operands
            )
            context.Emax, context.Emin = MAX_EMAX, MIN_EMIN
            context.traps[Inexact] = True
            result = operation()
            return result if result.is_finite() else None
    except DecimalException:
        return None


def _cost(base: Decimal | None, increment: Decimal | None, level: Decimal) -> str:
    if base is None or increment is None and level != 1:
        return "-"
    if level == 1:
        return _text(base)
    assert increment is not None
    value = _calculate(lambda: base + increment * (level - 1), (base, increment, level))
    return (
        _text(value)
        if value is not None
        else f"({_text(base)}+{_text(increment)}×({_text(level)}-1))"
    )


def _total(base: Decimal | None, increment: Decimal | None, level: Decimal) -> str:
    if level == 0:
        return "0"
    if base is None or increment is None and level != 1:
        return "-"
    if level == 1:
        return _text(base)
    assert increment is not None
    value = _calculate(
        lambda: level * base + increment * level * (level - 1) / 2,
        (base, increment, level),
    )
    return (
        _text(value)
        if value is not None
        else f"({_text(level)}×{_text(base)}+{_text(increment)}×{_text(level)}×({_text(level)}-1)/2)"
    )


def _field_level(key: str, prefix: str) -> str | None:
    if key == prefix:
        return "1"
    if key.startswith(prefix + ":"):
        raw = key[len(prefix) + 1 :]
        if raw and raw.isascii() and raw.isdecimal():
            return raw.lstrip("0") or "0"
    return None


def _sheet(
    record: ObjectRecord, requested: str, sources: TechDetailSources
) -> list[str]:
    row = record.row
    code, name = row[1], sources._clean(row[4]) or row[1]
    base_id = (
        row[3].lower() if not record.from_fields and valid_object_code(row[3]) else ""
    )
    base_fields = sources._tech_base_fields().get(base_id, {}) if base_id else {}
    notes: list[str] = []
    values = {key: _scalar(record, key, base_fields, notes) for key in _SCALARS}
    levels = values["glvl"]
    if levels is not None and (levels < 0 or levels != levels.to_integral_value()):
        notes.append(
            "  glvl 等级数未确认：不是非负整数；保留原始字段，未作为生成记录数量。"
        )
        levels = None
    gold, gold_i, lumber, lumber_i = (
        values[key] for key in ("gglb", "gglm", "glmb", "glmm")
    )
    lines = [f"[{code}] {name}" + (f"  (基础: {base_id})" if base_id else "")]
    if levels is not None:
        lines.append("  最大等级: " + _text(levels))
    bits = []
    for label, initial, step in (("金", gold, gold_i), ("木", lumber, lumber_i)):
        if initial is not None:
            bit = label + " " + _text(initial)
            if step is None:
                bit += "（增量未确认）"
            elif step:
                bit += ("+" if step > 0 else "") + _text(step) + "/级"
            bits.append(bit)
    if bits:
        lines.append("  每级费用: " + ", ".join(bits))
    domain = "1.." + _text(levels) if levels is not None else "正整数，最大等级未确认"
    formula = []
    for label, initial, step in (("金", gold, gold_i), ("木", lumber, lumber_i)):
        formula.append(
            label
            + " "
            + (_text(initial) if initial is not None else "未知")
            + " + "
            + (_text(step) if step is not None else "未知")
            + "×(n-1)"
        )
    lines.append("  费用公式（n=" + domain + "）: " + "；".join(formula))
    lines.append(
        "  公式覆盖声明等级范围；下列费用对应已编码等级及边界，可用 --level N 查询指定等级。"
    )
    points: dict[Decimal, str] = {}
    if levels is not None and levels > 0:
        points[Decimal(1)] = "1"
    for field in record.evidence.fields:
        for prefix in ("gub1", "greq"):
            label = _field_level(field.key, prefix)
            if label is not None and label != "0":
                points.setdefault(Decimal(label), label)
    if levels is not None and levels > 0:
        points.setdefault(levels, _text(levels))
    if requested:
        points = {Decimal(requested): requested}
    if points:
        costs = []
        for number, label in sorted(points.items()):
            point = (
                label
                + "级 金"
                + _cost(gold, gold_i, number)
                + " 木"
                + _cost(lumber, lumber_i, number)
            )
            if levels is None:
                point += "（等级范围未确认，仅为静态公式值）"
            elif number > levels:
                point += "（超出声明最大等级，仅为静态公式值）"
            costs.append(point)
        lines.append(
            ("  所查等级费用: " if requested else "  级费用: ") + " | ".join(costs)
        )
    if levels is not None:
        totals = [
            label + _total(initial, step, levels)
            for label, initial, step in (("金", gold, gold_i), ("木", lumber, lumber_i))
            if initial is not None or levels == 0
        ]
        if totals:
            lines.append("  满级累计: " + " ".join(totals))
    for field in record.evidence.fields:
        label = _field_level(field.key, "gub1")
        if label is not None:
            lines.append(
                "  效果("
                + label
                + "级): "
                + sources._clean(field.value)
                + (" [来源: " + field.source + "]" if field.source else "")
            )
        elif field.key.startswith("gub1:"):
            notes.append("  效果等级未确认，保留完整字段: " + field.key)
        label = _field_level(field.key, "greq")
        if label is not None:
            lines.append(
                "  前置: "
                + label
                + "级←"
                + field.value
                + (" [来源: " + field.source + "]" if field.source else "")
            )
    lines.extend(notes)
    if description := sources._clean(row[6]):
        lines.append("  ID表说明（原始清单证据）: " + description)
    return lines


def split_tech_selector(expression: str) -> tuple[str, str]:
    """Recognize a top-level flag while preserving exact literals and escapes."""
    positions: list[int] = []
    index, depth = 0, 0
    while index < len(expression):
        char = expression[index]
        if (
            char == "="
            and index + 1 < len(expression)
            and expression[index + 1] in ('"', "“", "”")
        ):
            index += 2
            while index < len(expression) and expression[index] not in ('"', "“", "”"):
                index += 1
            index += 1
            continue
        if char == "\\":
            index += 2
            continue
        if char in ("(", "（"):
            depth += 1
        elif char in (")", "）"):
            depth = max(0, depth - 1)
        elif (
            depth == 0
            and (index == 0 or expression[index - 1].isspace())
            and expression.startswith("--level", index)
        ):
            end = index + len("--level")
            if end == len(expression) or expression[end].isspace():
                positions.append(index)
        index += 1
    if not positions:
        return expression, ""
    if len(positions) != 1:
        raise ValueError("--level 只能指定一次")
    position = positions[0]
    tokens = expression[position:].split()
    if len(tokens) != 2:
        raise ValueError("--level 需要一个正整数等级，并放在查询表达式末尾")
    return expression[:position].strip(), normalize_tech_level(tokens[1])


def query_tech_details(
    pack: Path, query: str, limit: int, sources: TechDetailSources
) -> list[str]:
    expression = sources._clean(query).strip()
    try:
        expression, requested = split_tech_selector(expression)
    except ValueError as error:
        return [
            "未找到科技: " + str(error),
            "用法: tech <名称/四码/字段表达式> --level N",
        ]
    compiled = compile_query(expression)
    if expression and compiled.is_empty:
        return [
            "未找到科技: 查询表达式没有关键词",
            "可用科技名称、四码或字段词，以 &&、|| 组合查询。",
        ]
    index = load_object_records(pack, "科技", sources)
    matches = [
        record
        for record in index.records
        if not expression
        or compiled.score_fields(record.search_fields(sources)) is not None
    ]
    if not matches:
        return [
            "未找到科技: " + query,
            f"  本次可确认科技记录共 {len(index.records)} 项科技；可换名称、四码、字段词，用 search <词> 跨八表查。",
            "  数据来源: 对象ID/科技.tsv 与对象字段.tsv；可用 text <词> 查原文或重新导出。",
            "  若有坐标，可用 near <x> <y> 反查附近对象。",
        ]
    lines: list[str] = []
    for record in matches[:limit] if limit else matches:
        lines.extend(_sheet(record, requested, sources))
        lines.extend(
            render_object_record(
                record, index.view, sources, include_description=False
            )[1:]
        )
        lines.append("")
    if limit and len(matches) > limit:
        lines.append(
            f"  (已达 --limit {limit}, 其余 {len(matches) - limit} 条未显示——去掉 --limit 看全量)"
        )
    if not index.complete:
        lines.append("  数据源有诊断，以上为已确认科技记录；记录数不代表完整地图总量。")
    return lines

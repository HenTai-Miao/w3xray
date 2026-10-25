"""Pure Lua list operations over source-backed values; never execute scripts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

from .script_lexing import literal_string_value, script_views
from .script_object_literals import strip_outer_parentheses
from .script_scopes import script_structure
from .script_value_models import StaticValue, StaticValues, unknown_values


def _integer(value: StaticValue) -> int | None:
    raw = value.value
    if raw is None or value.kind not in {"number", "string"}:
        return None
    if value.kind == "string":
        raw = literal_string_value(raw)
        if raw is None:
            return None
    raw = raw.strip()
    if re.fullmatch(r"[+-]?0[xX][0-9a-fA-F]+", raw):
        number = int(raw, 16)
        return number if -(1 << 63) <= number < (1 << 63) else None
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", raw):
        return None
    try:
        decimal = Decimal(raw)
        if not decimal.is_finite() or not -(1 << 63) <= decimal < (1 << 63):
            return None
        number = int(decimal)
        return number if decimal == number else None
    except InvalidOperation, ValueError:
        return None


def select_values(actual: StaticValues) -> StaticValues:
    selector = actual.at(0)
    if selector.kind == "string" and selector.value is not None:
        text = literal_string_value(selector.value)
        # luaB_select tests the first byte, including strings such as "#count".
        if text is not None and text.startswith("#"):
            if actual.tail is not None:
                return unknown_values("select 参数尾部数量未静态确定", multi=False)
            return StaticValues((StaticValue(str(len(actual.values) - 1), "number"),))
    index = _integer(selector)
    if index is None:
        return unknown_values("select 索引不是已确认的 Lua 整数或 #", multi=True)
    values = actual.values[1:]
    if index < 0:
        if actual.tail is not None:
            return unknown_values("select 负索引依赖未确定的参数尾部长度", multi=True)
        index = len(values) + index + 1
    if index < 1:
        return unknown_values("select 索引超出 Lua 有效范围", multi=True)
    return StaticValues(values[index - 1 :], actual.tail, actual.variable_width)


def array_literal_parts(expression: str) -> tuple[tuple[str, ...] | None, str]:
    raw = strip_outer_parentheses(expression.strip())
    views = script_views(raw, lua=True)
    syntax = views.syntax
    if not syntax.startswith("{") or not syntax.endswith("}"):
        return None, "table.unpack 的表不是本次调用中新建的数组字面量，未假定可变表内容"
    functions = {
        item.start: item.end for item in script_structure(raw, lua=True).functions
    }
    brackets = ["}"]
    parts: list[str] = []
    start, position = 1, 1
    while position < len(syntax):
        end = functions.get(position)
        if end is not None:
            position = end
            continue
        char = syntax[position]
        if char in "([{":
            brackets.append({"(": ")", "[": "]", "{": "}"}[char])
        elif char in ")]}":
            if not brackets or brackets.pop() != char:
                return None, "table.unpack 数组字面量括号不匹配"
            if not brackets:
                if position != len(syntax) - 1:
                    return None, "table.unpack 首参含数组以外的运算，未静态确定"
                part = views.arguments[start:position].strip()
                if part:
                    parts.append(part)
                return tuple(parts), ""
        elif len(brackets) == 1:
            if char in ",;":
                part = views.arguments[start:position].strip()
                if not part:
                    return None, "table.unpack 数组含空字段，未假定为 nil"
                parts.append(part)
                start = position + 1
            elif (
                char == "="
                and syntax[position - 1] not in "<>=~"
                and syntax[position + 1] != "="
            ):
                return None, "table.unpack 数组含命名字段或显式索引，未假定连续序列"
        position += 1
    return None, "table.unpack 数组字面量未闭合"


def unpack_values(elements: StaticValues, bounds: StaticValues) -> StaticValues:
    first, last = bounds.at(0), bounds.at(1)
    start = 1 if first.kind == "nil" else _integer(first)
    stop = None if last.kind == "nil" else _integer(last)
    if start is None or (last.kind != "nil" and stop is None):
        return unknown_values("table.unpack 范围不是已确认的 Lua 整数", multi=True)
    if last.kind == "nil":
        if elements.tail is not None:
            return unknown_values("table.unpack 数组尾部长度未静态确定", multi=True)
        stop = len(elements.values)
        while stop and elements.values[stop - 1].kind == "nil":
            stop -= 1
        if any(item.kind in {"nil", "unknown"} for item in elements.values[:stop]):
            return unknown_values(
                "table.unpack 数组含空洞或未知值，# 长度未唯一确定；请核对显式范围",
                multi=True,
            )
    assert stop is not None
    if start > stop:
        return StaticValues()
    if start < 1 or stop > len(elements.values):
        return unknown_values(
            "table.unpack 范围超出源码已编码数组；未物化额外索引或未知尾部", multi=True
        )
    return StaticValues(
        elements.values[start - 1 : stop], variable_width=elements.variable_width
    )

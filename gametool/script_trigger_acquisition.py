"""Complete static acquisition evidence from source-local trigger callbacks."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
import re

from .save_call_context import extract_call_args
from .script_lexing import script_literals, script_views
from .script_object_literals import literal_object_code
from .script_scopes import CallSpan, FunctionSpan, ScriptStructure, source_line_starts
from .script_trigger_bindings import script_trigger_bindings
from .script_function_graph import (
    FunctionGraph,
    FunctionNode,
    format_function_graph,
    script_functions,
)
from .script_control_ranges import ControlRange, control_ranges
from .script_values import StaticValue
from .script_item_pools import (
    ItemPoolIndex,
    PoolSnapshot,
    format_pool_snapshot,
    item_pool_index,
)

_OUTPUTS = {
    "CreateItem": (0, "创建"),
    "CreateItemLoc": (0, "创建"),
    "BlzCreateItemWithSkin": (0, "创建"),
    "UnitAddItemById": (1, "发放"),
    "UnitAddItemByIdSwapped": (0, "发放"),
    "UnitAddItemToSlotById": (1, "发放"),
    "AddItemToStock": (1, "上架商店"),
    "AddItemToStockBJ": (0, "上架商店"),
    "PlaceRandomItem": (None, "随机奖池"),
}
_NUMBER = re.compile(r"(?<![\w.])(?:\$[0-9a-fA-F]+|0[xX][0-9a-fA-F]+|[0-9]+)(?![\w.])")
_EQUAL = re.compile(r"\s*\)*\s*==\s*\(*\s*\Z")
_OPERAND = re.compile(
    r"(?:_G\.)?(GetDyingUnit|GetTriggerUnit|GetManipulatedItem)\s*\(\s*\)\Z"
)
_RANDOM_APIS = frozenset({"GetRandomInt", "GetRandomReal"})


@dataclass(frozen=True, slots=True)
class TriggerAcquisition:
    kind: str
    trigger_offset: int
    trigger_handle: str
    handler: str
    handler_offset: int
    offset: int
    line: int
    item_code: str
    unit_codes: tuple[str, ...]
    input_items: tuple[str, ...]
    conditions: tuple[str, ...]
    random_calls: tuple[str, ...]
    expression: str
    operation: str
    diagnostic: str = ""
    random_count: int = 0
    events: tuple[str, ...] = ()
    pools: tuple[PoolSnapshot, ...] = ()
    graph: FunctionGraph | None = None
    node: int = 0
    argument_evidence: str = ""
    call_graph_lines: tuple[str, ...] = ()
    value_proof: tuple[str, ...] = ()


def _branches(
    text: str, function: FunctionSpan, structure: ScriptStructure, lua: bool | None
) -> tuple[ControlRange, ...]:
    return tuple(
        branch
        for branch in control_ranges(text, function, structure, lua)
        if branch.kind == "if"
    )


def _literal_spans(
    text: str, structure: ScriptStructure, lua: bool | None
) -> tuple[tuple[int, int, str], ...]:
    values: list[tuple[int, int, str]] = []
    views = script_views(text, lua=lua)
    for call in structure.calls:
        if call.name.removeprefix("_G.") == "FourCC":
            value = text[call.start : call.end].removeprefix("_G.")
            if code := literal_object_code(value):
                values.append((call.start, call.end, code))
    if lua is not True:
        values.extend(
            (literal.start, literal.end, literal.value)
            for literal in script_literals(text, lua=lua)
            if literal.object_code
        )
    for match in _NUMBER.finditer(views.syntax):
        code = literal_object_code(match.group())
        if code and code != "\x00\x00\x00\x00":
            values.append((match.start(), match.end(), code))
    return tuple(sorted(values))


@lru_cache(maxsize=256)
def _selectors(
    expression: str, *, lua: bool | None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep equality operands with their actual type-getter; no code guessing."""
    from .script_scopes import script_structure

    structure = script_structure(expression, lua=lua)
    views = script_views(expression, lua=lua)
    literals = _literal_spans(expression, structure, lua)
    starts = [value[0] for value in literals]
    by_end = sorted(literals, key=lambda value: value[1])
    ends = [value[1] for value in by_end]
    units: list[str] = []
    items: list[str] = []
    for call in structure.calls:
        api = call.name.removeprefix("_G.")
        if api not in {"GetUnitTypeId", "GetItemTypeId"}:
            continue
        args = extract_call_args(views, call.open + 1)
        operand = _OPERAND.fullmatch(args[0]) if len(args) == 1 else None
        if operand is None:
            continue
        allowed = (
            {"GetDyingUnit", "GetTriggerUnit"}
            if api == "GetUnitTypeId"
            else {"GetManipulatedItem"}
        )
        if operand.group(1) not in allowed:
            continue
        before_getter = views.syntax[: call.start].rstrip(" \t\r\n(")
        after_getter = views.syntax[call.end :].lstrip(" \t\r\n)")
        if before_getter.endswith(
            ("+", "-", "*", "/", "%", "^", "~", "&", "|")
        ) or after_getter.startswith(("+", "-", "*", "/", "%", "^", "~", "&", "|")):
            continue
        candidates: list[tuple[int, int, str]] = []
        right = bisect_right(starts, call.end - 1)
        if right < len(literals) and _EQUAL.fullmatch(
            views.syntax[call.end : literals[right][0]]
        ):
            candidates.append(literals[right])
        left = bisect_right(ends, call.start) - 1
        if left >= 0 and _EQUAL.fullmatch(views.syntax[by_end[left][1] : call.start]):
            candidates.append(by_end[left])
        for start, end, code in candidates:
            # A literal that participates in arithmetic is not the equality operand.
            before = views.syntax[:start].rstrip(" \t\r\n(")
            after = views.syntax[end:].lstrip(" \t\r\n)")
            if before.endswith(
                ("+", "-", "*", "/", "%", "^", "~", "&", "|")
            ) or after.startswith(("+", "-", "*", "/", "%", "^", "~", "&", "|")):
                continue
            (units if api == "GetUnitTypeId" else items).append(code)
    return tuple(dict.fromkeys(units)), tuple(dict.fromkeys(items))


class _Analysis:
    def __init__(self, text: str, lua: bool | None) -> None:
        self.text, self.lua = text, lua
        self.bindings = script_trigger_bindings(text, lua=lua)
        self.views = script_views(text, lua=lua)
        self.functions = script_functions(text, lua=lua)
        self.lines = source_line_starts(text)
        self.calls: dict[int | None, list[CallSpan]] = {}
        self.pool_index: ItemPoolIndex | None = None
        for call in self.bindings.structure.calls:
            self.calls.setdefault(call.owner, []).append(call)

    def body(self, function: FunctionSpan) -> str:
        return self.bindings.structure.own_text(
            self.text, function.body_start, function.body_end, function.start
        ).strip()

    def records(
        self,
        function: FunctionSpan,
        conditions: tuple[str, ...],
        events: tuple[str, ...],
        identity: int,
        handle: str,
        diagnostic: str,
        *,
        node: FunctionNode | None = None,
    ) -> list[TriggerAcquisition]:
        branches = _branches(self.text, function, self.bindings.structure, self.lua)
        starts = [branch.start for branch in branches]
        active: list[ControlRange] = []
        cursor = 0
        random_sites = tuple(
            call
            for call in self.calls.get(function.start, ())
            if call.name.removeprefix("_G.") in _RANDOM_APIS
        )
        random_calls = tuple(self.text[call.start : call.end] for call in random_sites)
        random_starts = tuple(call.start for call in random_sites)
        result: list[TriggerAcquisition] = []
        if not function.complete:
            diagnostic = "; ".join(filter(None, (diagnostic, "处理函数范围未闭合")))
        function_text = self.body(function)
        kinds = [
            label
            for marker, label in (
                ("DEATH", "死亡"),
                ("PICKUP_ITEM", "拾取"),
                ("USE_ITEM", "使用"),
                ("DROP_ITEM", "丢弃"),
            )
            if any(marker in event for event in events)
        ]
        if not kinds and any(
            re.search(
                r"\bGetDyingUnit\s*\(", script_views(context, lua=self.lua).syntax
            )
            for context in (function_text, *conditions)
        ):
            kinds = ["死亡"]
            diagnostic = "; ".join(
                filter(
                    None,
                    (
                        diagnostic,
                        "未找到本处理器的事件注册或事件类型未静态确定，保留死亡处理线索",
                    ),
                )
            )
        if not kinds:
            kinds = ["其他"]
        common_units: list[str] = []
        common_items: list[str] = []
        for condition in conditions:
            units, items = _selectors(condition, lua=self.lua)
            common_units.extend(units)
            common_items.extend(items)
        for call in self.calls.get(function.start, ()):
            api = call.name.removeprefix("_G.")
            signature = _OUTPUTS.get(api)
            if (
                signature is None
                or not call.complete
                or self.functions.bound(call.name, call.owner, call.start)
            ):
                continue
            while cursor < len(branches) and starts[cursor] <= call.start:
                branch = branches[cursor]
                active = [item for item in active if item.end > branch.start]
                active.append(branch)
                cursor += 1
            active = [item for item in active if item.end > call.start]
            args = extract_call_args(self.views, call.open + 1)
            position, operation = signature
            if position is not None and not args:
                continue
            actual = self.functions.argument_values(
                args,
                function.start,
                call.start,
                node.arguments if node is not None else (),
                unknown_tail=node.unknown_tail if node is not None else False,
            )
            scalar = actual.at(position) if position is not None else StaticValue(None)
            value, value_note = scalar.value, scalar.diagnostic
            code = literal_object_code(value) if value is not None else ""
            argument_evidence = ""
            if position is not None and (
                position >= len(args) or not code or value != args[position]
            ):
                argument = (
                    args[position]
                    if position < len(args)
                    else f"展开后第{position + 1}个实参（原始参数：{', '.join(args)}）"
                )
                argument_evidence = f"物品实参 {argument}" + (
                    f" -> {value}" if code else f"; {value_note or '物品码未静态确定'}"
                )
            units, items = list(common_units), list(common_items)
            branch_conditions: list[str] = []
            for branch in active:
                branch_conditions.append(branch.condition)
                selector = branch.selector
                if node is not None and selector:
                    start = self.views.arguments.rfind(
                        selector, function.body_start, branch.start
                    )
                    selector = self.functions.resolved_text(
                        selector,
                        function.start,
                        start,
                        node.arguments,
                        unknown_tail=node.unknown_tail,
                    )
                    if selector != branch.selector:
                        branch_conditions.append("返回值/实参展开（静态）: " + selector)
                branch_units, branch_items = _selectors(selector, lua=self.lua)
                units.extend(branch_units)
                items.extend(branch_items)
            if not events and not units and not items:
                continue
            pools: tuple[PoolSnapshot, ...] = ()
            if operation == "随机奖池":
                if self.pool_index is None:
                    self.pool_index = item_pool_index(self.text, lua=self.lua)
                pools = self.pool_index.placements.get(call.start, ())
            record = TriggerAcquisition(
                kinds[0],
                identity,
                handle,
                function.name,
                function.start,
                call.start,
                bisect_right(self.lines, call.start),
                code,
                tuple(dict.fromkeys(units)),
                tuple(dict.fromkeys(items)),
                (*conditions, *branch_conditions),
                random_calls,
                self.text[call.start : call.end],
                operation,
                diagnostic,
                bisect_right(random_starts, call.start - 1),
                events,
                pools,
                argument_evidence=argument_evidence,
                value_proof=self.functions.values.proof_lines(scalar),
            )
            result.append(record)
            result.extend(replace(record, kind=kind) for kind in kinds[1:])
        return result

    def expanded_records(
        self,
        function: FunctionSpan,
        conditions: tuple[str, ...],
        events: tuple[str, ...],
        identity: int,
        handle: str,
        diagnostic: str,
    ) -> list[TriggerAcquisition]:
        graph = self.functions.graph(function)
        result: list[TriggerAcquisition] = []
        graph_lines = tuple(format_function_graph(graph, self.functions))
        has_selectors = any(edge.selectors for edge in graph.edges)
        for number, node in enumerate(graph.nodes):
            selectors = graph.selectors_for(number) if has_selectors else ()
            rows = self.records(
                node.function,
                (*conditions, *selectors),
                events,
                identity,
                handle,
                diagnostic,
                node=node,
            )
            result.extend(
                replace(
                    row,
                    handler=function.name,
                    handler_offset=function.start,
                    graph=graph if graph.edges else None,
                    node=number,
                    call_graph_lines=graph_lines,
                )
                for row in rows
            )
        return result


@lru_cache(maxsize=8)
def trigger_acquisitions(
    text: str, *, lua: bool | None = None
) -> tuple[TriggerAcquisition, ...]:
    """Return source-local reward calls and helper contexts without a depth ceiling."""
    analysis = _Analysis(text, lua)
    rows: list[TriggerAcquisition] = []
    registered: set[int] = set()
    for sites in analysis.bindings.instances.values():
        events = tuple(dict.fromkeys(event for site in sites for event in site.events))
        conditions: list[str] = []
        diagnostics = [site.diagnostic for site in sites if site.diagnostic]
        for site in sites:
            callback = site.callback
            if callback is None:
                continue
            if callback.diagnostic:
                diagnostics.append(callback.diagnostic)
            registered.update(function.start for function in callback.functions)
            for function in callback.functions:
                registered.update(
                    node.function.start
                    for node in analysis.functions.graph(function).nodes
                )
            if site.call.name.removeprefix("_G.") in {
                "TriggerAddCondition",
                "TriggerAddConditionBJ",
            }:
                for function in callback.functions:
                    graph = analysis.functions.graph(function)
                    for node in graph.nodes:
                        original = analysis.body(node.function)
                        conditions.append(original)
                        body = analysis.bindings.structure.own_text(
                            text,
                            node.function.body_start,
                            node.function.body_end,
                            node.function.start,
                        )
                        resolved = analysis.functions.resolved_text(
                            body,
                            node.function.start,
                            node.function.body_start,
                            node.arguments,
                            unknown_tail=node.unknown_tail,
                        ).strip()
                        if resolved != original:
                            conditions.append("字面量实参展开（静态）: " + resolved)
                    if graph.edges:
                        diagnostics.append(
                            "条件处理器包含辅助调用；各函数原文保留为静态线索，返回值逻辑须按原文核对"
                        )
        for site in sites:
            if (
                site.call.name.removeprefix("_G.")
                not in {"TriggerAddAction", "TriggerAddActionBJ"}
                or site.callback is None
            ):
                continue
            for function in site.callback.functions:
                rows.extend(
                    analysis.expanded_records(
                        function,
                        tuple(conditions),
                        events,
                        sites[0].call.start,
                        site.arguments[0],
                        "; ".join(dict.fromkeys(diagnostics)),
                    )
                )
    for function in analysis.bindings.structure.functions:
        if function.start not in registered:
            rows.extend(analysis.records(function, (), (), function.start, "", ""))
    return tuple(
        sorted(
            rows, key=lambda row: (row.trigger_offset, row.handler_offset, row.offset)
        )
    )


def format_trigger_acquisitions(
    records: tuple[TriggerAcquisition, ...],
    name_of: Callable[[str], str],
    *,
    source: str = "",
    target: str = "",
    death: bool | None = None,
) -> list[str]:
    """Render full evidence once per call, sharing condition text within each handler."""
    grouped: dict[tuple[int, int, str], list[TriggerAcquisition]] = {}
    pool_codes: dict[int, frozenset[str]] = {}
    for record in records:
        if death is not None and (record.kind == "死亡") != death:
            continue
        if target and target not in (
            record.item_code,
            *record.unit_codes,
            *record.input_items,
        ):
            matched = False
            for pool in record.pools:
                codes = pool_codes.get(id(pool))
                if codes is None:
                    codes = frozenset(member.code for member in pool.members)
                    pool_codes[id(pool)] = codes
                matched |= target in codes
            if not matched:
                continue
        grouped.setdefault(
            (record.trigger_offset, record.handler_offset, record.kind), []
        ).append(record)
    output: list[str] = []
    for (_trigger, _handler, kind), entries in grouped.items():
        first = entries[0]
        output.append(
            f"⚠ 脚本{kind}触发产出线索 ({first.handler}; 来源 {source or '当前脚本'}; 注册偏移 {first.trigger_offset}):"
        )
        output.append("  静态证据，条件/分支与随机结果须按原文核对，未断言必定获得。")
        if first.events:
            output.append("  注册事件: " + "、".join(first.events))
        if first.graph is not None:
            # Native source statements retain their own offsets; graph nodes carry arguments.
            output.extend(first.call_graph_lines)
        conditions: dict[str, int] = {}
        for entry in entries:
            for condition in entry.conditions:
                if condition not in conditions:
                    conditions[condition] = len(conditions) + 1
                    output.append(f"  条件{conditions[condition]}: {condition}")
        for diagnostic in dict.fromkeys(
            entry.diagnostic for entry in entries if entry.diagnostic
        ):
            output.append("  关联诊断: " + diagnostic)
        for proof in dict.fromkeys(
            proof for entry in entries for proof in entry.value_proof
        ):
            output.append("  返回值证据: " + proof)
        random_calls = first.random_calls
        random_count = max(entry.random_count for entry in entries)
        for index, random in enumerate(random_calls[:random_count], 1):
            output.append(f"  随机调用{index}（仅作线索）: {random}")
        # Snapshots are shared by placements with the same definition/state.
        # Identity keys avoid hashing every member again for every placement.
        pool_numbers: dict[int, int] = {}
        for entry in entries:
            for pool in entry.pools:
                if id(pool) not in pool_numbers:
                    pool_numbers[id(pool)] = len(pool_numbers) + 1
                    output.extend(
                        format_pool_snapshot(pool, name_of, pool_numbers[id(pool)])
                    )
        for entry in entries:
            units = "、".join(f"{name_of(code)}[{code}]" for code in entry.unit_codes)
            items = "、".join(f"{name_of(code)}[{code}]" for code in entry.input_items)
            if units:
                output.append("  条件涉及单位: " + units)
            if items:
                output.append("  条件涉及物品: " + items)
            refs = "、".join(
                str(conditions[condition]) for condition in entry.conditions
            )
            item = (
                f"{name_of(entry.item_code)}[{entry.item_code}]"
                if entry.item_code
                else "奖池成员由注册与运行时选择决定"
                if entry.operation == "随机奖池"
                else "动态物品码（未静态确定）"
            )
            output.append(
                f"  {entry.operation}: {item}; 第{entry.line}行 / 偏移{entry.offset}"
                + (f"; 条件{refs}" if refs else "")
            )
            if entry.graph is not None:
                output.append(f"    产出函数节点: {entry.node + 1}")
            output.append("    原文: " + entry.expression)
            if entry.argument_evidence:
                output.append("    实参证据: " + entry.argument_evidence)
            if entry.pools:
                output.append(
                    "    奖池证据: "
                    + "、".join(str(pool_numbers[id(pool)]) for pool in entry.pools)
                )
            if entry.random_count:
                output.append(
                    f"    同处理器此前随机调用: 1..{entry.random_count}（仅作线索）"
                )
    return output

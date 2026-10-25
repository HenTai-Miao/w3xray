"""Finite source call graphs and literal arguments; never execute map scripts."""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
import re

from .save_call_context import extract_call_args
from .script_lexing import script_views
from .script_scopes import CallSpan, FunctionSpan, script_structure
from .script_function_bindings import (
    ScriptFunctionBindings,
    FunctionReference as FunctionReference,
)
from .script_values import ScriptValues, StaticValue

_NAME = re.compile(r"[A-Za-z_]\w*(?:[.:][A-Za-z_]\w*)*")


@dataclass(frozen=True, slots=True)
class FunctionNode:
    function: FunctionSpan
    arguments: tuple[str | None, ...]


@dataclass(frozen=True, slots=True)
class FunctionEdge:
    source: int
    target: int | None
    call: CallSpan
    conditions: tuple[str, ...]
    selectors: tuple[str, ...]
    diagnostic: str = ""
    value_proofs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FunctionGraph:
    nodes: tuple[FunctionNode, ...]
    edges: tuple[FunctionEdge, ...]
    cyclic: bool = False
    _selector_cache: dict[int, tuple[str, ...]] = field(
        default_factory=dict, compare=False, repr=False
    )

    def selectors_for(self, node: int) -> tuple[str, ...]:
        """Only ancestor call sites contribute selectors; sibling rewards stay apart."""
        if not self._selector_cache:
            values: list[dict[str, None]] = [{} for _ in self.nodes]
            pending: deque[tuple[int, str]] = deque()
            outgoing: dict[int, list[int]] = {}
            for edge in self.edges:
                if edge.target is not None:
                    outgoing.setdefault(edge.source, []).append(edge.target)
                    for selector in edge.selectors:
                        if selector not in values[edge.target]:
                            values[edge.target][selector] = None
                            pending.append((edge.target, selector))
            while pending:
                current, selector = pending.popleft()
                for target in outgoing.get(current, ()):
                    if selector not in values[target]:
                        values[target][selector] = None
                        pending.append((target, selector))
            self._selector_cache.update(
                (index, tuple(value)) for index, value in enumerate(values)
            )
        return self._selector_cache[node]


class ScriptFunctions(ScriptFunctionBindings):
    def __init__(self, text: str, *, lua: bool | None) -> None:
        super().__init__(text, lua=lua)
        self._graphs: dict[int, FunctionGraph] = {}
        self.values = ScriptValues(self)

    def resolved_text(
        self, text: str, owner: int, start: int, arguments: tuple[str | None, ...]
    ) -> str:
        """Substitute only known scalar tokens, keeping strings and calls opaque."""
        syntax = script_views(text, lua=self.lua).syntax
        replacements: list[tuple[int, int, str]] = []
        for call in script_structure(text, lua=self.lua).calls:
            if (
                call.owner is not None
                or not call.complete
                or not self.bound(call.name, owner, start + call.start)
            ):
                continue
            result = self.scalar(
                text[call.start : call.end], owner, start + call.start, arguments
            )
            if result.value is not None:
                replacements.append((call.start, call.end, result.value))
        parts: list[str] = []
        cursor = 0
        for match in _NAME.finditer(syntax):
            if syntax[match.end() :].lstrip().startswith("("):
                continue
            symbol = self.symbols.symbol(match.group(), owner, start + match.start())
            if symbol not in self.writes and symbol[0] != owner:
                continue
            value, _note = self.literal(
                match.group(), owner, start + match.start(), arguments
            )
            if value is not None:
                replacements.append((match.start(), match.end(), value))
        for first, end, value in sorted(
            replacements, key=lambda item: (item[0], -item[1])
        ):
            if first >= cursor:
                parts.extend((text[cursor:first], value))
                cursor = end
        parts.append(text[cursor:])
        return "".join(parts)

    def scalar(
        self,
        expression: str,
        owner: int,
        position: int,
        arguments: tuple[str | None, ...],
    ) -> StaticValue:
        return self.values.resolve(expression, owner, position, arguments)

    def literal(
        self,
        expression: str,
        owner: int,
        position: int,
        arguments: tuple[str | None, ...],
    ) -> tuple[str | None, str]:
        result = self.scalar(expression, owner, position, arguments)
        return result.value, result.diagnostic

    def graph(self, function: FunctionSpan) -> FunctionGraph:
        cached = self._graphs.get(function.start)
        if cached is not None:
            return cached
        arguments = tuple(None for _ in self.symbols.parameters.get(function.start, ()))
        nodes = [FunctionNode(function, arguments)]
        identities: dict[tuple[int, tuple[str | None, ...]], int] = {
            (function.start, arguments): 0
        }
        edges: list[FunctionEdge] = []
        cursor = 0
        while cursor < len(nodes):
            node = nodes[cursor]
            for call in self.calls.get(node.function.start, ()):
                if not call.complete or not self.bound(
                    call.name, call.owner, call.start
                ):
                    continue
                reference = self.resolve(call.name, call.start, call.owner)
                ranges = self.symbols.control_data(call.owner)[0]
                active = tuple(
                    item
                    for item in ranges
                    if item.start <= call.start < item.end and item.kind == "if"
                )
                conditions = tuple(item.condition for item in active)
                selectors = tuple(
                    self.resolved_text(
                        item.selector,
                        node.function.start,
                        self.views.arguments.rfind(
                            item.selector, node.function.body_start, item.start
                        ),
                        node.arguments,
                    )
                    for item in active
                    if item.selector
                )
                if not reference.functions:
                    edges.append(
                        FunctionEdge(
                            cursor,
                            None,
                            call,
                            conditions,
                            selectors,
                            reference.diagnostic,
                        )
                    )
                    continue
                args = extract_call_args(self.views, call.open + 1)
                expands = (
                    self.lua is True
                    and bool(args)
                    and any(
                        item.start == 0 and item.end == len(args[-1]) and item.complete
                        for item in script_structure(args[-1], lua=True).calls
                    )
                )
                if ":" in call.name:
                    args = (call.name.rsplit(":", 1)[0], *args)
                for target in reference.functions:
                    parameters = self.symbols.parameters.get(target.start, ())
                    bindings: list[str | None] = []
                    notes = [reference.diagnostic] if reference.diagnostic else []
                    value_proofs: dict[str, None] = {}
                    for index, name in enumerate(parameters):
                        result = (
                            self.scalar(
                                args[index],
                                node.function.start,
                                call.start,
                                node.arguments,
                            )
                            if index < len(args)
                            else StaticValue(
                                None,
                                diagnostic="末个调用可能展开多个返回值，此参数未静态确定"
                                if expands
                                else "缺少实参",
                            )
                        )
                        bindings.append(result.value)
                        value_proofs.update(
                            (line, None) for line in self.values.proof_lines(result)
                        )
                        if result.diagnostic:
                            notes.append(f"{name}: {result.diagnostic}")
                    identity = (target.start, tuple(bindings))
                    number = identities.get(identity)
                    if number is None:
                        number = len(nodes)
                        identities[identity] = number
                        nodes.append(FunctionNode(target, tuple(bindings)))
                    edges.append(
                        FunctionEdge(
                            cursor,
                            number,
                            call,
                            conditions,
                            selectors,
                            "; ".join(notes),
                            tuple(value_proofs),
                        )
                    )
            cursor += 1
        # A repeated destination can be a diamond join. Only an actual cycle is diagnosed.
        degrees = [0] * len(nodes)
        outgoing: dict[int, list[int]] = {}
        for edge in edges:
            if edge.target is not None:
                degrees[edge.target] += 1
                outgoing.setdefault(edge.source, []).append(edge.target)
        pending = deque(index for index, degree in enumerate(degrees) if degree == 0)
        visited = 0
        while pending:
            number = pending.popleft()
            visited += 1
            for target in outgoing.get(number, ()):
                degrees[target] -= 1
                if degrees[target] == 0:
                    pending.append(target)
        graph = FunctionGraph(tuple(nodes), tuple(edges), visited < len(nodes))
        self._graphs[function.start] = graph
        return graph


@lru_cache(maxsize=8)
def script_functions(text: str, *, lua: bool | None = None) -> ScriptFunctions:
    return ScriptFunctions(text, lua=lua)


def format_function_graph(
    graph: FunctionGraph, functions: ScriptFunctions, *, definitions: bool = False
) -> list[str]:
    if not graph.edges:
        return []
    lines = ["  静态调用图（当前源码；分支与替代路径分别保留，不断言执行顺序）:"]
    printed: list[tuple[int, int]] = []
    for index, node in enumerate(graph.nodes):
        function = node.function
        names = functions.symbols.parameters.get(function.start, ())
        values = ", ".join(
            f"{name}={value if value is not None else '动态'}"
            for name, value in zip(names, node.arguments)
        )
        lines.append(
            f"    节点{index + 1}: {function.name}({values}); 第{function.start_line}行 / 偏移{function.start}"
        )
        if (
            definitions
            and index
            and not any(
                start <= function.start and function.end <= end
                for start, end in printed
            )
        ):
            lines.append(
                "      函数原文: " + functions.text[function.start : function.end]
            )
            printed.append((function.start, function.end))
        if index == 0:
            printed.append((function.start, function.end))
    for edge in graph.edges:
        target = f"节点{edge.target + 1}" if edge.target is not None else "未确定函数"
        lines.append(
            f"    节点{edge.source + 1} -> {target}; 第{bisect_right(functions.lines, edge.call.start)}行 / 偏移{edge.call.start}: "
            + functions.text[edge.call.start : edge.call.end]
        )
        for condition in edge.conditions:
            lines.append("      调用条件: " + condition)
        for proof in edge.value_proofs:
            lines.append("      返回值证据: " + proof)
        if edge.diagnostic:
            lines.append("      调用诊断: " + edge.diagnostic)
    if graph.cyclic:
        lines.append(
            "    递归环：已保留所有调用位置；重复函数及相同字面量实参共享节点，运行次数由实际执行决定。"
        )
    return lines

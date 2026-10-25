"""Finite source call graphs and literal arguments; never execute map scripts."""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from types import MappingProxyType

from .save_call_context import extract_call_args
from .script_lexing import script_views
from .script_names import NAME_PATTERN
from .script_geometry_values import GEOMETRY_READERS
from .script_scopes import CallSpan, FunctionSpan, script_structure
from .script_function_bindings import (
    ScriptFunctionBindings,
    FunctionReference as FunctionReference,
)
from .script_values import ScriptValues, StaticValue
from .script_value_models import StaticValues


@dataclass(frozen=True, slots=True)
class FunctionNode:
    function: FunctionSpan
    arguments: tuple[str | None, ...]
    unknown_tail: bool = False


@dataclass(frozen=True, slots=True)
class FunctionContext:
    node: FunctionNode
    incoming: bool
    evidence: tuple[str, ...] = ()


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
        self._source_graph: FunctionGraph | None = None
        self._source_contexts: Mapping[int, tuple[FunctionContext, ...]] | None = None
        self.values = ScriptValues(self)

    def resolved_text(
        self,
        text: str,
        owner: int | None,
        start: int,
        arguments: tuple[str | None, ...],
        *,
        unknown_tail: bool = False,
    ) -> str:
        """Substitute only known scalar tokens, keeping strings and calls opaque."""
        syntax = script_views(text, lua=self.lua).syntax
        replacements: list[tuple[int, int, str]] = []
        for call in script_structure(text, lua=self.lua).calls:
            if (
                call.owner is not None
                or not call.complete
                or not (
                    self.bound(call.name, owner, start + call.start)
                    or self.resolve(call.name, start + call.start, owner).builtin
                    in GEOMETRY_READERS
                )
            ):
                continue
            result = self.scalar(
                text[call.start : call.end],
                owner,
                start + call.start,
                arguments,
                unknown_tail=unknown_tail,
            )
            if result.value is not None:
                replacements.append((call.start, call.end, result.value))
        parts: list[str] = []
        cursor = 0
        for match in NAME_PATTERN.finditer(syntax):
            if syntax[match.end() :].lstrip().startswith("("):
                continue
            symbol = self.symbols.symbol(match.group(), owner, start + match.start())
            if symbol not in self.writes and symbol[0] != owner:
                continue
            value, _note = self.literal(
                match.group(),
                owner,
                start + match.start(),
                arguments,
                unknown_tail=unknown_tail,
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
        owner: int | None,
        position: int,
        arguments: tuple[str | None, ...],
        *,
        unknown_tail: bool = False,
    ) -> StaticValue:
        return self.values.resolve(
            expression, owner, position, arguments, unknown_tail=unknown_tail
        )

    def literal(
        self,
        expression: str,
        owner: int | None,
        position: int,
        arguments: tuple[str | None, ...],
        *,
        unknown_tail: bool = False,
    ) -> tuple[str | None, str]:
        result = self.scalar(
            expression, owner, position, arguments, unknown_tail=unknown_tail
        )
        return result.value, result.diagnostic

    def argument_values(
        self,
        expressions: tuple[str, ...],
        owner: int | None,
        position: int,
        arguments: tuple[str | None, ...],
        *,
        unknown_tail: bool = False,
    ) -> StaticValues:
        return self.values.argument_values(
            expressions, owner, position, arguments, unknown_tail=unknown_tail
        )

    def graph(self, function: FunctionSpan) -> FunctionGraph:
        cached = self._graphs.get(function.start)
        if cached is not None:
            return cached
        arguments = tuple(None for _ in self.symbols.parameters.get(function.start, ()))
        root_tail = function.start in self.symbols.variadic
        graph = self._build_graph((FunctionNode(function, arguments, root_tail),))
        self._graphs[function.start] = graph
        return graph

    def source_graph(self) -> FunctionGraph:
        """Share every encoded call context; ambiguous bindings remain unresolved."""
        if self._source_graph is None:
            top = FunctionSpan(
                "<源码顶层>",
                -1,
                0,
                len(self.text),
                len(self.text),
                None,
                1,
                len(self.lines),
                True,
                self.lua is True,
            )
            roots = (FunctionNode(top, ()),) + tuple(
                FunctionNode(
                    function,
                    tuple(
                        None for _ in self.symbols.parameters.get(function.start, ())
                    ),
                    function.start in self.symbols.variadic,
                )
                for function in self.structure.functions
            )
            self._source_graph = self._build_graph(roots, strict=True)
        return self._source_graph

    def source_contexts(self) -> Mapping[int, tuple[FunctionContext, ...]]:
        """Index complete contexts and separate real inputs from default placeholders."""
        if self._source_contexts is not None:
            return self._source_contexts
        graph = self.source_graph()
        targets = {
            graph.nodes[edge.target].function.start
            for edge in graph.edges
            if edge.target is not None
        }
        reachable = {0}
        reachable.update(
            index
            for index, node in enumerate(
                graph.nodes[: len(self.structure.functions) + 1]
            )
            if node.function.start not in targets
        )
        outgoing: dict[int, list[int]] = {}
        for edge in graph.edges:
            if edge.target is not None:
                outgoing.setdefault(edge.source, []).append(edge.target)
        pending = list(reachable)
        while pending:
            for target in outgoing.get(pending.pop(), ()):
                if target not in reachable:
                    reachable.add(target)
                    pending.append(target)
        incoming = {
            edge.target
            for edge in graph.edges
            if edge.target is not None and edge.source in reachable
        }
        proofs: dict[int, dict[str, None]] = {}
        for edge in graph.edges:
            if edge.target is not None:
                proof = proofs.setdefault(edge.target, {})
                proof.update(dict.fromkeys(edge.value_proofs))
                proof[
                    f"调用来源 第{bisect_right(self.lines, edge.call.start)}行 / 偏移{edge.call.start}: {self.text[edge.call.start : edge.call.end]}"
                ] = None
        grouped: dict[int, list[FunctionContext]] = {}
        for index, node in enumerate(graph.nodes):
            grouped.setdefault(node.function.start, []).append(
                FunctionContext(node, index in incoming, tuple(proofs.get(index, {})))
            )
        self._source_contexts = MappingProxyType(
            {owner: tuple(values) for owner, values in grouped.items()}
        )
        return self._source_contexts

    def _build_graph(
        self, roots: tuple[FunctionNode, ...], *, strict: bool = False
    ) -> FunctionGraph:
        nodes = list(roots)
        identities: dict[tuple[int, tuple[str | None, ...], bool], int] = {
            (node.function.start, node.arguments, node.unknown_tail): index
            for index, node in enumerate(nodes)
        }
        parents: list[int | None] = [None] * len(nodes)
        edges: list[FunctionEdge] = []
        cursor = 0
        while cursor < len(nodes):
            node = nodes[cursor]
            for call in self.calls.get(
                None if node.function.start < 0 else node.function.start, ()
            ):
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
                        call.owner,
                        self.views.arguments.rfind(
                            item.selector, node.function.body_start, item.start
                        ),
                        node.arguments,
                        unknown_tail=node.unknown_tail,
                    )
                    for item in active
                    if item.selector
                )
                if (
                    not reference.functions
                    or strict
                    and (reference.diagnostic or len(reference.functions) != 1)
                ):
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
                if ":" in call.name:
                    args = (call.name.rsplit(":", 1)[0], *args)
                actual = self.argument_values(
                    args,
                    call.owner,
                    call.start,
                    node.arguments,
                    unknown_tail=node.unknown_tail,
                )
                for target in reference.functions:
                    parameters = self.symbols.parameters.get(target.start, ())
                    bound, unknown_tail = self.values.binding_values(
                        target.start, actual
                    )
                    target_actual = actual
                    notes = [reference.diagnostic] if reference.diagnostic else []
                    if target.start in self.symbols.variadic and actual.variable_width:
                        ancestor: int | None = cursor
                        while ancestor is not None:
                            previous = nodes[ancestor]
                            if previous.function.start == target.start and len(
                                bound
                            ) > len(previous.arguments):
                                target_actual = self.values.widen_recursive(
                                    target.start, actual, args
                                )
                                bound, unknown_tail = self.values.binding_values(
                                    target.start, target_actual
                                )
                                notes.append("递归变长尾部的长度/值未静态确定")
                                break
                            ancestor = parents[ancestor]
                    bindings = tuple(result.value for result in bound)
                    value_proofs = dict.fromkeys(
                        line
                        for result in (
                            *target_actual.values,
                            *((target_actual.tail,) if target_actual.tail else ()),
                        )
                        for line in self.values.proof_lines(result)
                    )
                    for index, result in enumerate(bound):
                        if result.diagnostic:
                            name = (
                                parameters[index]
                                if index < len(parameters)
                                else f"变长参数{index - len(parameters) + 1}"
                            )
                            notes.append(f"{name}: {result.diagnostic}")
                    if unknown_tail:
                        notes.append("变长实参包含未确定的尾部")
                    identity = (target.start, bindings, unknown_tail)
                    number = identities.get(identity)
                    if number is None:
                        number = len(nodes)
                        identities[identity] = number
                        nodes.append(FunctionNode(target, bindings, unknown_tail))
                        parents.append(cursor)
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
        if function.start in functions.symbols.variadic:
            extra = ", ".join(
                value if value is not None else "动态"
                for value in node.arguments[len(names) :]
            )
            values += (
                (", " if values else "")
                + f"...=({extra})"
                + (" + 未确定尾部" if node.unknown_tail else "")
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

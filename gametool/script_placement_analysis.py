"""Source-backed placement values and finite helper contexts, without execution."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache

from .save_call_context import extract_call_args
from .script_function_graph import script_functions
from .script_object_literals import literal_object_code, strip_outer_parentheses
from .script_scopes import CallSpan, script_structure
from .script_lexing import script_views
from .script_value_models import StaticValue
from .static_numbers import static_number

PLACEMENT_APIS = frozenset(
    {
        "CreateUnit",
        "CreateUnitAtLoc",
        "BlzCreateUnitWithSkin",
        "CreateCorpse",
        "CreateItem",
        "CreateItemLoc",
        "BlzCreateItemWithSkin",
        "CreateDestructable",
        "CreateDestructableZ",
        "CreateDeadDestructable",
        "CreateDeadDestructableZ",
    }
)


@dataclass(frozen=True, slots=True)
class ScriptPlacement:
    code: str
    x: float
    y: float
    kind: str
    offset: int
    line: int
    expression: str
    evidence: tuple[str, ...] = ()

    def row(self) -> tuple[str, float, float, str]:
        return self.code, self.x, self.y, self.kind


@dataclass(frozen=True, slots=True)
class PlacementDiagnostic:
    offset: int
    line: int
    expression: str
    reason: str


@dataclass(frozen=True, slots=True)
class PlacementAnalysis:
    placements: tuple[ScriptPlacement, ...]
    diagnostics: tuple[PlacementDiagnostic, ...] = ()


class _Analysis:
    def __init__(self, script: str, lua: bool | None) -> None:
        self.text, self.lua = script, lua
        self.functions = script_functions(script, lua=lua)
        self.views = self.functions.views
        self.arguments: dict[int, tuple[str, ...]] = {}

    def number(
        self,
        expression: str,
        value: StaticValue,
        call: CallSpan,
        arguments: tuple[str | None, ...],
        unknown_tail: bool,
    ) -> float | None:
        if value.kind == "number" and value.value is not None:
            return static_number(value.value, lua=self.lua is True)
        direct = static_number(expression, lua=self.lua is True)
        if direct is not None:
            return direct
        return static_number(
            self.functions.resolved_text(
                expression,
                call.owner,
                call.open + 1,
                arguments,
                unknown_tail=unknown_tail,
            ),
            lua=self.lua is True,
        )

    def resolve(
        self,
        call: CallSpan,
        arguments: tuple[str | None, ...],
        unknown_tail: bool,
    ) -> tuple[ScriptPlacement | None, str]:
        functions = self.functions
        if functions.bound(call.name, call.owner, call.start):
            return None, "创建函数已被绑定或重定义，未假定为原生函数"
        name = call.name.removeprefix("_G.")
        kind = (
            "destructable"
            if "Destructable" in name
            else "unit"
            if "Unit" in name or name == "CreateCorpse"
            else "item"
        )
        offset = 1 if kind == "unit" else 0
        raw = self.arguments.setdefault(
            call.start, extract_call_args(self.views, call.open + 1)
        )
        actual = functions.argument_values(
            raw,
            call.owner,
            call.start,
            arguments,
            unknown_tail=unknown_tail,
        )
        code_value = actual.at(offset)
        code = (
            literal_object_code(code_value.value)
            if code_value.value is not None and code_value.kind in {"object", "number"}
            else ""
        )
        if not code:
            return None, "对象码未静态确定: " + (
                code_value.diagnostic or "实参不是对象码或整数"
            )
        if name in {"CreateUnitAtLoc", "CreateItemLoc"}:
            expression = (
                strip_outer_parentheses(raw[offset + 1])
                if len(raw) > offset + 1
                else ""
            )
            calls = script_structure(expression, lua=self.lua).calls
            loc = next(
                (
                    item
                    for item in calls
                    if item.start == 0 and item.complete and item.end == len(expression)
                ),
                None,
            )
            if (
                loc is None
                or loc.name.removeprefix("_G.") != "Location"
                or functions.bound(loc.name, call.owner, call.start)
            ):
                return None, "位置不是已确认的 Location 构造；动态位置句柄未静态确定"
            coords = extract_call_args(
                script_views(expression, lua=self.lua), loc.open + 1
            )
            values = functions.argument_values(
                coords, call.owner, call.start, arguments, unknown_tail=unknown_tail
            )
            if values.tail is not None or len(values.values) != 2:
                return None, "Location 坐标参数数量未静态确定"
            x, y = tuple(
                self.number(
                    coords[i] if i < len(coords) else "",
                    values.at(i),
                    call,
                    arguments,
                    unknown_tail,
                )
                for i in range(2)
            )
            proofs = (*actual.values, *values.values)
        else:
            x, y = tuple(
                self.number(
                    raw[i] if i < len(raw) else "",
                    actual.at(i),
                    call,
                    arguments,
                    unknown_tail,
                )
                for i in (offset + 1, offset + 2)
            )
            proofs = actual.values
        if x is None or y is None:
            return None, "坐标未静态确定；保留动态/缺失/非有限坐标，不猜测点位"
        evidence = dict.fromkeys(
            line for value in proofs for line in functions.values.proof_lines(value)
        )
        names = (
            functions.symbols.parameters.get(call.owner, ())
            if call.owner is not None
            else ()
        )
        if names:
            assert call.owner is not None
            evidence[
                functions.symbols.functions[call.owner].name
                + "; 调用上下文: "
                + ", ".join(
                    f"{name}={value if value is not None else '动态'}"
                    for name, value in zip(names, arguments)
                )
            ] = None
        return ScriptPlacement(
            code,
            x,
            y,
            kind,
            call.start,
            bisect_right(functions.lines, call.start),
            self.text[call.start : call.end],
            tuple(evidence),
        ), ""

    def run(self) -> PlacementAnalysis:
        functions = self.functions
        calls = tuple(
            call
            for call in functions.structure.calls
            if call.complete and call.name.removeprefix("_G.") in PLACEMENT_APIS
        )
        found: dict[tuple[int, tuple[str, float, float, str]], ScriptPlacement] = {}
        unresolved: dict[int, tuple[CallSpan, str]] = {}
        for call in calls:
            arguments = (
                tuple(None for _ in functions.symbols.parameters.get(call.owner, ()))
                if call.owner is not None
                else ()
            )
            placement, note = self.resolve(
                call, arguments, call.owner in functions.symbols.variadic
            )
            if placement is not None:
                found[(call.start, placement.row())] = placement
            else:
                unresolved[call.start] = (call, note)
        contextual = tuple(
            call
            for call, _note in unresolved.values()
            if call.owner is not None
            and (
                functions.symbols.parameters.get(call.owner)
                or call.owner in functions.symbols.variadic
            )
            and not functions.bound(call.name, call.owner, call.start)
        )
        dynamic: dict[int, dict[str, None]] = {}
        if contextual:
            graph = functions.source_graph()
            targets = {
                graph.nodes[edge.target].function.start
                for edge in graph.edges
                if edge.target is not None
            }
            # Unknown default nodes let us inspect source bodies. Only the top
            # level and functions without encoded callers are input roots;
            # descendants of other default nodes are not extra runtime calls.
            reachable = {0}
            reachable.update(
                index
                for index, node in enumerate(
                    graph.nodes[: len(functions.structure.functions) + 1]
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
            incoming_proofs: dict[int, dict[str, None]] = {}
            for edge in graph.edges:
                if edge.target is not None:
                    proof = incoming_proofs.setdefault(edge.target, {})
                    proof.update(dict.fromkeys(edge.value_proofs))
                    proof[
                        f"调用来源 第{bisect_right(functions.lines, edge.call.start)}行 / 偏移{edge.call.start}: {self.text[edge.call.start : edge.call.end]}"
                    ] = None
            by_owner: dict[int, list[int]] = {}
            for index, node in enumerate(graph.nodes):
                by_owner.setdefault(node.function.start, []).append(index)
            for call in contextual:
                assert call.owner is not None
                for index in by_owner.get(call.owner, ()):
                    node = graph.nodes[index]
                    placement, note = self.resolve(
                        call, node.arguments, node.unknown_tail
                    )
                    if placement is not None:
                        key = (call.start, placement.row())
                        if key not in found:
                            proof = dict.fromkeys(placement.evidence)
                            proof.update(incoming_proofs.get(index, {}))
                            found[key] = ScriptPlacement(
                                placement.code,
                                placement.x,
                                placement.y,
                                placement.kind,
                                placement.offset,
                                placement.line,
                                placement.expression,
                                tuple(proof),
                            )
                    elif index in incoming:
                        dynamic.setdefault(call.start, {})[note] = None
        resolved_offsets = {placement.offset for placement in found.values()}
        diagnostics = tuple(
            PlacementDiagnostic(
                call.start,
                bisect_right(functions.lines, call.start),
                self.text[call.start : call.end],
                "; ".join(dynamic.get(call.start, {note: None})),
            )
            for call, note in unresolved.values()
            if call.start not in resolved_offsets or call.start in dynamic
        )
        return PlacementAnalysis(
            tuple(sorted(found.values(), key=lambda row: row.offset)), diagnostics
        )


@lru_cache(maxsize=8)
def analyze_script_placements(
    script: str, *, lua: bool | None = False
) -> PlacementAnalysis:
    """Keep distinct source-call/point evidence, never runtime instance estimates."""
    return _Analysis(script, lua).run()

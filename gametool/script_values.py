"""Conservative scalar dataflow through source getters, without script execution."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import json
import re
from typing import TYPE_CHECKING

from .save_call_context import extract_call_args
from .script_lexing import literal_string_value, script_views
from .script_object_literals import literal_object_code, strip_outer_parentheses
from .script_returns import ReturnSpan, script_returns
from .script_scopes import script_structure

if TYPE_CHECKING:
    from .script_function_bindings import ScriptFunctionBindings

_NAME = re.compile(r"[A-Za-z_]\w*(?:[.:][A-Za-z_]\w*)*")
_NUMBER = re.compile(
    r"[+-]?(?:\$[0-9a-fA-F]+|0[xX][0-9a-fA-F]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
)


@dataclass(frozen=True, slots=True)
class StaticValue:
    value: str | None
    kind: str = "unknown"
    diagnostic: str = ""
    proof: int = -1


@dataclass(frozen=True, slots=True)
class _Expression:
    text: str
    owner: int | None
    position: int
    context: int | None
    arguments: tuple[str | None, ...]


@dataclass(frozen=True, slots=True)
class _Proof:
    label: str
    parents: tuple[int, ...]


@dataclass(slots=True)
class _Frame:
    key: _Expression
    stage: str = "start"
    dependencies: tuple[_Expression, ...] = ()
    function: int | None = None
    row: ReturnSpan | None = None
    label: str = ""
    parents: tuple[int, ...] = ()


class ScriptValues:
    def __init__(self, functions: ScriptFunctionBindings) -> None:
        self.functions = functions
        self.returns: dict[int | None, list[ReturnSpan]] = {}
        for row in script_returns(functions.text, lua=functions.lua):
            self.returns.setdefault(row.owner, []).append(row)
        self.results: dict[_Expression, StaticValue] = {}
        self.proofs: list[_Proof] = []
        self._proof_lines: dict[int, tuple[str, ...]] = {}
        self._events: dict[int | None, set[int]] = {}
        for (owner, _name), positions in functions.symbols.locals.items():
            self._events.setdefault(owner, {-1, 0}).update(positions)
        for writes in functions.writes.values():
            for assignment in writes:
                self._events.setdefault(assignment.owner, {-1, 0}).update(
                    (assignment.offset, assignment.offset + 1)
                )
        self._epochs: dict[int | None, tuple[int, ...]] = {}

    def _key(
        self,
        text: str,
        owner: int | None,
        position: int,
        context: int | None,
        arguments: tuple[str | None, ...],
    ) -> _Expression:
        epochs = self._epochs.get(owner)
        if epochs is None:
            events = self._events.get(owner, {-1, 0}).copy()
            for control in self.functions.symbols.control_data(owner)[0]:
                events.update((control.start, control.end))
            epochs = tuple(sorted(events))
            self._epochs[owner] = epochs
        # Within one epoch the visible locals, preceding writes and control blocks
        # are identical. Retain source offsets in proofs, rather than recomputing
        # the same nested argument at every call's character position.
        boundary = epochs[bisect_right(epochs, position) - 1]
        return _Expression(
            strip_outer_parentheses(text), owner, boundary, context, arguments
        )

    def _result(
        self,
        value: str | None,
        kind: str = "unknown",
        diagnostic: str = "",
        *,
        label: str = "",
        parents: tuple[int, ...] = (),
    ) -> StaticValue:
        parents = tuple(parent for parent in parents if parent >= 0)
        proof = -1
        if label or parents:
            proof = len(self.proofs)
            self.proofs.append(_Proof(label, parents))
        return StaticValue(value, kind, diagnostic, proof)

    def resolve(
        self,
        expression: str,
        owner: int,
        position: int,
        arguments: tuple[str | None, ...],
    ) -> StaticValue:
        root = self._key(expression, owner, position, owner, arguments)
        pending = [_Frame(root)]
        active: set[_Expression] = {root}
        while pending:
            frame = pending[-1]
            key = frame.key
            if key in self.results:
                pending.pop()
                active.discard(key)
                continue
            if frame.stage == "start":
                value = key.text
                string = literal_string_value(value)
                if string is not None:
                    if (
                        self.functions.lua is not True
                        and value.startswith("'")
                        and literal_object_code(value)
                    ):
                        result = StaticValue(value, "object")
                    else:
                        result = StaticValue(
                            json.dumps(string, ensure_ascii=False), "string"
                        )
                    self.results[key] = result
                    continue
                if _NUMBER.fullmatch(value):
                    self.results[key] = StaticValue(value, "number")
                    continue
                if value in {"true", "false", "nil", "null"}:
                    self.results[key] = StaticValue(
                        value, "boolean" if value in {"true", "false"} else "nil"
                    )
                    continue
                if _NAME.fullmatch(value):
                    symbol = self.functions.symbols.symbol(
                        value, key.owner, key.position
                    )
                    assignment, note = self.functions._write(
                        symbol, key.owner, key.position
                    )
                    if note:
                        self.results[key] = StaticValue(None, diagnostic=note)
                        continue
                    if assignment is not None:
                        rhs = self.functions.atoms.value(assignment)
                        if not rhs:
                            self.results[key] = StaticValue(
                                None, diagnostic="赋值不是可确认的标量表达式"
                            )
                            continue
                        dependency = self._key(
                            rhs,
                            assignment.owner,
                            self.functions._rhs_position(assignment),
                            key.context,
                            key.arguments,
                        )
                    else:
                        names = (
                            self.functions.symbols.parameters.get(key.context, ())
                            if key.context is not None
                            else ()
                        )
                        environment = dict(zip(names, key.arguments))
                        supplied = (
                            environment.get(value)
                            if symbol[:2] == (key.context, key.context)
                            else None
                        )
                        if supplied is None:
                            self.results[key] = StaticValue(
                                None, diagnostic="实参值由运行时决定，未静态确定"
                            )
                            continue
                        dependency = self._key(
                            supplied, key.owner, key.position, key.context, ()
                        )
                    frame.stage, frame.dependencies = "alias", (dependency,)
                else:
                    structure = script_structure(value, lua=self.functions.lua)
                    calls = [
                        call
                        for call in structure.calls
                        if call.start == 0 and call.end == len(value) and call.complete
                    ]
                    if len(calls) != 1:
                        self.results[key] = StaticValue(
                            None, diagnostic="动态实参或运算表达式，未静态求值"
                        )
                        continue
                    call = calls[0]
                    args = extract_call_args(
                        script_views(value, lua=self.functions.lua), call.open + 1
                    )
                    if call.name.removeprefix(
                        "_G."
                    ) == "FourCC" and not self.functions.bound(
                        call.name, key.owner, key.position
                    ):
                        if len(args) != 1:
                            self.results[key] = StaticValue(
                                None, diagnostic="FourCC 实参数量未确定"
                            )
                            continue
                        frame.stage = "fourcc"
                    else:
                        reference = self.functions.resolve(
                            call.name, key.position, key.owner
                        )
                        if len(reference.functions) != 1 or reference.diagnostic:
                            self.results[key] = StaticValue(
                                None,
                                diagnostic="返回值函数未唯一确定: "
                                + (reference.diagnostic or call.name),
                            )
                            continue
                        function = reference.functions[0]
                        returns = self.returns.get(function.start, ())
                        if not function.complete or len(returns) != 1:
                            self.results[key] = StaticValue(
                                None,
                                diagnostic=f"{function.name} 有 {len(returns)} 处返回或范围未闭合；未合并为固定值",
                            )
                            continue
                        row = returns[0]
                        ranges = self.functions.symbols.control_data(function.start)[0]
                        if row.diagnostic or any(
                            item.start <= row.start < item.end
                            and item.condition != "do"
                            for item in ranges
                        ):
                            self.results[key] = StaticValue(
                                None,
                                diagnostic=f"{function.name} 返回位于分支/循环或表达式不完整，值未静态确定",
                            )
                            continue
                        frame.stage, frame.function, frame.row = (
                            "arguments",
                            function.start,
                            row,
                        )
                        frame.label = f"{function.name}; 第{row.line}行 / 偏移{row.start}: return {row.expression}"
                        if ":" in call.name:
                            args = (call.name.rsplit(":", 1)[0], *args)
                    frame.dependencies = tuple(
                        self._key(
                            arg, key.owner, key.position, key.context, key.arguments
                        )
                        for arg in args
                    )
            missing = next(
                (item for item in frame.dependencies if item not in self.results), None
            )
            if missing is not None:
                if missing in active:
                    self.results[key] = StaticValue(
                        None, diagnostic="返回值或变量依赖形成递归环，未静态求值"
                    )
                    continue
                active.add(missing)
                pending.append(_Frame(missing))
                continue
            values = tuple(self.results[item] for item in frame.dependencies)
            if frame.stage == "arguments":
                names = (
                    self.functions.symbols.parameters.get(frame.function, ())
                    if frame.function is not None
                    else ()
                )
                bindings = tuple(
                    values[index].value if index < len(values) else None
                    for index in range(len(names))
                )
                assert frame.row is not None and frame.function is not None
                if names:
                    frame.label += "; 实参 " + ", ".join(
                        f"{name}={value if value is not None else '动态'}"
                        for name, value in zip(names, bindings)
                    )
                frame.parents = tuple(item.proof for item in values if item.proof >= 0)
                frame.stage = "return"
                frame.dependencies = (
                    self._key(
                        frame.row.first,
                        frame.function,
                        frame.row.expression_start,
                        frame.function,
                        bindings,
                    ),
                )
                continue
            if frame.stage == "fourcc":
                item = values[0]
                string = (
                    literal_string_value(item.value)
                    if item.value is not None and item.kind == "string"
                    else None
                )
                raw = f"FourCC({string!r})" if string is not None else ""
                self.results[key] = self._result(
                    raw if raw and literal_object_code(raw) else None,
                    "object" if raw and literal_object_code(raw) else "unknown",
                    ""
                    if raw and literal_object_code(raw)
                    else item.diagnostic or "FourCC 实参不是四字节文本",
                    parents=(item.proof,),
                )
            else:
                item = values[0]
                self.results[key] = self._result(
                    item.value,
                    item.kind,
                    item.diagnostic,
                    label=frame.label,
                    parents=(*frame.parents, item.proof),
                )
        return self.results[root]

    def proof_lines(self, value: StaticValue) -> tuple[str, ...]:
        cached = self._proof_lines.get(value.proof)
        if cached is not None:
            return cached
        pending, seen, lines = [value.proof], set(), []
        while pending:
            number = pending.pop()
            if number < 0 or number in seen:
                continue
            seen.add(number)
            proof = self.proofs[number]
            if proof.label:
                lines.append(proof.label)
            pending.extend(reversed(proof.parents))
        result = tuple(lines)
        self._proof_lines[value.proof] = result
        return result

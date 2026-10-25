"""Conservative scalar and Lua list dataflow, without script execution."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
import json
import math
import re
from typing import TYPE_CHECKING

from .save_call_context import extract_call_args
from .script_lexing import literal_string_value, script_views
from .script_lua_builtins import array_literal_parts, select_values, unpack_values
from .script_names import qualified_name, rectangle_name
from .script_numeric_expressions import NumericExpression, numeric_expression
from .script_geometry import GeometryAliases
from .script_geometry_values import (
    GEOMETRY_BUILTINS,
    GEOMETRY_CONSTRUCTORS,
    GEOMETRY_READERS,
    GEOMETRY_TRANSFORMS,
    GEOMETRY_PREDICATES,
    geometry_center,
    computed_geometry,
    geometry_constructor,
    geometry_coordinates,
    geometry_transform,
)
from .script_object_literals import literal_object_code, strip_outer_parentheses
from .script_returns import ReturnSpan, script_returns
from .script_scopes import script_structure
from .static_numbers import format_number, static_number
from .script_value_models import (
    StaticValue as StaticValue,
    StaticValues,
    flatten_values,
    split_value_expressions,
    unknown_values,
)

if TYPE_CHECKING:
    from .script_function_bindings import ScriptFunctionBindings

_NUMBER = re.compile(
    r"[+-]?(?:\$[0-9a-fA-F]+|0[xX][0-9a-fA-F]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
)


@dataclass(frozen=True, slots=True)
class _Expression:
    text: str
    owner: int | None
    position: int
    context: int | None
    arguments: tuple[str | None, ...]
    multi: bool = False
    parts: tuple[str, ...] | None = None
    unknown_tail: bool = False


@dataclass(frozen=True, slots=True)
class _Proof:
    label: str
    parents: tuple[int, ...]
    derived_numeric: bool = False


@dataclass(slots=True)
class _Frame:
    key: _Expression
    stage: str = "start"
    dependencies: tuple[_Expression, ...] = ()
    function: int | None = None
    row: ReturnSpan | None = None
    label: str = ""
    parents: tuple[int, ...] = ()
    ordinal: int = 0
    call_arguments: tuple[str, ...] = ()
    bound_count: int = 0
    cursor: int = 0
    numeric: NumericExpression | None = None
    bindings: tuple[str | None, ...] = ()


class ScriptValues:
    def __init__(self, functions: ScriptFunctionBindings) -> None:
        self.functions = functions
        self.returns: dict[int | None, list[ReturnSpan]] = {}
        for row in script_returns(functions.text, lua=functions.lua):
            self.returns.setdefault(row.owner, []).append(row)
        self.results: dict[_Expression, StaticValues] = {}
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
        self._geometry_aliases: GeometryAliases | None = None

    def geometry_note(self, expression: str, owner: int | None, position: int) -> str:
        if self._geometry_aliases is None:
            self._geometry_aliases = GeometryAliases(self.functions)
        return self._geometry_aliases.diagnostic(expression, owner, position)

    def _key(
        self,
        text: str,
        owner: int | None,
        position: int,
        context: int | None,
        arguments: tuple[str | None, ...],
        *,
        multi: bool = False,
        parts: tuple[str, ...] | None = None,
        unknown_tail: bool = False,
    ) -> _Expression:
        epochs = self._epochs.get(owner)
        if epochs is None:
            events = self._events.get(owner, {-1, 0}).copy()
            for control in self.functions.symbols.control_data(owner)[0]:
                events.update((control.start, control.end))
            epochs = tuple(sorted(events))
            self._epochs[owner] = epochs
        boundary = epochs[bisect_right(epochs, position) - 1]
        raw = text.strip()
        value = strip_outer_parentheses(raw)
        # Parentheses enforce a scalar even in the final position of a Lua list.
        expands = multi and (parts is not None or raw == value)
        return _Expression(
            value, owner, boundary, context, arguments, expands, parts, unknown_tail
        )

    @staticmethod
    def _literal(
        value: str, lua: bool | None, *, computed: bool = False
    ) -> StaticValue | None:
        string = literal_string_value(value)
        if string is not None:
            if lua is not True and value.startswith("'") and literal_object_code(value):
                return StaticValue(value, "object")
            return StaticValue(json.dumps(string, ensure_ascii=False), "string")
        if _NUMBER.fullmatch(value):
            return StaticValue(value, "number")
        if value in {"true", "false", "nil", "null"}:
            return StaticValue(
                value, "boolean" if value in {"true", "false"} else "nil"
            )
        if computed and literal_object_code(value):
            return StaticValue(value, "object")
        if computed:
            return computed_geometry(value)
        return None

    def _save(self, key: _Expression, values: StaticValues) -> None:
        self.results[key] = (
            values if key.multi or key.parts is not None else values.scalar()
        )

    def _proof(
        self,
        values: StaticValues,
        label: str,
        parents: tuple[int, ...] = (),
        *,
        numeric: bool = False,
    ) -> StaticValues:
        dependencies = tuple(
            dict.fromkeys(
                p
                for p in (
                    *parents,
                    *(item.proof for item in values.values),
                    values.tail.proof if values.tail else -1,
                )
                if p >= 0
            )
        )
        if not label and not parents:
            return values
        number = len(self.proofs)
        self.proofs.append(
            _Proof(
                label,
                dependencies,
                numeric
                or any(self.proofs[parent].derived_numeric for parent in dependencies),
            )
        )
        return StaticValues(
            tuple(replace(item, proof=number) for item in values.values),
            replace(values.tail, proof=number) if values.tail else None,
            values.variable_width,
        )

    def binding_values(
        self, function: int, actual: StaticValues
    ) -> tuple[tuple[StaticValue, ...], bool]:
        count = len(self.functions.symbols.parameters.get(function, ()))
        values = tuple(
            actual.at(index)
            if self.functions.lua is True or index < len(actual.values) or actual.tail
            else StaticValue(None, diagnostic="缺少实参")
            for index in range(count)
        )
        variadic = function in self.functions.symbols.variadic
        if variadic:
            values += actual.values[count:]
        return values, variadic and actual.tail is not None

    def widen_recursive(
        self, function: int, actual: StaticValues, expressions: tuple[str, ...]
    ) -> StaticValues:
        # Only a recursively growing variadic tail is unknown; encoded literal
        # prefixes and all ordinary/nonrecursive lists keep their full lengths.
        fixed = max(
            len(self.functions.symbols.parameters.get(function, ())),
            len(expressions) - 1,
        )
        return StaticValues(
            actual.values[:fixed],
            StaticValue(None, diagnostic="递归变长尾部的长度/值未静态确定"),
            True,
        )

    def widen_numeric_recursion(
        self, bound: tuple[StaticValue, ...], previous: tuple[str | None, ...]
    ) -> tuple[StaticValue, ...]:
        """A changing numeric recurrence is symbolic, never an enumeration budget."""
        if len(bound) < len(previous):
            return bound
        return tuple(
            replace(
                item,
                value=None,
                kind="unknown",
                diagnostic="递归数值或几何变换的后续值未静态确定",
            )
            if index < len(previous)
            and item.value is not None
            and item.value != previous[index]
            and item.kind in {"number", "location", "rect"}
            and item.proof >= 0
            and self.proofs[item.proof].derived_numeric
            else item
            for index, item in enumerate(bound)
        )

    def has_numeric_dependency(self, values: tuple[StaticValue, ...]) -> bool:
        return any(
            item.value is not None
            and item.kind in {"number", "location", "rect"}
            and item.proof >= 0
            and self.proofs[item.proof].derived_numeric
            for item in values
        )

    def resolve(
        self,
        expression: str,
        owner: int | None,
        position: int,
        arguments: tuple[str | None, ...],
        *,
        unknown_tail: bool = False,
    ) -> StaticValue:
        return self._evaluate(
            self._key(
                expression, owner, position, owner, arguments, unknown_tail=unknown_tail
            )
        ).at(0)

    def resolve_many(
        self,
        expression: str,
        owner: int | None,
        position: int,
        arguments: tuple[str | None, ...],
        *,
        unknown_tail: bool = False,
    ) -> StaticValues:
        return self._evaluate(
            self._key(
                expression,
                owner,
                position,
                owner,
                arguments,
                multi=self.functions.lua is True,
                unknown_tail=unknown_tail,
            )
        )

    def argument_values(
        self,
        expressions: tuple[str, ...],
        owner: int | None,
        position: int,
        arguments: tuple[str | None, ...],
        *,
        unknown_tail: bool = False,
    ) -> StaticValues:
        return self._evaluate(
            self._key(
                "",
                owner,
                position,
                owner,
                arguments,
                multi=True,
                parts=expressions,
                unknown_tail=unknown_tail,
            )
        )

    def _evaluate(self, root: _Expression) -> StaticValues:
        pending = [_Frame(root)]
        active: set[_Expression] = {root}
        active_functions: dict[int, list[_Frame]] = {}
        while pending:
            frame = pending[-1]
            key = frame.key
            if key in self.results:
                pending.pop()
                active.discard(key)
                if frame.stage == "return" and frame.function is not None:
                    active_functions[frame.function].pop()
                continue
            if frame.stage == "start":
                value = key.text
                if key.parts is not None:
                    frame.stage = "list"
                    frame.dependencies = tuple(
                        self._key(
                            part,
                            key.owner,
                            key.position,
                            key.context,
                            key.arguments,
                            multi=self.functions.lua is True
                            and index == len(key.parts) - 1,
                            unknown_tail=key.unknown_tail,
                        )
                        for index, part in enumerate(key.parts)
                    )
                elif (literal := self._literal(value, self.functions.lua)) is not None:
                    self._save(key, StaticValues((literal,)))
                    continue
                elif value == "...":
                    if key.context not in self.functions.symbols.variadic:
                        self._save(
                            key,
                            unknown_values("当前函数不是变长参数函数", multi=key.multi),
                        )
                    else:
                        count = len(
                            self.functions.symbols.parameters.get(key.context, ())
                        )
                        values = tuple(
                            self._literal(item, self.functions.lua, computed=True)
                            if item is not None
                            else None
                            for item in key.arguments[count:]
                        )
                        self._save(
                            key,
                            StaticValues(
                                tuple(
                                    item
                                    or StaticValue(
                                        None, diagnostic="变长实参值未静态确定"
                                    )
                                    for item in values
                                ),
                                StaticValue(
                                    None, diagnostic="变长实参数量/值未静态确定"
                                )
                                if key.unknown_tail
                                else None,
                                True,
                            ),
                        )
                    continue
                elif (
                    name := qualified_name(
                        script_views(value, lua=self.functions.lua).syntax
                    )
                    or rectangle_name(
                        script_views(value, lua=self.functions.lua).syntax
                    )
                ) is not None:
                    value = name
                    symbol = self.functions.symbols.symbol(
                        value, key.owner, key.position
                    )
                    assignment, note = self.functions._write(
                        symbol, key.owner, key.position
                    )
                    if note:
                        self._save(key, unknown_values(note, multi=False))
                        continue
                    if assignment is not None:
                        parent_note = self.functions._parent_diagnostic(
                            value,
                            key.owner,
                            key.position,
                            (assignment.owner, assignment.offset),
                        )
                        if parent_note:
                            self._save(key, unknown_values(parent_note, multi=False))
                            continue
                        atoms = self.functions.atoms.assignment_values(assignment)
                        if any(atom is None for atom in atoms):
                            self._save(
                                key,
                                unknown_values(
                                    "赋值表达式未完整解析，未假定后续值为空",
                                    multi=False,
                                ),
                            )
                            continue
                        parts = tuple(
                            self.functions.atoms.views.arguments[
                                atom.start : atom.end
                            ].strip()
                            for atom in atoms
                            if atom is not None
                        )
                        dependency = self._key(
                            "",
                            assignment.owner,
                            self.functions._rhs_position(assignment),
                            key.context,
                            key.arguments,
                            multi=True,
                            parts=parts,
                            unknown_tail=key.unknown_tail,
                        )
                        frame.ordinal = assignment.ordinal
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
                            self._save(
                                key,
                                unknown_values(
                                    "实参值由运行时决定，未静态确定", multi=False
                                ),
                            )
                            continue
                        literal = self._literal(
                            supplied, self.functions.lua, computed=True
                        )
                        self._save(
                            key,
                            StaticValues(
                                (
                                    literal
                                    or StaticValue(
                                        None, diagnostic="实参不是已确认的字面量"
                                    ),
                                )
                            ),
                        )
                        continue
                    frame.stage, frame.dependencies = "alias", (dependency,)
                elif (
                    numeric := numeric_expression(value, lua=self.functions.lua)
                ) is not None:
                    frame.stage, frame.numeric = "numeric", numeric
                    frame.dependencies = tuple(
                        self._key(
                            operand.expression,
                            key.owner,
                            key.position,
                            key.context,
                            key.arguments,
                            unknown_tail=key.unknown_tail,
                        )
                        for operand in numeric.operands
                    )
                else:
                    calls = tuple(
                        call
                        for call in script_structure(
                            value, lua=self.functions.lua
                        ).calls
                        if call.start == 0 and call.end == len(value) and call.complete
                    )
                    if len(calls) != 1:
                        self._save(
                            key,
                            unknown_values(
                                "动态实参或运算表达式，未静态求值", multi=False
                            ),
                        )
                        continue
                    call = calls[0]
                    args = extract_call_args(
                        script_views(value, lua=self.functions.lua), call.open + 1
                    )
                    reference = self.functions.resolve(
                        call.name, key.position, key.owner
                    )
                    if reference.builtin == "FourCC":
                        if len(args) != 1:
                            self._save(
                                key,
                                unknown_values(
                                    "FourCC 实参数量未确定", multi=key.multi
                                ),
                            )
                            continue
                        frame.stage = "fourcc"
                    elif reference.builtin in GEOMETRY_BUILTINS:
                        frame.stage, frame.label = "geometry", reference.builtin
                    elif reference.builtin in {"select", "table.unpack"}:
                        frame.stage = reference.builtin
                        frame.label = f"{reference.builtin}; 静态列表运算: {value}"
                        if reference.builtin == "table.unpack":
                            parts, note = array_literal_parts(args[0] if args else "")
                            if parts is None:
                                self._save(key, unknown_values(note, multi=key.multi))
                                continue
                            frame.dependencies = tuple(
                                self._key(
                                    "",
                                    key.owner,
                                    key.position,
                                    key.context,
                                    key.arguments,
                                    multi=True,
                                    parts=items,
                                    unknown_tail=key.unknown_tail,
                                )
                                for items in (parts, args[1:])
                            )
                            continue
                    else:
                        if len(reference.functions) != 1 or reference.diagnostic:
                            self._save(
                                key,
                                unknown_values(
                                    "返回值函数未唯一确定: "
                                    + (reference.diagnostic or call.name),
                                    multi=key.multi,
                                ),
                            )
                            continue
                        function = reference.functions[0]
                        returns = self.returns.get(function.start, ())
                        if not function.complete or len(returns) > 1:
                            self._save(
                                key,
                                unknown_values(
                                    f"{function.name} 有 {len(returns)} 处返回或范围未闭合；未合并为固定值",
                                    multi=key.multi,
                                ),
                            )
                            continue
                        row = returns[0] if returns else None
                        ranges = self.functions.symbols.control_data(function.start)[0]
                        if row is not None and (
                            row.diagnostic
                            or any(
                                item.start <= row.start < item.end
                                and item.condition != "do"
                                for item in ranges
                            )
                        ):
                            self._save(
                                key,
                                unknown_values(
                                    f"{function.name} 返回位于分支/循环或表达式不完整，值未静态确定",
                                    multi=key.multi,
                                ),
                            )
                            continue
                        frame.stage, frame.function, frame.row = (
                            "arguments",
                            function.start,
                            row,
                        )
                        frame.label = (
                            f"{function.name}; 第{row.line}行 / 偏移{row.start}: return {row.expression}"
                            if row
                            else f"{function.name}; 第{function.end_line}行: 函数末尾无返回值"
                        )
                        if ":" in call.name:
                            args = (call.name.rsplit(":", 1)[0], *args)
                    frame.call_arguments = args
                    frame.dependencies = (
                        self._key(
                            "",
                            key.owner,
                            key.position,
                            key.context,
                            key.arguments,
                            multi=True,
                            parts=args,
                            unknown_tail=key.unknown_tail,
                        ),
                    )
            while (
                frame.cursor < len(frame.dependencies)
                and frame.dependencies[frame.cursor] in self.results
            ):
                frame.cursor += 1
            if frame.cursor < len(frame.dependencies):
                missing = frame.dependencies[frame.cursor]
                if missing in active:
                    self._save(
                        key,
                        unknown_values(
                            "返回值或变量依赖形成递归环，未静态求值", multi=key.multi
                        ),
                    )
                    continue
                active.add(missing)
                pending.append(_Frame(missing))
                continue
            values = tuple(self.results[item] for item in frame.dependencies)
            if frame.stage == "list":
                self._save(key, flatten_values(values))
            elif frame.stage == "arguments":
                assert frame.function is not None
                actual = values[0]
                bound, unknown_tail = self.binding_values(frame.function, actual)
                ancestors = active_functions.get(frame.function, ())
                if (
                    frame.function in self.functions.symbols.variadic
                    and actual.variable_width
                    and ancestors
                    and len(bound) > ancestors[-1].bound_count
                ):
                    actual = self.widen_recursive(
                        frame.function, actual, frame.call_arguments
                    )
                    bound, unknown_tail = self.binding_values(frame.function, actual)
                    frame.label += "; 递归变长尾部未静态确定"
                if ancestors:
                    bound = self.widen_numeric_recursion(bound, ancestors[-1].bindings)
                bindings = tuple(item.value for item in bound)
                frame.bindings = bindings
                names = self.functions.symbols.parameters.get(frame.function, ())
                if names:
                    frame.label += "; 实参 " + ", ".join(
                        f"{name}={item if item is not None else '动态'}"
                        for name, item in zip(names, bindings)
                    )
                frame.parents = tuple(
                    item.proof
                    for item in (
                        *actual.values,
                        *((actual.tail,) if actual.tail else ()),
                    )
                    if item.proof >= 0
                )
                frame.stage, frame.bound_count = "return", len(bound)
                active_functions.setdefault(frame.function, []).append(frame)
                parts = (
                    split_value_expressions(
                        frame.row.expression, lua=self.functions.lua
                    )
                    if frame.row
                    else ()
                )
                if parts is None:
                    self._save(
                        key,
                        unknown_values("返回值列表未闭合，未假定为空", multi=key.multi),
                    )
                    continue
                frame.cursor = 0
                frame.dependencies = (
                    self._key(
                        "",
                        frame.function,
                        frame.row.expression_start if frame.row else 0,
                        frame.function,
                        bindings,
                        multi=True,
                        parts=parts,
                        unknown_tail=unknown_tail,
                    ),
                )
                continue
            elif frame.stage == "fourcc":
                item = values[0].at(0)
                string = (
                    literal_string_value(item.value)
                    if item.value is not None and item.kind == "string"
                    else None
                )
                raw = f"FourCC({string!r})" if string is not None else ""
                valid = bool(raw and literal_object_code(raw))
                result = StaticValue(
                    raw if valid else None,
                    "object" if valid else "unknown",
                    "" if valid else item.diagnostic or "FourCC 实参不是四字节文本",
                    item.proof,
                )
                self._save(key, StaticValues((result,)))
            elif frame.stage == "alias":
                self._save(key, StaticValues((values[0].at(frame.ordinal),)))
            elif frame.stage == "numeric":
                assert frame.numeric is not None
                operands = tuple(group.at(0) for group in values)
                note = "; ".join(
                    dict.fromkeys(
                        item.diagnostic or f"非数值操作数: {item.kind}"
                        for item in operands
                        if item.kind != "number" or item.value is None
                    )
                )
                expression = (
                    frame.numeric.render(tuple(item.value or "" for item in operands))
                    if not note
                    else ""
                )
                number = (
                    static_number(expression, lua=self.functions.lua is True)
                    if expression
                    else None
                )
                result = (
                    StaticValue(format_number(number), "number")
                    if number is not None
                    else StaticValue(
                        None,
                        diagnostic="数值表达式未静态确定: "
                        + (note or "语法、除零或非有限结果"),
                    )
                )
                self._save(
                    key,
                    self._proof(
                        StaticValues((result,)),
                        f"静态数值表达式: {key.text}",
                        tuple(item.proof for item in operands if item.proof >= 0),
                        numeric=bool(operands),
                    ),
                )
            elif frame.stage == "geometry":
                actual = values[0]
                if frame.label in GEOMETRY_CONSTRUCTORS:
                    replacements = tuple(
                        StaticValue(format_number(number), "number", proof=item.proof)
                        if item.kind == "unknown"
                        and index < len(frame.call_arguments)
                        and (
                            number := static_number(
                                frame.call_arguments[index],
                                lua=self.functions.lua is True,
                            )
                        )
                        is not None
                        else item
                        for index, item in enumerate(actual.values)
                    )
                    result = geometry_constructor(
                        frame.label, StaticValues(replacements, actual.tail)
                    )
                elif frame.label in GEOMETRY_TRANSFORMS:
                    spec = GEOMETRY_TRANSFORMS[frame.label]
                    notes = dict.fromkeys(
                        note
                        for index, kind in enumerate(spec)
                        if kind != "number"
                        and (
                            expression := frame.call_arguments[index]
                            if index < len(frame.call_arguments)
                            else frame.call_arguments[-1]
                            if frame.call_arguments
                            else ""
                        )
                        and (
                            note := self.geometry_note(
                                expression, key.owner, key.position
                            )
                        )
                    )
                    result = (
                        StaticValue(None, diagnostic="; ".join(notes))
                        if notes
                        else geometry_transform(frame.label, actual)
                    )
                elif frame.label in GEOMETRY_READERS:
                    kind, index = GEOMETRY_READERS[frame.label]
                    item = actual.at(0)
                    coordinates = geometry_coordinates(item)
                    note = (
                        self.geometry_note(
                            frame.call_arguments[0], key.owner, key.position
                        )
                        if frame.call_arguments
                        else "缺少几何参数"
                    )
                    if item.kind != kind or coordinates is None or note:
                        result = StaticValue(
                            None,
                            diagnostic=note or item.diagnostic or "几何句柄未静态确定",
                        )
                    elif kind == "rect" and (
                        coordinates[0] > coordinates[2]
                        or coordinates[1] > coordinates[3]
                    ):
                        result = StaticValue(
                            None, diagnostic="矩形上下界顺序未确认，未推导投影"
                        )
                    elif index < 4:
                        result = StaticValue(
                            format_number(coordinates[index]), "number"
                        )
                    else:
                        x, y = geometry_center(coordinates)
                        result = (
                            geometry_constructor(
                                "Location",
                                StaticValues(
                                    (
                                        StaticValue(format_number(x), "number"),
                                        StaticValue(format_number(y), "number"),
                                    )
                                ),
                            )
                            if index == 6
                            else StaticValue(
                                format_number(x if index == 4 else y), "number"
                            )
                        )
                        if not all(math.isfinite(value) for value in (x, y)):
                            result = StaticValue(
                                None, diagnostic="矩形中心超出有限数值范围"
                            )
                elif frame.label in GEOMETRY_PREDICATES:
                    result = StaticValue(
                        None,
                        diagnostic="只读区域判断不作为静态坐标值；调用与参数证据保留",
                    )
                else:
                    result = StaticValue(
                        None, diagnostic="几何修改调用只保留副作用证据，不作为静态坐标"
                    )
                parents = tuple(item.proof for item in actual.values if item.proof >= 0)
                self._save(
                    key,
                    self._proof(
                        StaticValues((result,)),
                        f"{frame.label}; 几何表达式: {key.text}",
                        parents,
                        numeric=frame.label in GEOMETRY_TRANSFORMS,
                    ),
                )
            elif frame.stage in {"select", "table.unpack"}:
                result = (
                    select_values(values[0])
                    if frame.stage == "select"
                    else unpack_values(values[0], values[1])
                )
                parents = tuple(
                    item.proof
                    for group in values
                    for item in (*group.values, *((group.tail,) if group.tail else ()))
                    if item.proof >= 0
                )
                self._save(key, self._proof(result, frame.label, parents))
            else:
                self._save(key, self._proof(values[0], frame.label, frame.parents))
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

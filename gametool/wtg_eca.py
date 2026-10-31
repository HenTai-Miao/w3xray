"""Schema-driven WTG ECA function-tree parsing."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from typing import cast

from .trigger_schema import TriggerFunctionKind, TriggerSchema
from .wtg_diagnostics import EcaParseError
from .wtg_models import TriggerEcaFunction, TriggerEcaParameter
from .wtg_reader import WtgReader

type _ParseNode = TriggerEcaFunction | TriggerEcaParameter
type _ParseSteps = Generator[_ParseSteps, _ParseNode, _ParseNode]


def _complete_steps(initial: _ParseSteps) -> _ParseNode:
    """Drive nested grammar operations on a heap stack instead of Python frames."""
    stack = [initial]
    completed: _ParseNode | None = None
    try:
        while stack:
            try:
                nested = (
                    next(stack[-1]) if completed is None else stack[-1].send(completed)
                )
            except StopIteration as end:
                completed = cast(_ParseNode, end.value)
                stack.pop()
            else:
                stack.append(nested)
                completed = None
    finally:
        # A bad nested record releases all suspended parsers without recursively
        # unwinding a potentially deep chain of generators.
        for suspended in reversed(stack):
            suspended.close()
    assert completed is not None
    return completed


def parse_eca_functions(
    reader: WtgReader,
    trigger_name: str,
    count: int,
    schema: TriggerSchema,
    *,
    version: int,
    depth: int = 0,
) -> Iterator[TriggerEcaFunction]:
    """Read ``count`` WTG ECA functions from the current reader position."""
    for index in range(count):
        yield read_eca(
            reader,
            trigger_name,
            schema,
            has_branch=False,
            version=version,
            depth=depth,
            ordinal=index + 1,
        )


def read_eca(
    reader: WtgReader,
    trigger_name: str,
    schema: TriggerSchema,
    *,
    has_branch: bool,
    version: int,
    depth: int,
    ordinal: int = 0,
) -> TriggerEcaFunction:
    """Read one TriggerFunction using TriggerData for its parameter count."""
    result = _complete_steps(
        _eca_steps(
            reader,
            trigger_name,
            schema,
            has_branch=has_branch,
            version=version,
            depth=depth,
            ordinal=ordinal,
        )
    )
    assert isinstance(result, TriggerEcaFunction)
    return result


def _eca_steps(
    reader: WtgReader,
    trigger_name: str,
    schema: TriggerSchema,
    *,
    has_branch: bool,
    version: int,
    depth: int,
    ordinal: int,
) -> _ParseSteps:
    source_offset = reader.offset
    function_type = reader.i32()
    branch = reader.i32() if has_branch else 0
    name = reader.cstr()
    is_enabled = bool(reader.i32())
    kind = _kind_from_function_type(function_type, trigger_name, name, source_offset)
    function_schema = schema.get(kind, name)
    if function_schema is None:
        raise EcaParseError(
            trigger_name, name, source_offset, "missing TriggerData schema"
        )
    parameters: list[TriggerEcaParameter] = []
    for type_name in function_schema.parameter_types:
        parameter = yield _parameter_steps(
            reader,
            trigger_name,
            name,
            schema,
            type_name,
            version=version,
            depth=depth + 1,
        )
        assert isinstance(parameter, TriggerEcaParameter)
        parameters.append(parameter)
    child_count = reader.bounded_count("child ECA") if version >= 7 else 0
    children: list[TriggerEcaFunction] = []
    for index in range(child_count):
        child = yield _eca_steps(
            reader,
            trigger_name,
            schema,
            has_branch=True,
            version=version,
            depth=depth + 1,
            ordinal=index + 1,
        )
        assert isinstance(child, TriggerEcaFunction)
        children.append(child)
    return TriggerEcaFunction(
        trigger_name=trigger_name,
        function_type=function_type,
        name=name,
        is_enabled=is_enabled,
        parameters=tuple(parameters),
        children=tuple(children),
        depth=depth,
        ordinal=ordinal,
        branch=branch,
        source_offset=source_offset,
    )


def function_type_label(value: int) -> str:
    """Return a readable editor-level function type label."""
    return {0: "事件", 1: "条件", 2: "动作", 3: "调用"}.get(value, str(value))


def parameter_type_label(value: int) -> str:
    """Return a readable parameter type label."""
    return {-1: "未定义", 0: "原始", 1: "变量", 2: "函数", 3: "字符串"}.get(
        value, str(value)
    )


def _parameter_steps(
    reader: WtgReader,
    trigger_name: str,
    function_name: str,
    schema: TriggerSchema,
    type_name: str,
    *,
    version: int,
    depth: int,
) -> _ParseSteps:
    source_offset = reader.offset
    parameter_type = reader.i32()
    if parameter_type < -1 or parameter_type > 3:
        raise EcaParseError(
            trigger_name,
            function_name,
            source_offset,
            f"invalid parameter type {parameter_type}",
        )
    value = reader.cstr()
    have_function = reader.i32()
    nested = None
    if have_function:
        if parameter_type != 2:
            raise EcaParseError(
                trigger_name,
                function_name,
                source_offset,
                "nested function on non-function parameter",
            )
        nested = yield _eca_steps(
            reader,
            trigger_name,
            schema,
            has_branch=False,
            version=version,
            depth=depth,
            ordinal=0,
        )
        assert isinstance(nested, TriggerEcaFunction)
    have_array = reader.i32()
    array_indexer = None
    if have_array:
        if parameter_type != 1:
            raise EcaParseError(
                trigger_name,
                function_name,
                source_offset,
                "array indexer on non-variable parameter",
            )
        array_indexer = yield _parameter_steps(
            reader,
            trigger_name,
            function_name,
            schema,
            "array-index",
            version=version,
            depth=depth + 1,
        )
        assert isinstance(array_indexer, TriggerEcaParameter)
    return TriggerEcaParameter(
        parameter_type=parameter_type,
        value=value,
        nested_function=nested,
        begin_function=have_function,
        end_function=have_array,
        have_array_indexer=have_array,
        array_indexer=array_indexer,
        expected_type=type_name,
        source_offset=source_offset,
    )


def _kind_from_function_type(
    value: int,
    trigger_name: str,
    function_name: str,
    source_offset: int,
) -> TriggerFunctionKind:
    match value:
        case 0:
            return TriggerFunctionKind.EVENT
        case 1:
            return TriggerFunctionKind.CONDITION
        case 2:
            return TriggerFunctionKind.ACTION
        case 3:
            return TriggerFunctionKind.CALL
        case _:
            raise EcaParseError(
                trigger_name,
                function_name,
                source_offset,
                f"invalid function type {value}",
            )

"""Schema-driven WTG ECA function-tree parsing."""

from __future__ import annotations

from .trigger_schema import TriggerFunctionKind, TriggerSchema
from .wtg_diagnostics import EcaParseError
from .wtg_models import TriggerEcaFunction, TriggerEcaParameter
from .wtg_reader import WtgReader


def parse_eca_functions(
    reader: WtgReader,
    trigger_name: str,
    count: int,
    schema: TriggerSchema,
    *,
    version: int,
    depth: int = 0,
) -> tuple[TriggerEcaFunction, ...]:
    """Read ``count`` WTG ECA functions from the current reader position."""
    return tuple(
        read_eca(reader, trigger_name, schema, has_branch=False, version=version, depth=depth, ordinal=index + 1)
        for index in range(count)
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
    source_offset = reader.offset
    function_type = reader.i32()
    branch = reader.i32() if has_branch else 0
    name = reader.cstr()
    is_enabled = bool(reader.i32())
    kind = _kind_from_function_type(function_type)
    function_schema = schema.get(kind, name)
    if function_schema is None:
        raise EcaParseError(trigger_name, name, source_offset, "missing TriggerData schema")
    parameters = tuple(
        _read_parameter(reader, trigger_name, name, schema, type_name, depth=depth + 1)
        for type_name in function_schema.parameter_types
    )
    child_count = reader.bounded_count("child ECA") if version >= 7 else 0
    children = tuple(
        read_eca(reader, trigger_name, schema, has_branch=True, version=version, depth=depth + 1, ordinal=index + 1)
        for index in range(child_count)
    )
    return TriggerEcaFunction(
        trigger_name=trigger_name,
        function_type=function_type,
        name=name,
        is_enabled=is_enabled,
        parameters=parameters,
        children=children,
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
    return {-1: "未定义", 0: "原始", 1: "变量", 2: "函数", 3: "字符串"}.get(value, str(value))


def _read_parameter(
    reader: WtgReader,
    trigger_name: str,
    function_name: str,
    schema: TriggerSchema,
    type_name: str,
    *,
    depth: int,
) -> TriggerEcaParameter:
    source_offset = reader.offset
    parameter_type = reader.i32()
    if parameter_type < -1 or parameter_type > 3:
        raise EcaParseError(trigger_name, function_name, source_offset, f"invalid parameter type {parameter_type}")
    value = reader.cstr()
    have_function = reader.i32()
    nested = None
    if have_function:
        if parameter_type != 2:
            raise EcaParseError(trigger_name, function_name, source_offset, "nested function on non-function parameter")
        nested = read_eca(reader, trigger_name, schema, has_branch=False, version=7, depth=depth, ordinal=0)
    have_array = reader.i32()
    array_indexer = None
    if have_array:
        if parameter_type != 1:
            raise EcaParseError(trigger_name, function_name, source_offset, "array indexer on non-variable parameter")
        array_indexer = _read_parameter(reader, trigger_name, function_name, schema, "array-index", depth=depth + 1)
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


def _kind_from_function_type(value: int) -> TriggerFunctionKind:
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
            raise EcaParseError("", "", 0, f"invalid function type {value}")

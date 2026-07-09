"""Raw WTG ECA function-tree parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

_MAX_COUNT: Final = 100_000


class EcaReader(Protocol):
    """Reader methods needed by the WTG ECA parser."""

    def i32(self) -> int: ...

    def cstr(self) -> str: ...


@dataclass(frozen=True, slots=True)
class TriggerEcaParameter:
    parameter_type: int
    value: str
    nested_function: TriggerEcaFunction | None = None
    begin_function: int = 0
    end_function: int = 0


@dataclass(frozen=True, slots=True)
class TriggerEcaFunction:
    trigger_name: str
    function_type: int
    name: str
    is_enabled: bool
    parameters: tuple[TriggerEcaParameter, ...]
    children: tuple[TriggerEcaFunction, ...]
    depth: int = 0
    ordinal: int = 0


def parse_eca_functions(
    reader: EcaReader,
    trigger_name: str,
    count: int,
    *,
    depth: int = 0,
) -> tuple[TriggerEcaFunction, ...]:
    """Read ``count`` WTG ECA functions from the current reader position."""
    return tuple(
        _read_function(reader, trigger_name, depth=depth, ordinal=index + 1)
        for index in range(_bounded(count))
    )


def function_type_label(value: int) -> str:
    """Return a readable editor-level function type label."""
    labels = {
        0: "事件",
        1: "条件",
        2: "动作",
        3: "调用",
    }
    return labels.get(value, str(value))


def parameter_type_label(value: int) -> str:
    """Return a readable parameter type label."""
    labels = {
        0: "原始",
        1: "变量",
        2: "函数",
    }
    return labels.get(value, str(value))


def _read_function(
    reader: EcaReader,
    trigger_name: str,
    *,
    depth: int,
    ordinal: int,
) -> TriggerEcaFunction:
    function_type = reader.i32()
    name = reader.cstr()
    is_enabled = bool(reader.i32())
    parameter_count = _bounded(reader.i32())
    parameters = tuple(
        _read_parameter(reader, trigger_name, depth=depth + 1)
        for _index in range(parameter_count)
    )
    child_count = _bounded(reader.i32())
    children = tuple(
        _read_function(reader, trigger_name, depth=depth + 1, ordinal=index + 1)
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
    )


def _read_parameter(
    reader: EcaReader,
    trigger_name: str,
    *,
    depth: int,
) -> TriggerEcaParameter:
    parameter_type = reader.i32()
    value = reader.cstr()
    begin_function = reader.i32()
    nested = None
    if begin_function:
        nested = _read_function(reader, trigger_name, depth=depth, ordinal=0)
    end_function = reader.i32()
    return TriggerEcaParameter(
        parameter_type=parameter_type,
        value=value,
        nested_function=nested,
        begin_function=begin_function,
        end_function=end_function,
    )


def _bounded(value: int) -> int:
    if value < 0 or value > _MAX_COUNT:
        raise ValueError(f"invalid war3map.wtg ECA count: {value}")
    return value

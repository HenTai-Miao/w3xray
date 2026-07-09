"""war3map.wtg trigger tree summary parser."""

from __future__ import annotations

from dataclasses import dataclass
import struct

from .war3_encoding import decode_warcraft_string
from .wtg_eca import TriggerEcaFunction, parse_eca_functions

_MAX_COUNT = 100_000
_REFORGED_MARKER = 0x80000004


@dataclass(frozen=True, slots=True)
class TriggerCategory:
    category_id: int
    name: str
    is_comment: bool = False
    parent_id: int = 0


@dataclass(frozen=True, slots=True)
class TriggerVariable:
    name: str
    type_name: str
    category: int
    is_array: bool
    array_size: int
    is_initialized: bool
    initial_value: str
    object_id: int = 0
    parent_id: int = 0


@dataclass(frozen=True, slots=True)
class TriggerHeader:
    name: str
    description: str
    is_comment: bool
    is_enabled: bool
    is_custom_text: bool
    is_initially_off: bool
    run_on_init: bool
    category_id: int
    function_count: int
    object_type: int = 8
    object_id: int = 0


@dataclass(frozen=True, slots=True)
class TriggerTreeSummary:
    version: int
    is_reforged: bool
    category_count: int
    variable_count: int
    trigger_count: int
    comment_count: int
    script_count: int
    categories: tuple[TriggerCategory, ...]
    variables: tuple[TriggerVariable, ...]
    triggers: tuple[TriggerHeader, ...]
    eca_functions: tuple[TriggerEcaFunction, ...] = ()
    has_unexpanded_functions: bool = False


class _Reader:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def raw(self, size: int) -> bytes:
        if self._pos + size > len(self._data):
            raise IndexError("raw 越界")
        value = self._data[self._pos:self._pos + size]
        self._pos += size
        return value

    def i32(self) -> int:
        return struct.unpack("<i", self.raw(4))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.raw(4))[0]

    def cstr(self) -> str:
        end = self._data.find(b"\x00", self._pos)
        if end < 0:
            raise IndexError("cstr 缺少终止符")
        raw = self._data[self._pos:end]
        self._pos = end + 1
        return _decode_string(raw)


def parse_wtg(data: bytes) -> TriggerTreeSummary:
    """Parse trigger tree metadata from war3map.wtg.

    The parser summarizes the trigger tree and variables. It deliberately does
    not expand ECA function bodies because those require TriggerData.txt's
    function parameter table.
    """
    reader = _Reader(data)
    try:
        if reader.raw(4) != b"WTG!":
            raise ValueError("not a war3map.wtg file")
        marker = reader.u32()
        if marker == _REFORGED_MARKER:
            return _parse_reforged(reader)
        return _parse_classic(reader, _to_i32(marker))
    except (struct.error, IndexError) as exc:
        raise ValueError("truncated war3map.wtg") from exc


def _parse_classic(reader: _Reader, version: int) -> TriggerTreeSummary:
    categories = tuple(_read_classic_category(reader, version) for _ in range(_bounded(reader.i32())))
    reader.i32()
    variables = tuple(_read_classic_variable(reader, version) for _ in range(_bounded(reader.i32())))
    trigger_count = _bounded(reader.i32())
    triggers: list[TriggerHeader] = []
    eca_functions: list[TriggerEcaFunction] = []
    has_unexpanded = False
    for _index in range(trigger_count):
        trigger = _read_classic_trigger(reader, version)
        triggers.append(trigger)
        if trigger.function_count > 0:
            try:
                eca_functions.extend(parse_eca_functions(reader, trigger.name, trigger.function_count))
            except (IndexError, ValueError):
                has_unexpanded = True
                break
    return TriggerTreeSummary(
        version=version,
        is_reforged=False,
        category_count=len(categories),
        variable_count=len(variables),
        trigger_count=trigger_count,
        comment_count=sum(1 for trigger in triggers if trigger.is_comment),
        script_count=sum(1 for trigger in triggers if trigger.is_custom_text),
        categories=categories,
        variables=variables,
        triggers=tuple(triggers),
        eca_functions=tuple(eca_functions),
        has_unexpanded_functions=has_unexpanded,
    )


def _parse_reforged(reader: _Reader) -> TriggerTreeSummary:
    version = reader.i32()
    type_counts = tuple(_read_type_info(reader) for _ in range(7))
    reader.i32()
    reader.i32()
    reader.i32()
    variables = tuple(_read_reforged_variable(reader) for _ in range(_bounded(reader.i32())))
    object_count = _bounded(reader.i32())
    categories: list[TriggerCategory] = []
    triggers: list[TriggerHeader] = []
    eca_functions: list[TriggerEcaFunction] = []
    has_unexpanded = False
    for _index in range(object_count):
        object_type = reader.i32()
        match object_type:
            case 1:
                _read_reforged_map_header(reader)
            case 4:
                categories.append(_read_reforged_category(reader))
            case 8 | 16 | 32:
                trigger = _read_reforged_trigger(reader, object_type)
                triggers.append(trigger)
                if trigger.function_count > 0:
                    try:
                        eca_functions.extend(parse_eca_functions(reader, trigger.name, trigger.function_count))
                    except (IndexError, ValueError):
                        has_unexpanded = True
                        break
            case 64:
                _read_reforged_variable_tree_item(reader)
            case _:
                break
    return TriggerTreeSummary(
        version=version,
        is_reforged=True,
        category_count=type_counts[2],
        variable_count=len(variables),
        trigger_count=type_counts[3],
        comment_count=type_counts[4],
        script_count=type_counts[5],
        categories=tuple(categories),
        variables=variables,
        triggers=tuple(triggers),
        eca_functions=tuple(eca_functions),
        has_unexpanded_functions=has_unexpanded,
    )


def _read_classic_category(reader: _Reader, version: int) -> TriggerCategory:
    category_id = reader.i32()
    name = reader.cstr()
    is_comment = bool(reader.i32()) if version >= 7 else False
    return TriggerCategory(category_id=category_id, name=name, is_comment=is_comment)


def _read_classic_variable(reader: _Reader, version: int) -> TriggerVariable:
    name = reader.cstr()
    type_name = reader.cstr()
    category = reader.i32()
    is_array = bool(reader.i32())
    array_size = reader.i32() if version >= 7 else 1
    is_initialized = bool(reader.i32())
    initial_value = reader.cstr()
    return TriggerVariable(name, type_name, category, is_array, array_size, is_initialized, initial_value)


def _read_classic_trigger(reader: _Reader, version: int) -> TriggerHeader:
    name = reader.cstr()
    description = reader.cstr()
    is_comment = bool(reader.i32()) if version >= 7 else False
    return TriggerHeader(
        name=name,
        description=description,
        is_comment=is_comment,
        is_enabled=bool(reader.i32()),
        is_custom_text=bool(reader.i32()),
        is_initially_off=bool(reader.i32()),
        run_on_init=bool(reader.i32()),
        category_id=reader.i32(),
        function_count=_bounded(reader.i32()),
    )


def _read_type_info(reader: _Reader) -> int:
    total = _bounded(reader.i32())
    _bounded(reader.i32())
    return total


def _read_reforged_variable(reader: _Reader) -> TriggerVariable:
    name = reader.cstr()
    type_name = reader.cstr()
    category = reader.i32()
    is_array = bool(reader.i32())
    array_size = reader.i32()
    is_initialized = bool(reader.i32())
    initial_value = reader.cstr()
    object_id = reader.i32()
    parent_id = reader.i32()
    return TriggerVariable(name, type_name, category, is_array, array_size, is_initialized,
                           initial_value, object_id, parent_id)


def _read_reforged_map_header(reader: _Reader) -> None:
    reader.i32()
    reader.cstr()
    reader.i32()
    reader.i32()
    reader.i32()


def _read_reforged_category(reader: _Reader) -> TriggerCategory:
    object_id = reader.i32()
    name = reader.cstr()
    is_comment = bool(reader.i32())
    reader.i32()
    parent_id = reader.i32()
    return TriggerCategory(object_id, name, is_comment, parent_id)


def _read_reforged_trigger(reader: _Reader, object_type: int) -> TriggerHeader:
    name = reader.cstr()
    description = reader.cstr()
    is_comment = bool(reader.i32())
    object_id = reader.i32()
    enabled = bool(reader.i32())
    custom = bool(reader.i32())
    initially_off = bool(reader.i32())
    run_on_init = bool(reader.i32())
    parent_id = reader.i32()
    function_count = _bounded(reader.i32())
    return TriggerHeader(name, description, is_comment, enabled, custom, initially_off,
                         run_on_init, parent_id, function_count, object_type, object_id)


def _read_reforged_variable_tree_item(reader: _Reader) -> None:
    reader.i32()
    reader.cstr()
    reader.i32()


def _bounded(value: int) -> int:
    if value < 0 or value > _MAX_COUNT:
        raise ValueError(f"invalid war3map.wtg count: {value}")
    return value


def _to_i32(value: int) -> int:
    return value - 0x1_0000_0000 if value > 0x7FFF_FFFF else value


def _decode_string(raw: bytes) -> str:
    return decode_warcraft_string(raw, allow_latin1=True)

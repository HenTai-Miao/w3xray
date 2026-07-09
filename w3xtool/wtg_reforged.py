"""Reforged 0x80000004 WTG trigger-tree parser."""

from __future__ import annotations

from .trigger_schema import TriggerSchema
from .wtg_classic import _read_missing_function
from .wtg_diagnostics import EcaParseError, TriggerParseFailure, UnknownTriggerFunction, WtgReadError
from .wtg_eca import parse_eca_functions
from .wtg_models import TriggerCategory, TriggerHeader, TriggerTreeSummary, TriggerVariable
from .wtg_reader import WtgReader

_ITEM_TYPES = (1, 2, 4, 8, 16, 32, 64, 128)


def parse_reforged(reader: WtgReader, schema: TriggerSchema | None) -> TriggerTreeSummary:
    version = reader.i32()
    type_counts = _read_type_counts(reader)
    reader.i32()
    variables = tuple(_read_variable(reader) for _ in range(reader.bounded_count("variable")))
    object_count = reader.bounded_count("trigger item")
    categories: list[TriggerCategory] = []
    triggers: list[TriggerHeader] = []
    eca_functions = []
    missing: list[UnknownTriggerFunction] = []
    failures: list[TriggerParseFailure] = []
    for _index in range(object_count):
        object_type = reader.i32()
        if object_type in (1, 4):
            categories.append(_read_category(reader))
        elif object_type in (8, 16, 32):
            trigger = _read_trigger(reader, object_type)
            triggers.append(trigger)
            if not _read_trigger_functions(reader, trigger, schema, version, eca_functions, missing, failures):
                break
        elif object_type == 64:
            _read_variable_tree_item(reader)
        else:
            failures.append(TriggerParseFailure("", "", reader.offset - 4, f"unsupported item type {object_type}"))
            break
    return TriggerTreeSummary(
        version=version,
        is_reforged=True,
        category_count=type_counts.get(4, 0),
        variable_count=len(variables),
        trigger_count=type_counts.get(8, 0),
        comment_count=type_counts.get(16, 0),
        script_count=type_counts.get(32, 0),
        categories=tuple(categories),
        variables=variables,
        triggers=tuple(triggers),
        eca_functions=tuple(eca_functions),
        has_unexpanded_functions=bool(missing or failures),
        missing_schema_functions=tuple(missing),
        parse_failures=tuple(failures),
    )


def _read_type_counts(reader: WtgReader) -> dict[int, int]:
    counts: dict[int, int] = {}
    for item_type in _ITEM_TYPES:
        counts[item_type] = reader.bounded_count("trigger item type")
        deleted_count = reader.bounded_count("deleted trigger item")
        for _index in range(deleted_count):
            reader.i32()
    return counts


def _read_variable(reader: WtgReader) -> TriggerVariable:
    name = reader.cstr()
    type_name = reader.cstr()
    category = reader.i32()
    is_array = bool(reader.i32())
    array_size = reader.i32()
    is_initialized = bool(reader.i32())
    initial_value = reader.cstr()
    object_id = reader.i32()
    parent_id = reader.i32()
    return TriggerVariable(name, type_name, category, is_array, array_size, is_initialized, initial_value, object_id, parent_id)


def _read_category(reader: WtgReader) -> TriggerCategory:
    object_id = reader.i32()
    name = reader.cstr()
    is_comment = bool(reader.i32())
    reader.i32()
    parent_id = reader.i32()
    return TriggerCategory(object_id, name, is_comment, parent_id)


def _read_trigger(reader: WtgReader, object_type: int) -> TriggerHeader:
    name = reader.cstr()
    description = reader.cstr()
    is_comment = bool(reader.i32())
    object_id = reader.i32()
    enabled = bool(reader.i32())
    custom = bool(reader.i32())
    initially_off = bool(reader.i32())
    run_on_init = bool(reader.i32())
    parent_id = reader.i32()
    function_count = reader.bounded_count("trigger function")
    return TriggerHeader(name, description, is_comment, enabled, custom, initially_off, run_on_init, parent_id, function_count, object_type, object_id)


def _read_trigger_functions(
    reader: WtgReader,
    trigger: TriggerHeader,
    schema: TriggerSchema | None,
    version: int,
    eca_functions: list,
    missing: list[UnknownTriggerFunction],
    failures: list[TriggerParseFailure],
) -> bool:
    if trigger.function_count <= 0:
        return True
    if schema is None:
        try:
            missing.append(_read_missing_function(reader, trigger.name, has_branch=False))
        except WtgReadError as exc:
            failures.append(TriggerParseFailure(trigger.name, "", exc.offset, exc.reason))
        return False
    try:
        eca_functions.extend(parse_eca_functions(reader, trigger.name, trigger.function_count, schema, version=version))
    except EcaParseError as exc:
        if exc.reason == "missing TriggerData schema":
            missing.append(UnknownTriggerFunction(trigger.name, exc.function_name, 0, exc.offset))
        else:
            failures.append(TriggerParseFailure(trigger.name, exc.function_name, exc.offset, exc.reason))
        return False
    except WtgReadError as exc:
        failures.append(TriggerParseFailure(trigger.name, "", exc.offset, exc.reason))
        return False
    return True


def _read_variable_tree_item(reader: WtgReader) -> None:
    reader.i32()
    reader.cstr()
    reader.i32()

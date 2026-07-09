"""Classic v4/v7 WTG trigger-tree parser."""

from __future__ import annotations

from .trigger_schema import TriggerSchema
from .wtg_diagnostics import EcaParseError, TriggerParseFailure, UnknownTriggerFunction, WtgReadError
from .wtg_eca import parse_eca_functions
from .wtg_models import TriggerCategory, TriggerHeader, TriggerTreeSummary, TriggerVariable
from .wtg_reader import WtgReader


def parse_classic(reader: WtgReader, version: int, schema: TriggerSchema | None) -> TriggerTreeSummary:
    categories = tuple(_read_category(reader, version) for _ in range(reader.bounded_count("category")))
    reader.i32()
    variables = tuple(_read_variable(reader, version) for _ in range(reader.bounded_count("variable")))
    trigger_count = reader.bounded_count("trigger")
    triggers: list[TriggerHeader] = []
    eca_functions = []
    missing: list[UnknownTriggerFunction] = []
    failures: list[TriggerParseFailure] = []
    for _index in range(trigger_count):
        trigger = _read_trigger(reader, version)
        triggers.append(trigger)
        if trigger.function_count <= 0:
            continue
        if schema is None:
            try:
                missing.append(_read_missing_function(reader, trigger.name, has_branch=False))
            except WtgReadError as exc:
                failures.append(TriggerParseFailure(trigger.name, "", exc.offset, exc.reason))
            break
        try:
            eca_functions.extend(parse_eca_functions(reader, trigger.name, trigger.function_count, schema, version=version))
        except EcaParseError as exc:
            if exc.reason == "missing TriggerData schema":
                missing.append(UnknownTriggerFunction(trigger.name, exc.function_name, 0, exc.offset))
            else:
                failures.append(TriggerParseFailure(trigger.name, exc.function_name, exc.offset, exc.reason))
            break
        except WtgReadError as exc:
            failures.append(TriggerParseFailure(trigger.name, "", exc.offset, exc.reason))
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
        has_unexpanded_functions=bool(missing or failures),
        missing_schema_functions=tuple(missing),
        parse_failures=tuple(failures),
    )


def _read_category(reader: WtgReader, version: int) -> TriggerCategory:
    category_id = reader.i32()
    name = reader.cstr()
    is_comment = bool(reader.i32()) if version >= 7 else False
    return TriggerCategory(category_id=category_id, name=name, is_comment=is_comment)


def _read_variable(reader: WtgReader, version: int) -> TriggerVariable:
    name = reader.cstr()
    type_name = reader.cstr()
    category = reader.i32()
    is_array = bool(reader.i32())
    array_size = reader.i32() if version >= 7 else 1
    is_initialized = bool(reader.i32())
    initial_value = reader.cstr()
    return TriggerVariable(name, type_name, category, is_array, array_size, is_initialized, initial_value)


def _read_trigger(reader: WtgReader, version: int) -> TriggerHeader:
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
        function_count=reader.bounded_count("trigger function"),
    )


def _read_missing_function(reader: WtgReader, trigger_name: str, *, has_branch: bool) -> UnknownTriggerFunction:
    offset = reader.offset
    function_type = reader.i32()
    if has_branch:
        reader.i32()
    function_name = reader.cstr()
    reader.i32()
    return UnknownTriggerFunction(trigger_name, function_name, function_type, offset)

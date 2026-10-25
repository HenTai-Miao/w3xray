"""Source-local trigger instances and callback evidence, without executing scripts."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
import re
from types import MappingProxyType

from .save_call_context import extract_call_args
from .script_lexing import script_views
from .script_scopes import CallSpan, ScriptStructure, script_structure
from .script_function_graph import (
    FunctionReference as CallbackReference,
    script_functions,
)
from .script_assignments import (
    expression_key as _expression_key,
    reference_parts as _handle_parts,
    script_assignments,
)

_EVENT = re.compile(r"\b(?=[A-Z0-9_]*EVENT)[A-Z][A-Z0-9_]*\b")
_CALLBACK_APIS = frozenset(
    {
        "TriggerAddAction",
        "TriggerAddActionBJ",
        "TriggerAddCondition",
        "TriggerAddConditionBJ",
        "TimerStart",
    }
)

type TriggerInstance = tuple[int | None, str, int]


@dataclass(frozen=True, slots=True)
class TriggerSite:
    call: CallSpan
    arguments: tuple[str, ...]
    instance: TriggerInstance
    callback: CallbackReference | None = None
    events: tuple[str, ...] = ()
    diagnostic: str = ""


@dataclass(frozen=True, slots=True)
class ScriptTriggerBindings:
    structure: ScriptStructure
    sites: tuple[TriggerSite, ...]
    by_start: Mapping[int, TriggerSite]
    instances: Mapping[TriggerInstance, tuple[TriggerSite, ...]]


@lru_cache(maxsize=8)
def script_trigger_bindings(
    text: str, *, lua: bool | None = None
) -> ScriptTriggerBindings:
    """Collect every registration and keep reused handles within their own assignment."""
    structure = script_structure(text, lua=lua)
    views = script_views(text, lua=lua)
    assignments: dict[tuple[int | None, str], list[int]] = {}
    for assignment in script_assignments(text, lua=lua):
        assignments.setdefault((assignment.owner, assignment.key), []).append(
            assignment.offset
        )
    callbacks = script_functions(text, lua=lua)
    sites: list[TriggerSite] = []
    instances: dict[TriggerInstance, list[TriggerSite]] = {}
    for call in structure.calls:
        api = call.name.removeprefix("_G.")
        if api not in _CALLBACK_APIS and not api.startswith("TriggerRegister"):
            continue
        args = extract_call_args(views, call.open + 1)
        handle = _expression_key(args[0], lua=lua) if args else ""
        prefixes, diagnostic = (
            _handle_parts(args[0], lua=lua) if args else ((), "注册缺少句柄")
        )
        assignment = -1
        for prefix in prefixes:
            offsets = assignments.get((call.owner, prefix), ())
            index = bisect_right(offsets, call.start)
            if index:
                assignment = max(assignment, offsets[index - 1])
        instance = (call.owner, handle, assignment if prefixes else call.start)
        callback = None
        if api in _CALLBACK_APIS and len(args) >= 2:
            cursor = call.open + 1
            start = cursor
            for arg in args:
                start = views.arguments.find(arg, cursor, call.end)
                if start < 0:
                    break
                cursor = start + len(arg)
            if start >= 0:
                callback = callbacks.resolve(args[-1], start, call.owner)
        events = (
            tuple(
                dict.fromkeys(
                    match.group()
                    for arg in args[1:]
                    for match in _EVENT.finditer(script_views(arg, lua=lua).syntax)
                )
            )
            if api.startswith("TriggerRegister")
            else ()
        )
        site = TriggerSite(call, args, instance, callback, events, diagnostic)
        sites.append(site)
        instances.setdefault(instance, []).append(site)
    return ScriptTriggerBindings(
        structure,
        tuple(sites),
        MappingProxyType({site.call.start: site for site in sites}),
        MappingProxyType({key: tuple(values) for key, values in instances.items()}),
    )

"""Typed models for war3map.wtg trigger tree summaries."""

from __future__ import annotations

from dataclasses import dataclass

from .wtg_diagnostics import TriggerParseFailure, UnknownTriggerFunction


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
class TriggerEcaParameter:
    parameter_type: int
    value: str
    nested_function: TriggerEcaFunction | None = None
    begin_function: int = 0
    end_function: int = 0
    have_array_indexer: int = 0
    array_indexer: TriggerEcaParameter | None = None
    expected_type: str = ""
    source_offset: int = 0


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
    branch: int = 0
    source_offset: int = 0


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
    missing_schema_functions: tuple[UnknownTriggerFunction, ...] = ()
    parse_failures: tuple[TriggerParseFailure, ...] = ()

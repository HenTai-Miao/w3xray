"""Typed TriggerData.txt and TriggerStrings.txt schema parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import csv
from io import StringIO

from .trigger_strings import build_display_strings, parse_trigger_string_sections


class TriggerFunctionKind(StrEnum):
    EVENT = "event"
    CONDITION = "condition"
    ACTION = "action"
    CALL = "call"


@dataclass(frozen=True, slots=True)
class TriggerFunctionSchema:
    kind: TriggerFunctionKind
    name: str
    category: str
    return_type: str | None
    parameter_types: tuple[str, ...]
    display_name: str
    template: str | None


@dataclass(frozen=True, slots=True)
class TriggerSchema:
    functions: Mapping[tuple[TriggerFunctionKind, str], TriggerFunctionSchema]
    has_trigger_strings: bool = False

    def get(self, kind: TriggerFunctionKind, name: str) -> TriggerFunctionSchema | None:
        return self.functions.get((kind, name.lower()))

    def require(self, kind: TriggerFunctionKind, name: str) -> TriggerFunctionSchema:
        schema = self.get(kind, name)
        if schema is None:
            raise KeyError(f"missing trigger schema for {kind.value}:{name}")
        return schema


_DATA_SECTIONS = (
    (TriggerFunctionKind.EVENT, "TriggerEvents", "TriggerEventStrings"),
    (TriggerFunctionKind.CONDITION, "TriggerConditions", "TriggerConditionStrings"),
    (TriggerFunctionKind.ACTION, "TriggerActions", "TriggerActionStrings"),
    (TriggerFunctionKind.CALL, "TriggerCalls", "TriggerCallStrings"),
)


def parse_trigger_schema(trigger_data: str, trigger_strings: str) -> TriggerSchema:
    """Parse real-format TriggerData and TriggerStrings into typed schemas."""
    data_sections = _parse_sections(trigger_data)
    string_sections = parse_trigger_string_sections(trigger_strings)
    functions: dict[tuple[TriggerFunctionKind, str], TriggerFunctionSchema] = {}
    has_trigger_strings = False
    for kind, data_name, strings_name in _DATA_SECTIONS:
        entries = data_sections.get(data_name, {})
        localized = string_sections.get(strings_name, {})
        has_trigger_strings = has_trigger_strings or bool(localized)
        for name, value in entries.items():
            if name.startswith("_"):
                continue
            return_type, parameter_types = _parse_signature(kind, value)
            display_name, template = build_display_strings(localized.get(name, ()))
            functions[(kind, name.lower())] = TriggerFunctionSchema(
                kind=kind,
                name=name,
                category=entries.get(f"_{name}_Category", ""),
                return_type=return_type,
                parameter_types=parameter_types,
                display_name=display_name or name,
                template=template,
            )
    return TriggerSchema(functions=functions, has_trigger_strings=has_trigger_strings)


def _parse_sections(text: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("//", ";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            sections.setdefault(current, {})
            continue
        if "=" not in line or not current:
            continue
        key, value = line.split("=", 1)
        sections.setdefault(current, {})[key.strip()] = value.strip()
    return sections


def _parse_signature(
    kind: TriggerFunctionKind,
    value: str,
) -> tuple[str | None, tuple[str, ...]]:
    parts = tuple(
        field.strip()
        for field in next(csv.reader(StringIO(value), skipinitialspace=False))
        if field.strip()
    )
    if kind is TriggerFunctionKind.CALL:
        if len(parts) < 3:
            return None, ()
        return parts[2], parts[3:]
    if len(parts) < 2:
        return None, ()
    return None, parts[1:]

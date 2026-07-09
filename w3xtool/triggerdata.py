"""Trigger schema loading, legacy compatibility, and WTG semantic rendering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Protocol, TYPE_CHECKING

from .casc_source import CascUnsupportedError
from .trigger_schema import TriggerFunctionKind, TriggerFunctionSchema, TriggerSchema, parse_trigger_schema
from .war3_encoding import decode_warcraft_string
from .wts import resolve as resolve_wts

if TYPE_CHECKING:
    from .wtg_eca import TriggerEcaFunction, TriggerEcaParameter

_POSITION_RE = re.compile(r"%(\d+)")
_BRACE_RE = re.compile(r"\{([^{}]+)\}")
_TRIGGER_DATA_NAMES = ("UI/TriggerData.txt", "ui/TriggerData.txt", "TriggerData.txt")
_TRIGGER_STRING_NAMES = ("UI/TriggerStrings.txt", "ui/TriggerStrings.txt", "TriggerStrings.txt")


class TriggerDataSource(Protocol):
    """File source that can expose Warcraft III UI/TriggerData.txt."""

    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...


TriggerDataTable = TriggerSchema


@dataclass(frozen=True, slots=True)
class _LegacyTemplate:
    function_name: str
    template: str
    arg_names: tuple[str, ...]
    display_name: str = ""


def parse_trigger_data(text: str) -> TriggerDataTable:
    """Parse real TriggerData signatures or the legacy template-shaped test format."""
    if _looks_like_real_trigger_schema(text):
        return parse_trigger_schema(text, "")
    return _parse_legacy_trigger_data(text)


def load_trigger_schema_from_source(source: TriggerDataSource | None) -> TriggerSchema | None:
    """Load TriggerData/TriggerStrings from an exported or CASC-backed source."""
    if source is None:
        return None
    try:
        data = _read_first(source, _TRIGGER_DATA_NAMES)
        strings = _read_first(source, _TRIGGER_STRING_NAMES)
    except (FileNotFoundError, OSError, ValueError, CascUnsupportedError):
        return None
    if data is None:
        return None
    return parse_trigger_schema(_decode(data), _decode(strings or b""))


def load_trigger_data_from_source(source: TriggerDataSource | None) -> TriggerDataTable | None:
    """Backward-compatible alias for loading trigger schemas from a source."""
    return load_trigger_schema_from_source(source)


def render_eca_semantic(
    function: TriggerEcaFunction,
    schema: TriggerSchema | None,
    *,
    wts: Mapping[int, str] | None = None,
    object_names: Mapping[str, str] | None = None,
) -> str:
    """Render one WTG ECA function as a World Editor-like sentence."""
    values = tuple(
        _parameter_text(param, schema, wts=wts, object_names=object_names)
        for param in function.parameters
    )
    if schema is None:
        return _fallback(function.name, values)
    function_schema = _lookup_schema(schema, function)
    if function_schema is None or function_schema.template is None:
        return _fallback(function.name, values)
    return _fill_template(function_schema.template, values)


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


def _parse_legacy_trigger_data(text: str) -> TriggerSchema:
    sections = _parse_sections(text)
    functions: dict[tuple[TriggerFunctionKind, str], TriggerFunctionSchema] = {}
    for section, values in sections.items():
        direct = _direct_template(section, values)
        if direct is not None:
            _store_legacy(functions, direct)
        for item in _flat_templates(values):
            _store_legacy(functions, item)
    return TriggerSchema(functions=functions)


def _store_legacy(
    functions: dict[tuple[TriggerFunctionKind, str], TriggerFunctionSchema],
    template: _LegacyTemplate,
) -> None:
    positional_template = _legacy_template_to_positional(template.template, template.arg_names)
    for kind in TriggerFunctionKind:
        functions[(kind, template.function_name.lower())] = TriggerFunctionSchema(
            kind=kind,
            name=template.function_name,
            category="",
            return_type=None,
            parameter_types=(),
            display_name=template.display_name or template.function_name,
            template=positional_template,
        )


def _direct_template(section: str, values: dict[str, str]) -> _LegacyTemplate | None:
    template = _first(values, ("Template", "Display", "Text", "Name"))
    if not section or template is None:
        return None
    arg_names = _split_args(_first(values, ("Args", "ArgNames", "Arguments")) or "")
    display_name = _first(values, ("DisplayName", "Name")) or ""
    return _LegacyTemplate(section, template, arg_names, display_name)


def _flat_templates(values: dict[str, str]) -> tuple[_LegacyTemplate, ...]:
    result: list[_LegacyTemplate] = []
    for key, value in values.items():
        if _is_flat_metadata_key(key, values):
            continue
        arg_names = _split_args(
            values.get(f"{key}Args", "")
            or values.get(f"{key}ArgNames", "")
            or values.get(f"{key}Arguments", "")
        )
        display_name = values.get(f"{key}Name", "")
        result.append(_LegacyTemplate(key, value, arg_names, display_name))
    return tuple(result)


def _is_flat_metadata_key(key: str, values: dict[str, str]) -> bool:
    if key in ("Name", "Hint", "Category"):
        return True
    for suffix in ("Args", "ArgNames", "Arguments", "Name", "Hint", "Category"):
        if key.endswith(suffix) and key[: -len(suffix)] in values:
            return True
    return False


def _parameter_text(
    parameter: TriggerEcaParameter,
    schema: TriggerSchema | None,
    *,
    wts: Mapping[int, str] | None,
    object_names: Mapping[str, str] | None,
) -> str:
    if parameter.nested_function is not None:
        return render_eca_semantic(parameter.nested_function, schema, wts=wts, object_names=object_names)
    value = str(resolve_wts(parameter.value, wts or {}))
    if object_names is None:
        return value
    return object_names.get(value, value)


def _fill_template(template: str, values: tuple[str, ...]) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1)) - 1
        if 0 <= index < len(values):
            return values[index]
        return match.group(0)

    return _POSITION_RE.sub(replace, template)


def _fallback(function_name: str, values: tuple[str, ...]) -> str:
    if not values:
        return function_name
    return f"{function_name}({', '.join(values)})"


def _kind_from_function_type(value: int) -> TriggerFunctionKind:
    match value:
        case 0:
            return TriggerFunctionKind.EVENT
        case 1:
            return TriggerFunctionKind.CONDITION
        case 2:
            return TriggerFunctionKind.ACTION
        case _:
            return TriggerFunctionKind.CALL


def _lookup_schema(
    schema: TriggerSchema,
    function: TriggerEcaFunction,
) -> TriggerFunctionSchema | None:
    by_kind = schema.get(_kind_from_function_type(function.function_type), function.name)
    if by_kind is not None:
        return by_kind
    for kind in TriggerFunctionKind:
        fallback = schema.get(kind, function.name)
        if fallback is not None:
            return fallback
    return None


def _looks_like_real_trigger_schema(text: str) -> bool:
    return any(section in text for section in ("[TriggerEvents]", "[TriggerConditions]", "[TriggerActions]", "[TriggerCalls]"))


def _read_first(source: TriggerDataSource, names: tuple[str, ...]) -> bytes | None:
    for name in names:
        if source.has_file(name):
            return source.read_file(name)
    return None


def _decode(data: bytes) -> str:
    return decode_warcraft_string(data, allow_latin1=True)


def _first(values: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = values.get(key)
        if value:
            return value
    return None


def _split_args(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _legacy_template_to_positional(template: str, arg_names: tuple[str, ...]) -> str:
    converted = template
    for index, name in enumerate(arg_names, start=1):
        converted = converted.replace(f"{{{name}}}", f"%{index}")
    if arg_names:
        return converted
    placeholder_index = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal placeholder_index
        placeholder_index += 1
        return f"%{placeholder_index}"

    return _BRACE_RE.sub(replace, converted)

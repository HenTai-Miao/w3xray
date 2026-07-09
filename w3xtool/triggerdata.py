"""TriggerData.txt parsing and WTG ECA semantic rendering."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol, TYPE_CHECKING

from .war3_encoding import decode_warcraft_string

if TYPE_CHECKING:
    from .wtg_eca import TriggerEcaFunction, TriggerEcaParameter

_BRACE_RE = re.compile(r"\{([^{}]+)\}")


class TriggerDataSource(Protocol):
    """File source that can expose Warcraft III UI/TriggerData.txt."""

    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class TriggerFunctionTemplate:
    function_name: str
    template: str
    arg_names: tuple[str, ...]
    display_name: str = ""


@dataclass(frozen=True, slots=True)
class TriggerDataTable:
    functions: dict[str, TriggerFunctionTemplate]

    def get(self, function_name: str) -> TriggerFunctionTemplate | None:
        return self.functions.get(function_name.lower())


def parse_trigger_data(text: str) -> TriggerDataTable:
    """Parse the INI-like TriggerData.txt formats used by World Editor."""
    sections = _parse_sections(text)
    functions: dict[str, TriggerFunctionTemplate] = {}
    for section, values in sections.items():
        direct = _direct_template(section, values)
        if direct is not None:
            functions[direct.function_name.lower()] = direct
        for item in _flat_templates(values):
            functions[item.function_name.lower()] = item
    return TriggerDataTable(functions)


def load_trigger_data_from_source(source: TriggerDataSource | None) -> TriggerDataTable | None:
    """Load TriggerData.txt from an exported or CASC-backed game-data source."""
    if source is None:
        return None
    for name in ("UI/TriggerData.txt", "ui/TriggerData.txt", "TriggerData.txt"):
        if source.has_file(name):
            raw = source.read_file(name)
            return parse_trigger_data(decode_warcraft_string(raw, allow_latin1=True))
    return None


def render_eca_semantic(function: TriggerEcaFunction, table: TriggerDataTable | None) -> str:
    """Render one WTG ECA function as a World Editor-like sentence."""
    values = tuple(_parameter_text(param, table) for param in function.parameters)
    if table is None:
        return _fallback(function.name, values)
    template = table.get(function.name)
    if template is None:
        return _fallback(function.name, values)
    return _fill_template(template.template, template.arg_names, values)


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
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        sections.setdefault(current, {})[key.strip()] = value.strip()
    return sections


def _direct_template(section: str, values: dict[str, str]) -> TriggerFunctionTemplate | None:
    template = _first(values, ("Template", "Display", "Text", "Name"))
    if not section or template is None:
        return None
    arg_names = _split_args(_first(values, ("Args", "ArgNames", "Arguments")) or "")
    display_name = _first(values, ("DisplayName", "Name")) or ""
    return TriggerFunctionTemplate(section, template, arg_names, display_name)


def _flat_templates(values: dict[str, str]) -> tuple[TriggerFunctionTemplate, ...]:
    result: list[TriggerFunctionTemplate] = []
    for key, value in values.items():
        if _is_flat_metadata_key(key, values):
            continue
        arg_names = _split_args(
            values.get(f"{key}Args", "")
            or values.get(f"{key}ArgNames", "")
            or values.get(f"{key}Arguments", "")
        )
        display_name = values.get(f"{key}Name", "")
        result.append(TriggerFunctionTemplate(key, value, arg_names, display_name))
    return tuple(result)


def _is_flat_metadata_key(key: str, values: dict[str, str]) -> bool:
    if key in ("Name", "Hint", "Category"):
        return True
    for suffix in ("Args", "ArgNames", "Arguments", "Name", "Hint", "Category"):
        if key.endswith(suffix) and key[: -len(suffix)] in values:
            return True
    return False


def _parameter_text(parameter: TriggerEcaParameter, table: TriggerDataTable | None) -> str:
    if parameter.nested_function is not None:
        return render_eca_semantic(parameter.nested_function, table)
    return parameter.value


def _fill_template(template: str, arg_names: tuple[str, ...], values: tuple[str, ...]) -> str:
    by_name = {name: values[index] for index, name in enumerate(arg_names) if index < len(values)}
    text = _BRACE_RE.sub(lambda match: by_name.get(match.group(1), match.group(0)), template)
    for index, value in enumerate(values, start=1):
        text = text.replace(f"%{index}", value)
    if text == template and values:
        return f"{template}({', '.join(values)})"
    return text


def _fallback(function_name: str, values: tuple[str, ...]) -> str:
    if not values:
        return function_name
    return f"{function_name}({', '.join(values)})"


def _first(values: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = values.get(key)
        if value:
            return value
    return None


def _split_args(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())

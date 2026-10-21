"""Assign categories to sections from trusted and anonymous text tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, assert_never

from .object_text_names import TextObjectSourceKind, normalized_name
from .textobj import classify

type TextObjectSection = tuple[str, Mapping[str, str]]

_FIXED_NAMED_FAMILIES: Final[tuple[tuple[str, str], ...]] = (
    ("unit", "单位"),
    ("item", "物品"),
    ("upgrade", "科技"),
)
_BUFF_FIELD_KEYS: Final = frozenset(
    {"bufftip", "buffubertip", "effectart", "effectattach", "spelleffect"}
)


def categories_for_text_sections(
    source_name: str,
    source_kind: TextObjectSourceKind,
    sections: Sequence[TextObjectSection],
) -> tuple[str, ...]:
    """Classify named families per section and anonymous data as one block."""
    fallback = classify(
        (obj_id for obj_id, _fields in sections),
        (field_name for _obj_id, fields in sections for field_name in fields),
    )
    match source_kind:
        case TextObjectSourceKind.ANONYMOUS:
            return (fallback,) * len(sections)
        case TextObjectSourceKind.FUNC | TextObjectSourceKind.STRINGS:
            return _named_categories(source_name, sections, fallback)
        case unreachable:
            assert_never(unreachable)


def _named_categories(
    source_name: str,
    sections: Sequence[TextObjectSection],
    fallback: str,
) -> tuple[str, ...]:
    normalized = normalized_name(source_name)
    for family, category in _FIXED_NAMED_FAMILIES:
        if normalized.endswith((f"{family}func.txt", f"{family}strings.txt")):
            return (category,) * len(sections)
    if normalized.endswith(("abilityfunc.txt", "abilitystrings.txt")):
        return tuple(
            "增益" if _is_buff_section(obj_id, fields) else "技能"
            for obj_id, fields in sections
        )
    return (fallback,) * len(sections)


def _is_buff_section(obj_id: str, fields: Mapping[str, str]) -> bool:
    return obj_id[:1].casefold() in {"b", "x"} or bool(
        {key.casefold() for key in fields} & _BUFF_FIELD_KEYS
    )

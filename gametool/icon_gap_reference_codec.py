"""Strict boundary parser for unresolved-icon reference identity JSON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, override

from .json_evidence import JsonNode, parse_json_evidence

_REFERENCE_KEYS: Final = frozenset(
    (
        "category",
        "rawcode",
        "base",
        "name",
        "field",
        "label",
        "type",
        "source",
        "wts",
        "map",
        "scope",
    )
)


@dataclass(frozen=True, slots=True)
class IconGapReferenceIdentity:
    """One exact object-field reference carried by a normalized gap row."""

    category: str
    rawcode: str
    base: str
    name: str
    field: str
    label: str
    type: str
    source: str
    wts: str
    map: str
    scope: str


@dataclass(frozen=True, slots=True)
class IconGapReferenceFormatError(ValueError):
    """Malformed or ambiguous unresolved-icon reference JSON."""

    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


def parse_icon_gap_references(text: str) -> tuple[IconGapReferenceIdentity, ...]:
    """Parse an exact nonempty reference set and reject duplicate identities."""
    try:
        nodes, root = parse_json_evidence(text)
    except ValueError as exc:
        raise IconGapReferenceFormatError("malformed icon reference JSON") from exc
    value = nodes[root]
    if value.kind != "array" or not value.elements:
        raise IconGapReferenceFormatError("icon reference set is empty")
    references = tuple(_parse_reference(nodes, item) for item in value.elements)
    if len(set(references)) != len(references):
        raise IconGapReferenceFormatError("duplicate icon reference identity")
    return references


def _parse_reference(
    nodes: tuple[JsonNode, ...], index: int
) -> IconGapReferenceIdentity:
    node = nodes[index]
    if (
        node.kind != "object"
        or len(node.members) != len(_REFERENCE_KEYS)
        or {member.key for member in node.members} != _REFERENCE_KEYS
    ):
        raise IconGapReferenceFormatError("unexpected icon reference keys")
    value = {member.key: nodes[member.node] for member in node.members}
    reference = IconGapReferenceIdentity(
        _text(value["category"]),
        _text(value["rawcode"]),
        _text(value["base"]),
        _text(value["name"]),
        _text(value["field"]),
        _text(value["label"]),
        _text(value["type"]),
        _text(value["source"]),
        _text(value["wts"]),
        _text(value["map"]),
        _text(value["scope"]),
    )
    if not reference.category or not reference.rawcode:
        raise IconGapReferenceFormatError("icon reference identity is empty")
    return reference


def _text(node: JsonNode) -> str:
    if node.kind != "string" or not isinstance(node.value, str):
        raise IconGapReferenceFormatError("icon reference value is not text")
    return node.value

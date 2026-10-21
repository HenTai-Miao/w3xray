"""Shared immutable models for knowledge-pack requirement coverage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .external_listfile import ExternalListfileReport

if TYPE_CHECKING:
    from .knowledge_results import KnowledgeWriteReport


@dataclass(frozen=True, slots=True)
class RequirementCoverage:
    request: str
    status: str
    primary: tuple[str, ...]
    secondary: tuple[str, ...]
    note: str


@dataclass(frozen=True, slots=True)
class ExtractionCapabilities:
    game_data_kind: str = "missing"
    has_trigger_schema: bool = False
    has_trigger_strings: bool = False
    external_listfile: ExternalListfileReport | None = None
    archive_diagnosis_kind: str = ""
    write_report: KnowledgeWriteReport | None = None
    game_data_inventory_view: str = ""

"""UI/TRIGSTR text inventory for map investigation exports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .api import MapData
from .presentation_safety import tsv_cell as _tsv
from .script_sources import analysis_script_texts
from .wts import map_wts_table

_TRIGSTR_RE: Final = re.compile(r"\bTRIGSTR_(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class UiTextString:
    trigstr: str
    text: str


@dataclass(frozen=True, slots=True)
class UiTextReference:
    source: str
    line: int
    trigstr: str
    text: str
    context: str


@dataclass(frozen=True, slots=True)
class UiTextReport:
    strings: tuple[UiTextString, ...]
    references: tuple[UiTextReference, ...]

    @property
    def string_count(self) -> int:
        return len(self.strings)

    @property
    def reference_count(self) -> int:
        return len(self.references)

    @property
    def unresolved_count(self) -> int:
        return sum(1 for ref in self.references if not ref.text)


def build_ui_text_report(md: MapData) -> UiTextReport:
    """Build a TRIGSTR table and reference report from parsed map scripts."""
    table = _string_table(md)
    strings = tuple(
        UiTextString(trigstr=_trigstr_id(sid), text=text)
        for sid, text in sorted(table.items())
    )
    references = tuple(_iter_references(md, table))
    return UiTextReport(strings=strings, references=references)


def format_ui_text_strings_tsv(report: UiTextReport) -> str:
    """Format the WTS string table as TSV."""
    rows = ["TRIGSTR\t文本"]
    rows.extend(f"{_tsv(item.trigstr)}\t{_tsv(item.text)}" for item in report.strings)
    return "\n".join(rows) + "\n"


def format_ui_text_references_tsv(report: UiTextReport) -> str:
    """Format TRIGSTR references as TSV."""
    rows = ["来源\t行号\tTRIGSTR\t文本\t上下文"]
    for ref in report.references:
        rows.append("\t".join((
            _tsv(ref.source),
            str(ref.line),
            _tsv(ref.trigstr),
            _tsv(ref.text),
            _tsv(ref.context),
        )))
    return "\n".join(rows) + "\n"


def _string_table(md: MapData) -> dict[int, str]:
    return map_wts_table(md)


def _iter_references(md: MapData, table: dict[int, str]):
    for source, text in analysis_script_texts(md):
        for line_no, line in enumerate(text.splitlines(), start=1):
            seen: set[str] = set()
            for match in _TRIGSTR_RE.finditer(line):
                trigstr = _trigstr_id(int(match.group(1)))
                if trigstr in seen:
                    continue
                seen.add(trigstr)
                yield UiTextReference(
                    source=source,
                    line=line_no,
                    trigstr=trigstr,
                    text=table.get(int(match.group(1)), ""),
                    context=line.strip()[:160],
                )


def _trigstr_id(sid: int) -> str:
    return f"TRIGSTR_{sid:03d}"

"""Script-level clues for map save/load and ID investigation."""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
import re
from typing import Final

from .api import MapData
from .save_api_catalog import object_api_category, save_api_info
from .save_call_context import extract_call_args, structured_context, unescape_arg
from .script_scan import _codes_in
from .script_sources import analysis_script_texts
from .script_tokens import script_code_text

_STRING_RE: Final = re.compile(r'"((?:[^"\\]|\\.)*)"')
_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

@dataclass(frozen=True, slots=True)
class SaveClue:
    source: str
    line: int
    mechanism: str
    operation: str
    detail: str
    file_path: str = ""
    section: str = ""
    key: str = ""
    sync_prefix: str = ""
    object_codes: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        codes = f" · 对象码 {','.join(self.object_codes)}" if self.object_codes else ""
        context = "".join(f" · {label} {value}" for label, value in _context_parts(self))
        detail = f" · {self.detail}" if self.detail else ""
        return f"{self.source}:{self.line} {self.mechanism}/{self.operation}{context}{detail}{codes}"


@dataclass(frozen=True, slots=True)
class SaveReport:
    rows: tuple[SaveClue, ...]

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def object_codes(self) -> tuple[str, ...]:
        return tuple(sorted({code for row in self.rows for code in row.object_codes}))

    @property
    def local_files(self) -> tuple[str, ...]:
        return tuple(sorted({row.file_path for row in self.rows if row.file_path}))

    @property
    def sections(self) -> tuple[str, ...]:
        return tuple(sorted({row.section for row in self.rows if row.section}))

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted({row.key for row in self.rows if row.key}))

    @property
    def sync_prefixes(self) -> tuple[str, ...]:
        return tuple(sorted({row.sync_prefix for row in self.rows if row.sync_prefix}))

    @property
    def mechanism_counts(self) -> dict[str, int]:
        return dict(Counter(row.mechanism for row in self.rows))


def build_save_report(md: MapData) -> SaveReport:
    rows: list[SaveClue] = []
    for source, text in analysis_script_texts(md):
        rows.extend(_scan_script(source, text))
    return SaveReport(tuple(rows))


def format_save_report_tsv(report: SaveReport) -> str:
    rows = ["来源\t行号\t机制\t操作\t详情\t存档文件\t区段/父键\t键/子键\t同步前缀\t对象码\t摘要"]
    for clue in report.rows:
        rows.append("\t".join((
            _tsv(clue.source),
            str(clue.line),
            _tsv(clue.mechanism),
            _tsv(clue.operation),
            _tsv(clue.detail),
            _tsv(clue.file_path),
            _tsv(clue.section),
            _tsv(clue.key),
            _tsv(clue.sync_prefix),
            _tsv(",".join(clue.object_codes)),
            _tsv(clue.summary),
        )))
    return "\n".join(rows) + "\n"


def _scan_script(source: str, text: str) -> list[SaveClue]:
    rows: list[SaveClue] = []
    line_starts = _line_starts(text)
    code_text = script_code_text(text)
    for match in _CALL_RE.finditer(code_text):
        name = match.group(1)
        args = extract_call_args(text, match.end())
        line_no = bisect_right(line_starts, match.start())
        api_info = save_api_info(name)
        if api_info is not None:
            context = structured_context(name, args)
            detail = _call_detail(text, match.start(), args)
            if api_info.mechanism in {"Hashtable", "PlatformSave"}:
                detail = f"{name} · {detail}" if detail else name
            rows.append(SaveClue(
                source=source,
                line=line_no,
                mechanism=api_info.mechanism,
                operation=api_info.operation,
                detail=detail,
                file_path=context.file_path,
                section=context.section,
                key=context.key,
                sync_prefix=context.sync_prefix,
            ))
        object_category = object_api_category(name)
        if object_category is None:
            continue
        codes = tuple(sorted(set(_codes_in(" ".join(args)))))
        if not codes:
            continue
        rows.append(SaveClue(
            source=source,
            line=line_no,
            mechanism="ObjectID",
            operation=object_category,
            detail=_call_detail(text, match.start(), args),
            object_codes=codes,
        ))
    return rows


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(match.end() for match in re.finditer("\n", text))
    return starts


def _call_detail(text: str, start: int, args: tuple[str, ...]) -> str:
    arg_text = ", ".join(args)
    strings = [unescape_arg(match.group(1)) for match in _STRING_RE.finditer(arg_text)]
    if strings:
        return " / ".join(strings[:4])
    return _line_fragment(text, start)[:120]


def _line_fragment(text: str, start: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end < 0:
        line_end = len(text)
    return text[line_start:line_end].strip()


def _context_parts(clue: SaveClue) -> tuple[tuple[str, str], ...]:
    parts: list[tuple[str, str]] = []
    if clue.file_path:
        parts.append(("文件", clue.file_path))
    if clue.section:
        parts.append(("区段", clue.section))
    if clue.key:
        parts.append(("键", clue.key))
    if clue.sync_prefix:
        parts.append(("同步", clue.sync_prefix))
    return tuple(parts)


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")

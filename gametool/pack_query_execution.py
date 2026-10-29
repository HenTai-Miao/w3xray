"""Shared query execution for CLI, GUI, and structured campaign results.

The execution interface returns data and diagnostics without redirecting any
process-global stream. A query reads each source table once, validates its
whole content, and keeps the resulting rows local to that execution.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .script_call_query_models import (
    ScriptCallQueryDiagnostic,
    ScriptCallQueryRecord,
    ScriptCallQueryResult,
)
from .pack_query_spatial import NearEntry, SpatialQueryResult
from .pack_query_regions import NearRegion
from .pack_query_options import EMPTY_QUERY_COMMANDS, query_limit_error
from .pack_query_diff import ComparisonDiagnostic, DiffQueryResult
from .object_export_coverage import ObjectCoverageInput
from .pack_query_script_coverage import (
    SCRIPT_QUERY_COMMANDS,
    ScriptCoverage,
    combine_script_coverage,
)

if TYPE_CHECKING:
    from .pack_query_options import PackQueryCliOptions


class QueryBackend(Protocol):
    """Query functions and session state supplied by the public query API."""

    _TABLE_READ_LOCK: AbstractContextManager[object]
    _QUERY_ROWS: dict[tuple[str, str], list[list[str]]] | None
    _QUERY_SCRIPTS: dict[str, str | None] | None
    _QUERY_SCRIPT_SOURCES: dict[str, tuple[tuple[str, str], ...]] | None
    _QUERY_SCRIPT_COVERAGE: dict[str, ScriptCoverage] | None
    _QUERY_FILES: set[tuple[str, str]] | None
    _QUERY_OBJECT_WARNINGS: dict[str, list[str]] | None
    _QUERY_OBJECT_COVERAGE: dict[str, ObjectCoverageInput] | None
    _LOCKED_FILES: set[tuple[str, str]]
    _QUERIES: dict[str, Callable[[Path, str, int], list[str]]]

    def _load_last_query(self) -> dict[str, str] | None: ...

    def _store_last_query(self, pack: Path, command: str, query: str) -> None: ...

    def _campaign_subpacks(self, pack: Path) -> list[Path]: ...

    def _query_diff(
        self, pack: Path, query: str, limit: int, pack_b: str = ""
    ) -> list[str]: ...

    def _query_diff_result(
        self, pack: Path, query: str, limit: int, pack_b: str = ""
    ) -> DiffQueryResult: ...

    def _query_near_result(
        self, pack: Path, query: str, limit: int
    ) -> SpatialQueryResult: ...

    def _query_cmd_result(
        self, pack: Path, query: str, limit: int
    ) -> TextQueryResult: ...

    def _query_calls_result(
        self, pack: Path, query: str, limit: int
    ) -> ScriptCallQueryResult: ...

    def _query_script_result(
        self, pack: Path, command: str, query: str, limit: int
    ) -> TextQueryResult: ...


@dataclass(frozen=True, slots=True)
class TextQueryResult:
    lines: tuple[str, ...]
    has_matches: bool
    script_coverage: ScriptCoverage | None = None


@dataclass(frozen=True, slots=True)
class QuerySection:
    section: str
    pack: str
    lines: tuple[str, ...]
    entries: tuple[NearEntry, ...] = ()
    regions: tuple[NearRegion, ...] = ()
    regions_total: int = 0
    spatial_diagnostics: tuple[str, ...] = ()
    input_error: bool = False
    has_matches: bool | None = None
    script_coverage: ScriptCoverage | None = None
    calls: tuple[ScriptCallQueryRecord, ...] = ()
    calls_total: int = 0
    calls_omitted: int = 0
    call_diagnostics: tuple[ScriptCallQueryDiagnostic, ...] = ()
    source_stable: bool | None = None
    calls_report: ScriptCallQueryResult | None = field(
        default=None, repr=False, compare=False
    )


@dataclass(frozen=True, slots=True)
class PackQueryResult:
    pack: str
    command: str
    query: str
    sections: tuple[QuerySection, ...]
    exit_code: int
    campaign: bool = False
    diagnostics: tuple[str, ...] = ()
    checked_packs: tuple[str, ...] = ()
    comparison_complete: bool | None = None
    comparison_diagnostics: tuple[ComparisonDiagnostic, ...] = ()
    has_changes: bool | None = None

    @property
    def script_coverage(self) -> ScriptCoverage | None:
        coverages = tuple(
            section.script_coverage
            for section in self.sections
            if section.script_coverage is not None
        )
        return combine_script_coverage(coverages) if coverages else None

    @property
    def extra_diagnostics(self) -> tuple[str, ...]:
        """Keep typed diagnostics while displaying an identical warning only once."""
        if not any(note.startswith("[⚠") for note in self.diagnostics):
            return self.diagnostics
        rendered = {line for section in self.sections for line in section.lines}
        return tuple(note for note in self.diagnostics if note not in rendered)

    def render(self, *, as_json: bool = False) -> str:
        """Render one complete JSON document or all text sections."""
        lines: list[str] = []
        for section in self.sections:
            if self.campaign:
                lines.append(f"== {section.section} ==")
            lines.extend(section.lines)
        if not as_json:
            return "\n".join(lines)
        payload: dict[str, object] = {
            "section": "战役" if self.campaign else self.sections[0].section,
            "lines": lines,
            "pack": self.pack,
            "command": self.command,
            "query": self.query,
            "exit_code": self.exit_code,
            "input_error": any(section.input_error for section in self.sections),
            "warnings": [note for note in self.diagnostics if note.startswith("[⚠")],
        }
        if any(section.has_matches is not None for section in self.sections):
            payload["has_matches"] = any(
                _section_has_result(self.command, section) for section in self.sections
            )
        coverage = self.script_coverage
        if coverage is not None:
            payload["script_coverage"] = asdict(coverage)
            payload["checked_packs"] = list(self.checked_packs)
        if self.command == "calls":
            payload.update(_call_payload(self.sections))
            payload["checked_packs"] = list(self.checked_packs)
        if self.command == "diff":
            payload.update(
                comparison_complete=self.comparison_complete,
                comparison_diagnostics=[
                    asdict(note) for note in self.comparison_diagnostics
                ],
                has_changes=self.has_changes,
                input_error=any(section.input_error for section in self.sections),
                checked_packs=list(self.checked_packs),
            )
        if self.command == "near":
            payload["entries"] = [
                {**entry, **({"section": section.section} if self.campaign else {})}
                for section in self.sections
                for entry in section.entries
            ]
            payload["regions"] = [
                {
                    **region,
                    **(
                        {"section": section.section, "pack": section.pack}
                        if self.campaign
                        else {}
                    ),
                }
                for section in self.sections
                for region in section.regions
            ]
            payload["regions_total"] = sum(
                max(section.regions_total, len(section.regions))
                for section in self.sections
            )
            payload["regions_omitted"] = sum(
                max(section.regions_total - len(section.regions), 0)
                for section in self.sections
            )
            payload["spatial_diagnostics"] = [
                {"section": section.section, "pack": section.pack, "message": note}
                for section in self.sections
                for note in section.spatial_diagnostics
            ]
            payload["has_matches"] = any(
                section.entries or section.regions for section in self.sections
            )
            payload["input_error"] = any(
                section.input_error for section in self.sections
            )
            payload["checked_packs"] = list(self.checked_packs)
        if self.campaign:
            payload["sections"] = [
                {
                    "section": section.section,
                    "pack": section.pack,
                    "lines": list(section.lines),
                    **(_call_payload((section,)) if self.command == "calls" else {}),
                    **(
                        {
                            "has_matches": (
                                section.has_matches
                                if self.command == "calls"
                                else _section_has_result(self.command, section)
                            ),
                            "input_error": section.input_error,
                        }
                        if section.has_matches is not None
                        else {}
                    ),
                    **(
                        {"script_coverage": asdict(section.script_coverage)}
                        if section.script_coverage is not None
                        else {}
                    ),
                    **(
                        {
                            "entries": list(section.entries),
                            "regions": list(section.regions),
                            "regions_total": max(
                                section.regions_total, len(section.regions)
                            ),
                            "regions_omitted": max(
                                section.regions_total - len(section.regions), 0
                            ),
                            "spatial_diagnostics": list(section.spatial_diagnostics),
                            "has_matches": _has_result(
                                "near", section.lines, section.entries, section.regions
                            ),
                            "input_error": section.input_error,
                        }
                        if self.command == "near"
                        else {}
                    ),
                }
                for section in self.sections
            ]
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)


def execute_query(
    options: PackQueryCliOptions, queries: QueryBackend
) -> PackQueryResult:
    """Run a full query without printing or touching any GUI objects."""
    started = time.perf_counter()
    if note := query_limit_error(options.limit):
        result = _message(options, note, 2)
        result = replace(
            result,
            sections=tuple(
                replace(section, input_error=True) for section in result.sections
            ),
        )
        return _timed_result(result, started)
    with queries._TABLE_READ_LOCK:
        previous = queries._QUERY_ROWS
        previous_scripts = queries._QUERY_SCRIPTS
        previous_sources = queries._QUERY_SCRIPT_SOURCES
        previous_coverage = queries._QUERY_SCRIPT_COVERAGE
        previous_files = queries._QUERY_FILES
        previous_objects = queries._QUERY_OBJECT_WARNINGS
        previous_object_coverage = queries._QUERY_OBJECT_COVERAGE
        queries._QUERY_ROWS = {}
        queries._QUERY_SCRIPTS = {}
        queries._QUERY_SCRIPT_SOURCES = {}
        queries._QUERY_SCRIPT_COVERAGE = {}
        queries._QUERY_FILES = set()
        queries._QUERY_OBJECT_WARNINGS = {}
        queries._QUERY_OBJECT_COVERAGE = {}
        try:
            result = _collect_query(options, queries, remember=False)
        finally:
            touched = queries._QUERY_FILES or set()
            object_warnings = queries._QUERY_OBJECT_WARNINGS or {}
            source_coverages = queries._QUERY_SCRIPT_COVERAGE or {}
            object_coverages = queries._QUERY_OBJECT_COVERAGE or {}
            queries._QUERY_ROWS = previous
            queries._QUERY_SCRIPTS = previous_scripts
            queries._QUERY_SCRIPT_SOURCES = previous_sources
            queries._QUERY_SCRIPT_COVERAGE = previous_coverage
            queries._QUERY_FILES = previous_files
            queries._QUERY_OBJECT_WARNINGS = previous_objects
            queries._QUERY_OBJECT_COVERAGE = previous_object_coverage
        coverage_changed = False
        for pack, snapshot in object_coverages.items():
            if note := snapshot.verify():
                coverage_changed = True
                object_warnings.setdefault(pack, []).append(f"[⚠ {note}]")
        if coverage_changed:
            result = replace(
                result,
                exit_code=2,
                comparison_complete=(
                    False if result.comparison_complete is not None else None
                ),
            )
        if object_warnings:
            remaining = dict(object_warnings)
            sections = []
            for section in result.sections:
                notes = tuple(dict.fromkeys(remaining.pop(section.pack, ())))
                sections.append(replace(section, lines=(*section.lines, *notes)))
            campaign = (
                result.campaign
                or result.command != "diff"
                and any(
                    Path(pack).parent == Path(result.pack) / "子地图"
                    for pack in remaining
                )
            )
            for pack, notes in remaining.items():
                label = (
                    "容器级"
                    if pack == result.pack
                    else "子地图 " + Path(pack).name
                    if campaign and Path(pack).parent == Path(result.pack) / "子地图"
                    else "诊断来源 " + Path(pack).name
                )
                sections.append(
                    QuerySection(
                        label,
                        pack,
                        tuple(dict.fromkeys(notes)),
                        has_matches=False,
                        script_coverage=source_coverages.get(pack),
                    )
                )
            if campaign:
                sections = [
                    replace(section, section="容器级")
                    if section.pack == result.pack
                    else section
                    for section in sections
                ]
                sections.sort(
                    key=lambda section: (section.pack != result.pack, section.pack)
                )
            result = replace(result, sections=tuple(sections), campaign=campaign)
        diagnostics = (
            *dict.fromkeys(
                note for notes in object_warnings.values() for note in notes
            ),
            *(
                f"[⚠ 数据文件读取失败, 本次结果可能缺失: {rel} — "
                f"检查文件权限/编码或重新导出知识包: {pack}]"
                for pack, rel in sorted(queries._LOCKED_FILES.intersection(touched))
            ),
        )
        result = _revalidate_calls(result)
        if result.exit_code == 0 and options.command not in {"again", "diff"}:
            queries._store_last_query(Path(result.pack), result.command, result.query)
    return _timed_result(
        replace(
            result,
            diagnostics=tuple(
                dict.fromkeys(
                    (
                        *result.diagnostics,
                        *diagnostics,
                        *(
                            note
                            for section in result.sections
                            if section.script_coverage is not None
                            for note in section.script_coverage.diagnostics
                        ),
                    )
                )
            ),
        ),
        started,
    )


def _call_payload(sections: tuple[QuerySection, ...]) -> dict[str, object]:
    return {
        "calls": [
            {**asdict(record), "pack": section.pack, "section": section.section}
            for section in sections
            for record in section.calls
        ],
        "calls_total": sum(section.calls_total for section in sections),
        "calls_omitted": sum(section.calls_omitted for section in sections),
        "call_diagnostics": [
            {**asdict(note), "pack": section.pack, "section": section.section}
            for section in sections
            for note in section.call_diagnostics
        ],
        "source_stable": (
            all(section.source_stable for section in sections)
            if any(section.source_stable is not None for section in sections)
            else None
        ),
        "has_matches": any(section.has_matches is True for section in sections),
    }


def _call_section(section: QuerySection, report: ScriptCallQueryResult) -> QuerySection:
    # Keep replay headers and any independently appended diagnostics on refresh.
    old_lines = section.calls_report.lines if section.calls_report is not None else ()
    extras = tuple(line for line in section.lines if line not in old_lines)
    return replace(
        section,
        lines=(*extras, *report.lines),
        calls=report.calls,
        calls_total=report.total,
        calls_omitted=report.omitted,
        call_diagnostics=report.diagnostics,
        source_stable=report.source_stable,
        input_error=report.input_error,
        has_matches=report.has_matches,
        script_coverage=report.script_coverage,
        calls_report=report,
    )


def _revalidate_calls(result: PackQueryResult) -> PackQueryResult:
    if result.command != "calls":
        return result
    from .pack_query_script_calls import revalidate_script_calls

    sections = tuple(
        _call_section(section, revalidate_script_calls(section.calls_report))
        if section.calls_report is not None
        else section
        for section in result.sections
    )
    return replace(
        result,
        sections=sections,
        exit_code=2
        if any(section.input_error for section in sections)
        else result.exit_code,
    )


def _timed_result(result: PackQueryResult, started: float) -> PackQueryResult:
    elapsed_ms = (time.perf_counter() - started) * 1000
    hint = " — 同包再查走热缓存会快很多" if elapsed_ms > 500 else ""
    return replace(
        result, diagnostics=(*result.diagnostics, f"[耗时 {elapsed_ms:.0f}ms{hint}]")
    )


def _collect_query(
    options: PackQueryCliOptions, queries: QueryBackend, *, remember: bool = True
) -> PackQueryResult:
    if options.command == "again":
        last = queries._load_last_query()
        if (
            last is None
            or last["command"] == "again"
            or last["command"] not in queries._QUERIES
        ):
            return _message(options, "无最近查询记录 (先跑任意一次普通查询)", 0)
        if not Path(last["pack"]).is_dir():
            return _message(options, "最近查询的资料包目录已不存在: " + last["pack"], 2)
        result = _collect_query(
            replace(
                options,
                pack_dir=last["pack"],
                command=last["command"],
                query=last["query"],
                near_kind="",
            ),
            queries,
            remember=False,
        )
        first, *rest = result.sections
        header = f"[重跑] {last['command']} {last['query']} (来自 {last['pack']})"
        return replace(
            result, sections=(replace(first, lines=(header, *first.lines)), *rest)
        )
    pack = Path(options.pack_dir)
    if not pack.is_dir():
        result = _message(options, "资料包目录不存在: " + options.pack_dir, 2)
        if options.command == "calls":
            result = replace(
                result,
                sections=tuple(
                    replace(section, input_error=True) for section in result.sections
                ),
            )
        return result
    if options.command not in queries._QUERIES:
        return _message(options, "未知子命令: " + options.command, 2)
    if not options.query.strip() and options.command not in EMPTY_QUERY_COMMANDS | {
        "near",
        "diff",
    }:
        result = _message(
            options, options.command + " 需要查询词；可输入名称或四码。", 2
        )
        return replace(
            result,
            sections=tuple(
                replace(section, input_error=True) for section in result.sections
            ),
        )
    if options.command == "near" and options.near_kind:
        options = replace(options, query=options.query + " --kind " + options.near_kind)
    if options.command == "diff":
        report = queries._query_diff_result(
            pack, options.query, options.limit, options.pack_dir_b or options.query
        )
        result = _message_lines(
            options,
            report.lines,
            0
            if not report.input_error and (report.complete or report.has_changes)
            else 2,
        )
        return replace(
            result,
            sections=tuple(
                replace(section, input_error=report.input_error)
                for section in result.sections
            ),
            comparison_complete=report.complete,
            comparison_diagnostics=report.diagnostics,
            has_changes=report.has_changes,
            checked_packs=report.checked_packs,
            diagnostics=tuple(note.render() for note in report.diagnostics),
        )
    subs = queries._campaign_subpacks(pack) if options.command != "near" else []
    section = _run_section(
        queries,
        options.command,
        "near" if options.command == "near" else "",
        pack,
        options.query,
        options.limit,
    )
    if options.command == "near" and section.input_error:
        return PackQueryResult(str(pack), options.command, options.query, (section,), 2)
    if options.command == "near":
        subs = queries._campaign_subpacks(pack)
    checked = (
        (str(pack), *(str(sub) for sub in subs))
        if options.command == "near" or options.command in SCRIPT_QUERY_COMMANDS
        else ()
    )
    if subs:
        sections: list[QuerySection] = []
        observed = [section]
        if (
            _section_has_result(options.command, section)
            or options.command == "calls"
            or (options.command == "near" and section.spatial_diagnostics)
            or (
                section.script_coverage is not None
                and section.script_coverage.complete is False
            )
        ):
            sections.append(replace(section, section="容器级"))
        for sub in subs:
            sub_section = _run_section(
                queries,
                options.command,
                "子地图 " + sub.name,
                sub,
                options.query,
                options.limit,
            )
            observed.append(sub_section)
            if (
                _section_has_result(options.command, sub_section)
                or options.command == "calls"
                or (options.command == "near" and sub_section.spatial_diagnostics)
                or (
                    sub_section.script_coverage is not None
                    and sub_section.script_coverage.complete is False
                )
            ):
                sections.append(sub_section)
        if not sections:
            result = _message_lines(
                options,
                [
                    "子地图均无结果: " + options.query,
                    "容器级与全部子地图均已查询；可换名称/四码，或用 search、text、near 继续查。",
                ],
                2,
            )
            coverages = tuple(
                row.script_coverage
                for row in observed
                if row.script_coverage is not None
            )
            return replace(
                result,
                sections=tuple(
                    replace(
                        row,
                        has_matches=False,
                        script_coverage=combine_script_coverage(coverages),
                    )
                    for row in result.sections
                )
                if coverages
                else result.sections,
                checked_packs=checked,
            )
        success = any(_section_has_result(options.command, row) for row in sections)
        if options.command == "calls" and any(row.input_error for row in sections):
            success = False
        if remember and success:
            queries._store_last_query(pack, options.command, options.query)
        return PackQueryResult(
            str(pack),
            options.command,
            options.query,
            tuple(sections),
            0 if success else 2,
            campaign=True,
            checked_packs=checked,
        )
    success = _section_has_result(options.command, section)
    if success and remember:
        queries._store_last_query(pack, options.command, options.query)
    return PackQueryResult(
        str(pack),
        options.command,
        options.query,
        (section,),
        0 if success else 2,
        checked_packs=checked,
    )


def _section_has_result(command: str, section: QuerySection) -> bool:
    if section.input_error:
        return False
    if section.has_matches is not None:
        return section.has_matches
    return _has_result(command, section.lines, section.entries, section.regions)


def _has_result(
    command: str,
    lines: Sequence[str],
    entries: tuple[NearEntry, ...] = (),
    regions: tuple[NearRegion, ...] = (),
) -> bool:
    if command == "near":
        return bool(entries or regions)
    if not lines or lines[0].startswith(("未找到", "diff 需要", "第二个包")):
        return False
    return True


def _run_section(
    queries: QueryBackend, command: str, title: str, pack: Path, query: str, limit: int
) -> QuerySection:
    if command == "calls":
        report = queries._query_calls_result(pack, query, limit)
        return _call_section(QuerySection(title, str(pack), ()), report)
    if command in SCRIPT_QUERY_COMMANDS:
        result = queries._query_script_result(pack, command, query, limit)
        return QuerySection(
            title,
            str(pack),
            result.lines,
            has_matches=result.has_matches,
            script_coverage=result.script_coverage,
        )
    if command == "near":
        result = queries._query_near_result(pack, query, limit)
        return QuerySection(
            title,
            str(pack),
            result.lines,
            result.entries,
            result.regions,
            result.regions_total,
            result.spatial_diagnostics,
            result.input_error,
        )
    return _section(command, title, pack, queries._QUERIES[command](pack, query, limit))


def _section(
    command: str, title: str, pack: Path, lines: Sequence[str]
) -> QuerySection:
    del command
    return QuerySection(
        title,
        str(pack),
        tuple(lines),
    )


def _message(
    options: PackQueryCliOptions, text: str, exit_code: int
) -> PackQueryResult:
    return _message_lines(options, [text], exit_code)


def _message_lines(
    options: PackQueryCliOptions, lines: Sequence[str], exit_code: int
) -> PackQueryResult:
    return PackQueryResult(
        options.pack_dir,
        options.command,
        options.query,
        (
            _section(
                options.command,
                "near" if options.command == "near" else "",
                Path(options.pack_dir),
                lines,
            ),
        ),
        exit_code,
    )

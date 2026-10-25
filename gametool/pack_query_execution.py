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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .pack_query_spatial import NearEntry, SpatialQueryResult
from .pack_query_regions import NearRegion

if TYPE_CHECKING:
    from .pack_query_options import PackQueryCliOptions


class QueryBackend(Protocol):
    """Query functions and session state supplied by the public query API."""

    _TABLE_READ_LOCK: AbstractContextManager[object]
    _QUERY_ROWS: dict[tuple[str, str], list[list[str]]] | None
    _QUERY_SCRIPTS: dict[str, str | None] | None
    _QUERY_SCRIPT_SOURCES: dict[str, tuple[tuple[str, str], ...]] | None
    _QUERY_FILES: set[tuple[str, str]] | None
    _LOCKED_FILES: set[tuple[str, str]]
    _QUERIES: dict[str, Callable[[Path, str, int], list[str]]]

    def _load_last_query(self) -> dict[str, str] | None: ...

    def _store_last_query(self, pack: Path, command: str, query: str) -> None: ...

    def _campaign_subpacks(self, pack: Path) -> list[Path]: ...

    def _query_diff(
        self, pack: Path, query: str, limit: int, pack_b: str = ""
    ) -> list[str]: ...

    def _query_near_result(
        self, pack: Path, query: str, limit: int
    ) -> SpatialQueryResult: ...


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
            "warnings": [note for note in self.diagnostics if note.startswith("[⚠")],
        }
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
    with queries._TABLE_READ_LOCK:
        previous = queries._QUERY_ROWS
        previous_scripts = queries._QUERY_SCRIPTS
        previous_sources = queries._QUERY_SCRIPT_SOURCES
        previous_files = queries._QUERY_FILES
        queries._QUERY_ROWS = {}
        queries._QUERY_SCRIPTS = {}
        queries._QUERY_SCRIPT_SOURCES = {}
        queries._QUERY_FILES = set()
        try:
            result = _collect_query(options, queries)
        finally:
            touched = queries._QUERY_FILES or set()
            queries._QUERY_ROWS = previous
            queries._QUERY_SCRIPTS = previous_scripts
            queries._QUERY_SCRIPT_SOURCES = previous_sources
            queries._QUERY_FILES = previous_files
        root = Path(result.pack).resolve()
        diagnostics = tuple(
            f"[⚠ 数据文件读取失败, 本次结果可能缺失: {rel} — "
            f"检查文件权限/编码或重新导出知识包: {pack}]"
            for pack, rel in sorted(queries._LOCKED_FILES.intersection(touched))
            if (Path(pack) / rel).resolve().is_relative_to(root)
        )
    elapsed_ms = (time.perf_counter() - started) * 1000
    hint = " — 同包再查走热缓存会快很多" if elapsed_ms > 500 else ""
    return replace(
        result, diagnostics=(*diagnostics, f"[耗时 {elapsed_ms:.0f}ms{hint}]")
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
        return _message(options, "资料包目录不存在: " + options.pack_dir, 2)
    if options.command not in queries._QUERIES:
        return _message(options, "未知子命令: " + options.command, 2)
    if options.command == "near" and options.near_kind:
        options = replace(options, query=options.query + " --kind " + options.near_kind)
    if options.command == "diff":
        lines = queries._query_diff(
            pack, options.query, options.limit, options.pack_dir_b or options.query
        )
        return _message_lines(
            options, lines, 0 if _has_result(options.command, lines) else 2
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
    lines = section.lines
    if options.command == "near" and section.input_error:
        return PackQueryResult(str(pack), options.command, options.query, (section,), 2)
    if options.command == "near":
        subs = queries._campaign_subpacks(pack)
    checked = (
        (str(pack), *(str(sub) for sub in subs)) if options.command == "near" else ()
    )
    if subs:
        sections: list[QuerySection] = []
        if _has_result(options.command, lines, section.entries, section.regions) or (
            options.command == "near" and section.spatial_diagnostics
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
            if _has_result(
                options.command,
                sub_section.lines,
                sub_section.entries,
                sub_section.regions,
            ) or (options.command == "near" and sub_section.spatial_diagnostics):
                sections.append(sub_section)
        if not sections:
            return replace(
                _message_lines(
                    options,
                    [
                        "子地图均无结果: " + options.query,
                        "容器级与全部子地图均已查询；可换名称/四码，或用 search、text、near 继续查。",
                    ],
                    2,
                ),
                checked_packs=checked,
            )
        success = any(
            _has_result(options.command, row.lines, row.entries, row.regions)
            for row in sections
        )
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
    success = _has_result(options.command, lines, section.entries, section.regions)
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

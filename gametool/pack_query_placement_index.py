"""Complete indexed coordinates with explicit, source-local identity matching."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from .script_assignments import expression_key
from .script_placement_analysis import (
    PLACEMENT_APIS,
    analyze_script_placements,
    placement_api_name,
)
from .script_scopes import script_structure
from .script_source_identity import ScriptSourceMatch, ScriptSourceNames
from .script_sources import AnalysisScriptSource, script_language

type PlacementRow = tuple[str, float, float, str]
type IndexedCallRow = tuple[tuple[str, ...], str, str]


@dataclass(frozen=True, slots=True)
class IndexedPlacements:
    placements: tuple[PlacementRow, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(slots=True)
class _IndexedSite:
    match: ScriptSourceMatch
    offset: str
    origins: dict[tuple[str, str], None] = field(default_factory=dict)
    summaries: dict[str, dict[tuple[str, str], None]] = field(default_factory=dict)
    placement_call: bool = False

    def label(self) -> str:
        source, line = next(iter(self.origins))
        return f"  索引来源 {source} / 行号{line or '未记录'} / 偏移{self.offset or '未记录'}"

    def evidence(self) -> str:
        return "\n".join(
            "    证据来源: "
            + "; ".join(
                f"{source} / 行号{line or '未记录'}" for source, line in origins
            )
            + "\n    原文: "
            + summary
            for summary, origins in self.summaries.items()
        )


@lru_cache(maxsize=8)
def indexed_placements(
    contexts: tuple[AnalysisScriptSource, ...],
    rows: tuple[IndexedCallRow, ...],
    declared_script_type: str = "",
) -> IndexedPlacements:
    """Reuse source contexts for mirrors; retain independent legacy index calls."""
    if not rows:
        return IndexedPlacements()
    names = ScriptSourceNames(source.source for source in contexts)
    by_name = {source.source: source for source in contexts}
    calls = {
        source.source: {
            expression_key(source.text[call.start : call.end], lua=source.lua)
            for call in script_structure(source.text, lua=source.lua).calls
            if placement_api_name(call.name, lua=source.lua) in PLACEMENT_APIS
        }
        for source in contexts
    }
    sites: dict[tuple[str, ...], _IndexedSite] = {}
    for row, summary, offset in rows:
        if not row:
            continue
        match = names.resolve(row[0])
        key = (match.key, offset) if offset else (match.key, *row[1:2], summary)
        site = sites.get(key)
        if site is None:
            site = sites[key] = _IndexedSite(match, offset)
        origin = row[0], row[1] if len(row) > 1 else ""
        site.origins.setdefault(origin, None)
        if summary.strip():
            site.summaries.setdefault(summary, {}).setdefault(origin, None)
        if len(row) > 3:
            site.placement_call |= (
                placement_api_name(row[3], lua=None) in PLACEMENT_APIS
            )
    placements: list[PlacementRow] = []
    diagnostics: list[str] = []
    candidate_groups: dict[int, int] = {}
    keys: dict[tuple[str, bool | None], str] = {}

    def syntax_key(summary: str, lua: bool | None) -> str:
        key = summary, lua
        if key not in keys:
            keys[key] = expression_key(summary, lua=lua)
        return keys[key]

    for site in sites.values():
        match = site.match
        if match.diagnostic:
            reason = match.diagnostic
            if match.sources:
                identity = id(match.sources)
                group = candidate_groups.get(identity)
                if group is None:
                    group = len(candidate_groups) + 1
                    candidate_groups[identity] = group
                    reason = f"来源候选组 {group}: " + reason
                else:
                    reason = f"来源候选组 {group}: {len(match.sources)} 个候选（见该组首次诊断），未猜测来源"
            diagnostics.append(site.label() + ": " + reason + "\n" + site.evidence())
            continue
        source_label = next(iter(site.origins))[0]
        if contexts and not source_label.strip():
            diagnostics.append(
                site.label()
                + ": 来源未记录，无法确认是现有脚本镜像还是独立调用，未猜测额外实例或原生绑定；请补全来源，或用 text <码> 查完整原文。\n"
                + site.evidence()
            )
            continue
        source = by_name[match.sources[0]] if match.sources else None
        lua = (
            source.lua
            if source is not None
            else script_language(
                source_label,
                available_sources=by_name,
                declared_script_type=declared_script_type,
            )
        )
        summaries: dict[str, str] = {}
        for summary in site.summaries:
            if key := syntax_key(summary, lua):
                summaries.setdefault(key, summary)
        if not summaries:
            if site.placement_call:
                diagnostics.append(
                    site.label()
                    + ": 未记录可解析的调用摘要，未猜测坐标；可用 text <码> 查完整原文或重新导出知识包。"
                )
            continue
        if len(summaries) > 1:
            diagnostics.append(
                site.label()
                + f": 同一调用身份有 {len(summaries)} 份不一致原文，未选择其中的坐标；请核对索引或用 text <码> 查完整原文。\n"
                + site.evidence()
            )
            continue
        summary = next(iter(summaries.values()))
        mirrored = calls.get(source.source, set()) if source is not None else set()
        report = analyze_script_placements(summary, lua=lua)
        for placement in report.placements:
            if syntax_key(placement.expression, lua) not in mirrored:
                placements.append(placement.row())
        for note in report.diagnostics:
            if syntax_key(note.expression, lua) not in mirrored:
                diagnostics.append(
                    site.label() + ": " + note.reason + "\n    原文: " + note.expression
                )
    return IndexedPlacements(tuple(placements), tuple(diagnostics))

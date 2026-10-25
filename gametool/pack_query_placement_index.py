"""Complete indexed coordinates with explicit, source-local identity matching."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .script_assignments import expression_key
from .script_placement_analysis import (
    PLACEMENT_APIS,
    analyze_script_placements,
    placement_api_name,
)
from .script_scopes import script_structure
from .script_source_identity import ScriptSourceNames
from .script_sources import AnalysisScriptSource, script_language

type PlacementRow = tuple[str, float, float, str]
type IndexedCallRow = tuple[tuple[str, ...], str, str]


@dataclass(frozen=True, slots=True)
class IndexedPlacements:
    placements: tuple[PlacementRow, ...] = ()
    diagnostics: tuple[str, ...] = ()


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
    seen: set[tuple[str, ...]] = set()
    placements: list[PlacementRow] = []
    diagnostics: list[str] = []
    candidate_groups: dict[int, int] = {}
    for row, summary, offset in rows:
        if not row:
            continue
        match = names.resolve(row[0])
        key = (match.key, offset) if offset else (match.key, *row[1:2], summary)
        if key in seen:
            continue
        seen.add(key)
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
            diagnostics.append(
                f"  索引来源 {row[0]} / 行号{row[1] if len(row) > 1 else '未记录'} / 偏移{offset or '未记录'}: {reason}\n    原文: {summary}"
            )
            continue
        source = by_name[match.sources[0]] if match.sources else None
        lua = (
            source.lua
            if source is not None
            else script_language(
                row[0],
                available_sources=by_name,
                declared_script_type=declared_script_type,
            )
        )
        mirrored = calls.get(source.source, set()) if source is not None else set()
        for placement in analyze_script_placements(summary, lua=lua).placements:
            if expression_key(placement.expression, lua=lua) not in mirrored:
                placements.append(placement.row())
    return IndexedPlacements(tuple(placements), tuple(diagnostics))

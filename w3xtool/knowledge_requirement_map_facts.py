"""Map facts used to evaluate requirement availability and completeness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .extraction_completeness import (
    ExtractionCompletenessReport,
    build_extraction_completeness_report,
)
from .item_relation_models import RelationCompleteness
from .object_text_models import ObjectTextState

if TYPE_CHECKING:
    from .map_data import MapData


@dataclass(frozen=True, slots=True)
class MapRequirementFacts:
    files: int
    objects: int
    scripts: int
    placements: int
    world: int
    triggers: int
    variables: int
    eca: int
    has_terrain: bool
    source_readable: bool
    completeness_warnings: int
    text_records: int
    relation_records: int
    text_partial: bool
    relation_partial: bool


def build_map_requirement_facts(
    md: MapData,
    completeness: ExtractionCompletenessReport | None = None,
) -> MapRequirementFacts:
    """Measure only facts needed by the requirement status rules."""
    summary = md.trigger_summary
    files = tuple(md.all_files)
    resolved_completeness = (
        completeness
        if completeness is not None
        else build_extraction_completeness_report(md)
    )
    return MapRequirementFacts(
        files=len(files),
        objects=sum(len(items) for items in md.objects.values()),
        scripts=len(md.scripts),
        placements=len(md.units) + len(md.doodads),
        world=len(md.regions) + len(md.cameras) + len(md.sounds),
        triggers=len(tuple(getattr(summary, "triggers", ()) or ())),
        variables=len(tuple(getattr(summary, "variables", ()) or ())),
        eca=len(tuple(getattr(summary, "eca_functions", ()) or ())),
        has_terrain=any(
            name.lower().endswith((".w3e", ".wpm", ".shd")) for name in files
        ),
        source_readable=resolved_completeness.source_readable,
        completeness_warnings=len(resolved_completeness.warnings),
        text_records=len(md.object_texts.records),
        relation_records=len(md.item_relations.records),
        text_partial=any(
            record.state
            in {
                ObjectTextState.AUTHOR_UNDEFINED,
                ObjectTextState.SOURCE_UNAVAILABLE,
                ObjectTextState.SOURCE_CONFLICT,
            }
            for record in md.object_texts.records
        ),
        relation_partial=any(
            relation.completeness is not RelationCompleteness.COMPLETE
            for relation in md.item_relations.records
        ),
    )


def request_available(request: str, facts: MapRequirementFacts) -> bool | None:
    """Return whether one open-catalog requirement has matching map data."""
    match request:  # noqa: MATCH_OK - requirement names are an open catalog.
        case "提取/整理 UI 文本":
            return bool(facts.scripts or facts.objects)
        case "提取/整理图标和资源":
            return bool(facts.files or facts.scripts or facts.objects)
        case "整理配置文件格式":
            return bool(facts.files)
        case "分析本地存档读写":
            return bool(facts.scripts)
        case "分析地图 ID":
            return True
        case "分析物品/技能/单位 ID":
            return bool(facts.objects or facts.placements)
        case "提取完整对象说明":
            return bool(facts.text_records)
        case "分析装备掉落与获取":
            return bool(facts.relation_records)
        case request_name if request_name.startswith("分析脚本"):
            return bool(facts.scripts)
        case "分析预放置单位/装饰物":
            return bool(facts.placements)
        case "分析触发器和全局变量":
            return bool(facts.triggers or facts.variables or facts.eca)
        case "分析区域/镜头/声音":
            return bool(facts.world)
        case "分析地形和路径网格":
            return facts.has_terrain
        case "核对提取是否完整":
            return True
        case _:
            return None


def completeness_status(facts: MapRequirementFacts) -> str:
    """Describe extraction completeness from source and warning facts."""
    if not facts.source_readable:
        return "部分覆盖（源不可读）"
    if facts.completeness_warnings:
        return "部分覆盖（有警告）"
    return "已覆盖（诊断+兜底导出）"

"""Requirement catalog rows for complete text and item intelligence."""

from __future__ import annotations

from typing import Final

from .knowledge_requirement_models import RequirementCoverage

ITEM_INTELLIGENCE_REQUIREMENTS: Final = (
    RequirementCoverage(
        "提取完整对象说明",
        "已覆盖（逐字段证据）",
        ("对象完整描述.tsv",),
        ("对象字段.tsv", "对象文本与图标.tsv", "关系完整性.txt"),
        "保留全部文本角色、等级、原始/可读全文、来源、状态、占位和冲突证据。",
    ),
    RequirementCoverage(
        "分析装备掉落与获取",
        "已覆盖（静态证据）",
        ("掉落与获取关系.tsv",),
        ("装备技能关系.tsv", "关系完整性.txt", "预放置单位.tsv", "预放置装饰物.tsv"),
        "统一怪物、可破坏物、商店、合成、地图放置、脚本奖励及装备技能关系。",
    ),
)

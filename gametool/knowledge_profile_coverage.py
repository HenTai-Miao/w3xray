"""Apply the requested extraction scope to published requirement claims."""

from __future__ import annotations

from dataclasses import replace
from typing import Final

from .extraction_profile import CATEGORY_LABELS, ExtractionProfile
from .games.warcraft import WARCRAFT_ADAPTER
from .knowledge_requirement_models import RequirementCoverage

_ALWAYS_WRITTEN: Final = frozenset(("需求覆盖.tsv", "资料包写入结果.tsv"))


def apply_profile_coverage(
    rows: tuple[RequirementCoverage, ...], profile: ExtractionProfile | None
) -> tuple[RequirementCoverage, ...]:
    """Disclose deliberate omissions without describing them as source gaps."""
    if profile is None or not profile.disabled_categories():
        return rows
    disabled = profile.disabled_categories()
    summary = "、".join(f"{key}（{CATEGORY_LABELS[key]}）" for key in disabled)
    configured: list[RequirementCoverage] = [
        RequirementCoverage(
            "提取配置",
            "按请求筛选",
            ("需求覆盖.tsv", "资料包写入结果.tsv"),
            (),
            f"本次按请求关闭：{summary}。关闭的产物未写入，不代表地图缺少相应数据；"
            "始终保留需求覆盖与写入结果。发布完整仅表示开启范围内的写入完成。",
        )
    ]
    for row in rows:
        skipped = tuple(
            path
            for path in (*row.primary, *row.secondary)
            if not _artifact_allowed(path, profile)
        )
        if not skipped:
            configured.append(row)
            continue
        primary = tuple(path for path in row.primary if path not in skipped)
        secondary = tuple(path for path in row.secondary if path not in skipped)
        status = row.status
        if len(primary) != len(row.primary):
            status = "按请求部分产出" if primary else "按请求未产出主要产物"
        note = row.note + " 按提取配置未产出：" + "、".join(skipped) + "。"
        configured.append(
            replace(row, status=status, primary=primary, secondary=secondary, note=note)
        )
    return tuple(configured)


def _artifact_allowed(path: str, profile: ExtractionProfile) -> bool:
    if path in _ALWAYS_WRITTEN:
        return True
    category = "basic"
    specificity = -1
    for group in WARCRAFT_ADAPTER.export_groups:
        for declared in group.files:
            matches = path == declared or (
                declared.endswith("/") and path.startswith(declared)
            )
            if matches and len(declared) > specificity:
                category = group.category
                specificity = len(declared)
    return profile.allows(category)

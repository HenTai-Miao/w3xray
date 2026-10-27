"""Public knowledge-pack publication APIs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import os
from typing import Final

from .extraction_profile import ExtractionProfile, load_profile
from .knowledge_io import knowledge_write_session, safe_filename, write_text
from .knowledge_object_exports import format_box_id_text as format_box_id_text
from .knowledge_pack_contents import write_knowledge_pack_contents
from .knowledge_requirements import format_requirement_coverage
from .knowledge_results import (
    KnowledgeWriteItem,
    KnowledgeWriteReport,
    KnowledgeWriteStatus,
    format_knowledge_write_report,
)
from .map_data import MapData

_FINALIZATION_ROUNDS: Final = 8


def write_knowledge_pack(
    md: MapData,
    out_dir: str,
    external_names: Sequence[str] = (),
    game_data_path: str | None = None,
    *,
    profile: ExtractionProfile | None = None,
) -> int:
    """Write a map knowledge pack and return the number of files written."""
    return write_knowledge_pack_report(
        md,
        out_dir,
        external_names=external_names,
        game_data_path=game_data_path,
        profile=profile,
    ).written_count


def write_knowledge_pack_report(
    md: MapData,
    out_dir: str,
    external_names: Sequence[str] = (),
    game_data_path: str | None = None,
    *,
    publication_root: str | None = None,
    profile: ExtractionProfile | None = None,
) -> KnowledgeWriteReport:
    """Write a map knowledge pack and return final per-file outcomes.

    profile: 提取开关 (None = 读取持久化配置; 全部未配置时全量导出)。
    """
    destination_error = _destination_error(out_dir)
    if destination_error is not None:
        return KnowledgeWriteReport(
            (KnowledgeWriteItem(".", False, 0, destination_error),)
        )
    effective_profile = profile if profile is not None else load_profile()
    with knowledge_write_session(
        out_dir, publication_root=publication_root
    ) as recorder:
        _count, capabilities = write_knowledge_pack_contents(
            md,
            out_dir,
            external_names,
            game_data_path,
            profile=effective_profile,
        )
        coverage_text = ""
        result_text = ""
        for _round in range(_FINALIZATION_ROUNDS):
            coverage_text = format_requirement_coverage(
                md,
                replace(capabilities, write_report=recorder.report()),
            )
            _ = write_text(out_dir, "需求覆盖.tsv", coverage_text)
            result_text = format_knowledge_write_report(recorder.report())
            _ = write_text(out_dir, "资料包写入结果.tsv", result_text)
            final_report = recorder.report()
            if coverage_text == format_requirement_coverage(
                md,
                replace(capabilities, write_report=final_report),
            ) and result_text == format_knowledge_write_report(final_report):
                return final_report
        return recorder.report()


def write_knowledge_pack_family_report(
    md: MapData,
    out_dir: str,
    external_names: Sequence[str] = (),
    game_data_path: str | None = None,
    *,
    profile: ExtractionProfile | None = None,
) -> KnowledgeWriteReport:
    """Publish the selected map plus every loaded immediate campaign child."""
    effective_profile = profile if profile is not None else load_profile()
    parent = write_knowledge_pack_report(
        md,
        out_dir,
        external_names=external_names,
        game_data_path=game_data_path,
        profile=effective_profile,
    )
    if parent.status is KnowledgeWriteStatus.FAILED and parent.written_count == 0:
        return parent
    items = list(parent.items)
    for index, child in enumerate(md.sub_maps, start=1):
        directory = f"{index:03d}_{safe_filename(child.name)}"
        prefix = f"子地图/{directory}"
        report = write_knowledge_pack_report(
            child,
            os.path.join(out_dir, "子地图", directory),
            external_names=external_names,
            game_data_path=game_data_path,
            publication_root=out_dir,
            profile=effective_profile,
        )
        items.extend(
            replace(item, path=f"{prefix}/{item.path}") for item in report.items
        )
    return KnowledgeWriteReport(tuple(items))


def _destination_error(out_dir: str) -> str | None:
    """Keep previous packs and user files untouched instead of merging maps."""
    if os.path.islink(out_dir):
        return "资料包输出目录不能是符号链接；请选择新的空目录。"
    try:
        with os.scandir(out_dir) as entries:
            if next(entries, None) is not None:
                return (
                    "资料包输出目录非空，不能混入旧地图或用户文件；请选择新的空目录。"
                )
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"资料包输出目录不可用；请选择新的空目录。{type(exc).__name__}: {exc}"
    return None

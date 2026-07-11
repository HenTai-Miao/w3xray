"""Public knowledge-pack publication APIs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Final

from .knowledge_io import knowledge_write_session, write_text
from .knowledge_object_exports import format_box_id_text as format_box_id_text
from .knowledge_pack_contents import write_knowledge_pack_contents
from .knowledge_requirements import format_requirement_coverage
from .knowledge_results import KnowledgeWriteReport, format_knowledge_write_report
from .map_data import MapData

_FINALIZATION_ROUNDS: Final = 8


def write_knowledge_pack(
    md: MapData,
    out_dir: str,
    external_names: Sequence[str] = (),
    game_data_path: str | None = None,
) -> int:
    """Write a map knowledge pack and return the number of files written."""
    return write_knowledge_pack_report(
        md,
        out_dir,
        external_names=external_names,
        game_data_path=game_data_path,
    ).written_count


def write_knowledge_pack_report(
    md: MapData,
    out_dir: str,
    external_names: Sequence[str] = (),
    game_data_path: str | None = None,
    *,
    publication_root: str | None = None,
) -> KnowledgeWriteReport:
    """Write a map knowledge pack and return final per-file outcomes."""
    with knowledge_write_session(out_dir, publication_root=publication_root) as recorder:
        _count, capabilities = write_knowledge_pack_contents(
            md,
            out_dir,
            external_names,
            game_data_path,
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
            if (
                coverage_text
                == format_requirement_coverage(
                    md,
                    replace(capabilities, write_report=final_report),
                )
                and result_text == format_knowledge_write_report(final_report)
            ):
                return final_report
        return recorder.report()

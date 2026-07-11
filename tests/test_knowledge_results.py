"""Structured knowledge-pack write results and integer compatibility."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ContextManager

import pytest

from w3xtool.knowledge_pack import write_knowledge_pack, write_knowledge_pack_report
from w3xtool.knowledge_results import (
    KnowledgeWriteItem,
    KnowledgeWriteReport,
    KnowledgeWriteStatus,
)
from w3xtool.knowledge_requirements import ExtractionCapabilities, format_requirement_coverage
from w3xtool.map_data import GameObject, MapData
from w3xtool.map_archive_reader import MapArchiveReader
from w3xtool.safe_output_models import SafeWriteResult, SafeWriteStatus


@dataclass(frozen=True, slots=True)
class _UnavailableArchiveSource:
    path: str = "missing.w3x"

    def open(self) -> ContextManager[MapArchiveReader]:
        raise OSError("archive source unavailable")

    def close(self) -> None:
        return


def test_pack_reports_partial_success_instead_of_counting_failed_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: one category report fails while every other pack artifact remains writable.
    from w3xtool import knowledge_io

    original = knowledge_io.write_text_safely

    def fail_unit_table(root: str, name: str, text: str) -> SafeWriteResult:
        relative = f"{Path(root).name}/{name}".replace("\\", "/")
        if relative.endswith("对象ID/单位.tsv"):
            return SafeWriteResult(
                SafeWriteStatus.FAILED,
                "",
                0,
                "disk full",
            )
        return original(root, name, text)

    monkeypatch.setattr(knowledge_io, "write_text_safely", fail_unit_table)

    # When: the detailed pack API writes the remaining independent files.
    report = write_knowledge_pack_report(_minimal_map(), str(tmp_path / "pack"))

    # Then: the exact failure is retained and the overall result is partial.
    assert report.failed_count == 1
    assert report.status is KnowledgeWriteStatus.PARTIAL
    assert report.items_by_path["对象ID/单位.tsv"].error == "disk full"
    written = (tmp_path / "pack" / "资料包写入结果.tsv").read_text(encoding="utf-8")
    assert "对象ID/单位.tsv" in written
    assert "disk full" in written


def test_integer_facade_returns_detailed_report_written_count(tmp_path: Path) -> None:
    # Given: equivalent maps and distinct output directories.
    md = _minimal_map()

    # When: callers use the detailed API and the legacy integer facade.
    report = write_knowledge_pack_report(md, str(tmp_path / "report"))
    count = write_knowledge_pack(md, str(tmp_path / "legacy"))

    # Then: the compatibility result is derived from the structured report.
    assert count == report.written_count
    assert report.status is KnowledgeWriteStatus.COMPLETE


def test_binary_resource_body_is_recorded_in_write_report(tmp_path: Path) -> None:
    # Given: a readable map directory contains a binary asset body.
    source = tmp_path / "source"
    asset = source / "Assets" / "Panel.blp"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"BLP1panel")
    md = _minimal_map(path=source)
    md.all_files = ["Assets\\Panel.blp"]

    # When: the knowledge pack copies text and binary artifacts.
    report = write_knowledge_pack_report(md, str(tmp_path / "pack"))

    # Then: the binary body has the same structured success record as text files.
    item = report.items_by_path["资源/素材文件/assets/panel.blp"]
    assert item.written
    assert item.size == len(b"BLP1panel")


def test_requirement_coverage_reports_partial_publication() -> None:
    # Given: one artifact succeeded and one failed in the current publication.
    report = KnowledgeWriteReport((
        KnowledgeWriteItem("地图信息.txt", True, 12, None),
        KnowledgeWriteItem("对象ID/单位.tsv", False, 0, "disk full"),
    ))

    # When: dynamic requirement coverage is formatted with the publication result.
    text = format_requirement_coverage(
        _minimal_map(),
        ExtractionCapabilities(write_report=report),
    )

    # Then: users see the partial state, counts, and first failed path.
    assert "资料包发布\t部分完成" in text
    assert "成功 1，失败 1" in text
    assert "对象ID/单位.tsv" in text


def test_pack_manifest_lists_diagnostics_and_write_results(tmp_path: Path) -> None:
    # Given/When: a complete knowledge pack is published.
    report = write_knowledge_pack_report(_minimal_map(), str(tmp_path / "pack"))

    # Then: the catalog and refreshed coverage expose publication observability.
    manifest = (tmp_path / "pack" / "资料包目录.tsv").read_text(encoding="utf-8")
    coverage = (tmp_path / "pack" / "需求覆盖.tsv").read_text(encoding="utf-8")
    assert "组件诊断.tsv" in manifest
    assert "资料包写入结果.tsv" in manifest
    assert "资料包发布\t完整" in coverage
    assert report.items_by_path["资料包写入结果.tsv"].written


def test_persisted_publication_metadata_matches_final_report(tmp_path: Path) -> None:
    # Given: a complete publication whose result file must describe itself.
    pack_dir = tmp_path / "pack"

    # When: the detailed pack API reaches its final snapshot.
    report = write_knowledge_pack_report(_minimal_map(), str(pack_dir))

    # Then: report rows and coverage counts match the returned final state exactly.
    result_lines = (pack_dir / "资料包写入结果.tsv").read_text(encoding="utf-8").splitlines()
    coverage = (pack_dir / "需求覆盖.tsv").read_text(encoding="utf-8")
    assert len(result_lines) - 1 == len(report.items)
    assert any(line.startswith("资料包写入结果.tsv\t已写入\t") for line in result_lines)
    assert f"成功 {report.written_count}，失败 {report.failed_count}" in coverage


def test_real_unusable_output_root_returns_failed_report(tmp_path: Path) -> None:
    # Given: the requested pack root is an existing regular file.
    blocked_root = tmp_path / "blocked"
    blocked_root.write_text("not a directory", encoding="utf-8")

    # When: publication attempts the real filesystem boundary.
    report = write_knowledge_pack_report(_minimal_map(), str(blocked_root))

    # Then: callers receive structured failure instead of an uncaught FileExistsError.
    assert report.status is KnowledgeWriteStatus.FAILED
    assert report.written_count == 0
    assert report.failed_count > 0


def test_pack_reports_failed_when_every_attempted_path_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: the output boundary rejects every requested text artifact.
    from w3xtool import knowledge_io

    monkeypatch.setattr(
        knowledge_io,
        "write_text_safely",
        lambda _root, _name, _text: SafeWriteResult(
            SafeWriteStatus.FAILED,
            "",
            0,
            "read-only filesystem",
        ),
    )

    # When: publication attempts every independent artifact.
    report = write_knowledge_pack_report(_minimal_map(), str(tmp_path / "pack"))

    # Then: no failed path is counted as written and the session is fully failed.
    assert report.status is KnowledgeWriteStatus.FAILED
    assert report.written_count == 0
    assert report.failed_count > 0
    assert report.items_by_path["地图信息.txt"].error == "read-only filesystem"


def test_unknown_source_failure_is_recorded_in_pack_report(tmp_path: Path) -> None:
    # Given: the retained archive source cannot be reopened for anonymous blocks.
    md = _minimal_map()
    md.archive_source = _UnavailableArchiveSource()

    # When: the knowledge pack continues publishing independent artifacts.
    report = write_knowledge_pack_report(md, str(tmp_path / "pack"))

    # Then: the skipped Unknown area is an explicit partial-publication failure.
    item = report.items_by_path["未知文件/Unknown_manifest.tsv"]
    assert not item.written
    assert item.error == "OSError: unknown-file extraction failed"
    assert report.status is KnowledgeWriteStatus.PARTIAL
    persisted = (tmp_path / "pack" / "资料包写入结果.tsv").read_text(encoding="utf-8")
    assert "未知文件/Unknown_manifest.tsv" in persisted


def _minimal_map(path: Path | None = None) -> MapData:
    obj = GameObject("单位", "w3u", "H001", "hfoo", "Unit", True)
    md = MapData(path=str(path or "missing.w3x"), name="write report", objects={"单位": [obj]})
    md.obj_index = {obj.obj_id: obj}
    return md

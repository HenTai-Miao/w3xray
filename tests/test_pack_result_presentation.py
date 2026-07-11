"""GUI knowledge-pack result presentation does not overstate partial writes."""

from __future__ import annotations

from w3xtool.gui_export_actions import build_pack_export_presentation
from w3xtool.knowledge_results import KnowledgeWriteItem, KnowledgeWriteReport


def test_partial_pack_presentation_names_counts_and_first_failure() -> None:
    # Given: one artifact succeeded and one failed.
    report = KnowledgeWriteReport((
        KnowledgeWriteItem("地图信息.txt", True, 12, None),
        KnowledgeWriteItem("对象ID/单位.tsv", False, 0, "disk full"),
    ))

    # When: GUI copy is built from the structured result.
    presentation = build_pack_export_presentation("C:/Temp/pack", report)

    # Then: the UI says partial, never complete, and names the first failure.
    assert presentation.title == "部分完成"
    assert presentation.is_error is False
    assert "成功 1，失败 1" in presentation.status_text
    assert "对象ID/单位.tsv" in presentation.message
    assert "disk full" in presentation.message
    assert "完整" not in presentation.message


def test_failed_pack_presentation_uses_error_state() -> None:
    # Given: every attempted artifact failed.
    report = KnowledgeWriteReport((
        KnowledgeWriteItem("地图信息.txt", False, 0, "read-only filesystem"),
    ))

    # When: GUI copy is built from the failed result.
    presentation = build_pack_export_presentation("C:/Temp/pack", report)

    # Then: the GUI routes it through an error dialog with exact evidence.
    assert presentation.title == "导出失败"
    assert presentation.is_error
    assert "成功 0，失败 1" in presentation.status_text
    assert "read-only filesystem" in presentation.message

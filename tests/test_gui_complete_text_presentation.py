"""Complete-text evidence presentation for the object detail view."""

from __future__ import annotations

from tests.gui_base import GuiTestCase
from w3xtool.api import GameObject, MapData
from w3xtool.object_text_models import (
    ObjectTextIndex,
    ObjectTextRecord,
    ObjectTextState,
    TextSelectionReason,
)
from w3xtool.object_text_presentation import (
    ObjectTextView,
    format_complete_text_section,
)


class CompleteTextPresentationTest(GuiTestCase):
    def test_complete_text_current_view_excludes_only_lower_priority_rows(self) -> None:
        # Given
        obj = GameObject("技能", "w3a", "A001", "AHbz", "暴风雪", True)
        current = _text_record(
            "地图当前值",
            700,
            True,
            TextSelectionReason.HIGHEST_PRIORITY_VALUE,
            1,
            "war3map.w3a",
        )
        lower = _text_record(
            "SLK旧值",
            400,
            False,
            TextSelectionReason.LOWER_PRIORITY,
            2,
            "Units\\AbilityData.slk",
        )
        md = MapData(
            "map.w3x", "map", object_texts=ObjectTextIndex.build((current, lower))
        )

        # When
        selected = format_complete_text_section(md, obj, ObjectTextView.CURRENT)
        all_evidence = format_complete_text_section(md, obj, ObjectTextView.ALL)

        # Then
        assert "【完整文本】" in selected
        assert "【完整文本：可读版】" not in selected
        assert "【完整文本：原始版】" not in selected
        assert "地图当前值" in selected
        assert "SLK旧值" not in selected
        assert "最高优先级唯一值" not in selected
        assert "地图当前值" in all_evidence
        assert "SLK旧值" in all_evidence
        assert "低优先级证据" in all_evidence
        assert "非当前" in all_evidence

    def test_copy_text_payload_preserves_raw_newlines_tabs_and_color_codes(
        self,
    ) -> None:
        # Given
        raw = "|cffff0000第一行|r\n第二行\t字段"
        obj = GameObject("技能", "w3a", "A001", "AHbz", "暴风雪", True)
        record = _text_record(
            raw, 700, True, TextSelectionReason.HIGHEST_PRIORITY_VALUE, 1, "war3map.w3a"
        )
        md = MapData("map.w3x", "map", object_texts=ObjectTextIndex.build((record,)))

        # When
        payload = format_complete_text_section(md, obj, ObjectTextView.ALL)

        # Then: the raw value trails its readable body as one delta line, still exact.
        assert f"原始：{raw}" in payload
        assert "第一行\n第二行\t字段" in payload
        assert payload.count("原始：") == 1


def _text_record(
    raw: str,
    priority: int,
    is_current: bool,
    reason: TextSelectionReason,
    ordinal: int,
    source_path: str,
) -> ObjectTextRecord:
    return ObjectTextRecord(
        "技能",
        "A001",
        "AHbz",
        "暴风雪",
        True,
        "扩展提示",
        "ubertip",
        "aub1",
        "提示工具 - 扩展",
        1,
        raw,
        raw.replace("|cffff0000", "").replace("|r", ""),
        "地图文本字符串" if priority == 700 else "地图SLK",
        source_path,
        priority,
        ObjectTextState.MAP_VALUE,
        False,
        "",
        is_current,
        reason,
        ordinal,
    )

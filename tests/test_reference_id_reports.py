"""Reference-compatible ordering and text output for object ID reports."""

from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

from tests.gui_base import GuiTestCase
from w3xtool.api import GameObject, MapData
from w3xtool.knowledge_object_exports import (
    format_box_id_text,
    sorted_unique_objects,
    write_box_ids,
    write_object_ids,
)


def game_object(
    obj_id: str,
    name: str,
    field_values: dict[str, str] | None = None,
    *,
    category: str = "单位",
    fields: list[tuple[str, str]] | None = None,
) -> GameObject:
    """Build a report fixture with only the fields relevant to its output."""
    return GameObject(
        category=category,
        ext="w3u",
        obj_id=obj_id,
        base_id="hfoo",
        name=name,
        is_custom=True,
        fields=fields or [],
        field_values=field_values or {},
    )


def test_sorted_unique_objects_uses_latin1_replacement_bytes() -> None:
    # Given: rawcodes include non-Latin characters whose replacement bytes sort first.
    objects = (
        game_object("ÿ001", "late"),
        game_object("Ā001", "replacement"),
        game_object("A001", "ascii"),
    )

    # When: the shared report view is built.
    result = sorted_unique_objects(objects)

    # Then: ordering is deterministic by latin-1 replacement bytes.
    assert [item.obj_id for item in result] == ["Ā001", "A001", "ÿ001"]


def test_sorted_unique_objects_keeps_first_duplicate() -> None:
    # Given: one rawcode occurs twice with different object data.
    first = game_object("H001", "first")
    duplicate = game_object("H001", "second")

    # When: the shared report view is built.
    result = sorted_unique_objects((duplicate, first))

    # Then: only the first occurrence is retained.
    assert result == (duplicate,)


def test_unit_box_report_has_exact_propername_layout() -> None:
    # Given: a unit has canonical propernames and description values.
    unit = game_object(
        "H001",
        "前一个",
        {"display:propernames": "称谓甲", "display:description": "说明甲|n第二行"},
    )

    # When: the unit box-compatible report is formatted.
    text = format_box_id_text((unit,), category="单位")

    # Then: the reference layout has one blank line before the description.
    assert text == "ID：H001\n名字：前一个\n描述：称谓：称谓甲\n\n说明甲|n第二行\n"


def test_canonical_field_values_beat_legacy_labels() -> None:
    # Given: canonical values and conflicting legacy labels are both present.
    unit = game_object(
        "H001",
        "单位",
        {"display:propernames": "规范称谓", "display:description": "规范说明"},
        fields=[("Propernames", "旧称谓"), ("Ubertip", "旧说明")],
    )

    # When: the unit report is formatted.
    text = format_box_id_text((unit,), category="单位")

    # Then: canonical field_values are emitted.
    assert "描述：称谓：规范称谓\n\n规范说明" in text
    assert "旧称谓" not in text
    assert "旧说明" not in text


def test_legacy_labels_are_used_when_canonical_values_are_absent() -> None:
    # Given: an old caller supplies only labeled fields.
    unit = game_object(
        "H001",
        "单位",
        fields=[("Propernames", "旧称谓"), ("Ubertip", "旧说明")],
    )

    # When: the unit report is formatted.
    text = format_box_id_text((unit,), category="单位")

    # Then: legacy labels remain visible in the reference layout.
    assert "描述：称谓：旧称谓\n\n旧说明" in text


def test_rich_text_is_preserved_and_only_newlines_are_normalized() -> None:
    # Given: a description contains Warcraft markers and file-style newlines.
    unit = game_object(
        "H001",
        "单位",
        {
            "display:propernames": "称谓",
            "display:description": "|cffffcc00说明|r\r\n第二行|n第三行",
        },
    )

    # When: the box-compatible report is formatted.
    text = format_box_id_text((unit,), category="单位")

    # Then: markers survive and CRLF becomes the report newline.
    assert "|cffffcc00说明|r\n第二行|n第三行" in text
    assert "\r" not in text


def test_unresolved_text_is_emitted_verbatim() -> None:
    # Given: the extraction pipeline leaves an unresolved token in its canonical value.
    unit = game_object(
        "H001",
        "单位",
        {"display:propernames": "称谓", "display:description": "TRIGSTR_999"},
    )

    # When: the box-compatible report is formatted.
    text = format_box_id_text((unit,), category="单位")

    # Then: the unresolved token is visible to the report consumer.
    assert "\n\nTRIGSTR_999\n" in text


def test_one_argument_box_formatter_remains_compatible() -> None:
    # Given: a non-unit object uses the old one-argument API.
    ability = game_object(
        "A001",
        "技能",
        {"display:description": "技能说明"},
        category="技能",
    )

    # When: the formatter is called without a category.
    text = format_box_id_text((ability,))

    # Then: the legacy ID/name/description shape is preserved.
    assert text == "ID：A001\n名字：技能\n描述：技能说明\n"


def test_tsv_and_box_writers_share_sorted_deduped_order() -> None:
    # Given: a category has reversed input and a duplicate rawcode.
    md = MapData(path="x.w3x", name="ID图")
    md.objects = {
        "技能": [
            game_object("A010", "后", {"display:description": "后说明"}, category="技能"),
            game_object("A001", "前", {"display:description": "前说明"}, category="技能"),
            game_object("A001", "重复", {"display:description": "重复说明"}, category="技能"),
        ]
    }

    # When: both report writers export the category.
    with tempfile.TemporaryDirectory() as output:
        object_dir = Path(output) / "objects"
        box_dir = Path(output) / "box"
        write_object_ids(md, str(object_dir))
        write_box_ids(md, str(box_dir))
        tsv = (object_dir / "技能.tsv").read_text(encoding="utf-8")
        box = (box_dir / "技能ID.txt").read_text(encoding="utf-8")

    # Then: both outputs have the same unique sorted ID sequence.
    assert tsv.count("A001") == 1
    assert box.count("ID：A001") == 1
    assert tsv.index("A001") < tsv.index("A010")
    assert box.index("ID：A001") < box.index("ID：A010")


class GuiReferenceIdReportTest(GuiTestCase):
    def test_gui_id_export_uses_shared_sorted_unique_unit_view(self) -> None:
        # Given: the GUI map contains reversed and duplicate unit IDs.
        output = Path(self.create_temp_dir()) / "ids"
        output.mkdir()
        md = MapData(path="x.w3x", name="GUI ID图")
        md.objects = {
            "单位": [
                game_object(
                    "H010",
                    "后",
                    {"display:propernames": "称谓乙", "display:description": "说明乙"},
                ),
                game_object(
                    "H001",
                    "前",
                    {"display:propernames": "称谓甲", "display:description": "说明甲"},
                ),
                game_object("H001", "重复"),
            ]
        }
        self.app.map_data = md

        # When: the GUI ID export runs synchronously in the test thread.
        with patch("w3xtool.gui_export_actions.tmp_extract_dir", return_value=str(output)):
            with patch("w3xtool.gui_export_actions.threading.Thread", _InlineThread):
                with patch("w3xtool.gui_export_actions.messagebox.showinfo"):
                    self.app.on_export_ids()
                    self.app.update()
        text = (output / "单位ID.txt").read_text(encoding="utf-8")

        # Then: GUI output matches the shared reference-compatible formatter.
        assert text.count("ID：H001") == 1
        assert text.index("ID：H001") < text.index("ID：H010")
        assert "描述：称谓：称谓甲\n\n说明甲" in text

    def create_temp_dir(self) -> str:
        directory = tempfile.mkdtemp(prefix="w3xray-reference-id-")
        self.addCleanup(self._remove_tree, directory)
        return directory

    def _remove_tree(self, path: str) -> None:
        shutil.rmtree(path, ignore_errors=True)


class _InlineThread:
    def __init__(self, target, daemon: bool) -> None:
        self._target = target

    def start(self) -> None:
        self._target()

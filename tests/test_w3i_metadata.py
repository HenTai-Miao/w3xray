"""W3I version boundaries, complete evidence and corrupt-table recovery."""

from __future__ import annotations

import json
import math
from pathlib import Path
import struct

import pytest

from gametool.w3i import (
    Force,
    Player,
    W3iDiagnosticCode,
    W3iInfo,
    parse_w3i,
    w3i_info_to_dict,
)


class _Document:
    def __init__(self) -> None:
        self.data = bytearray()
        self.offsets: dict[str, int] = {}

    def add(self, name: str, data: bytes) -> None:
        self.offsets[name] = len(self.data)
        self.data.extend(data)

    def integer(self, name: str, value: int) -> None:
        self.add(name, struct.pack("<i", value))

    def text(self, name: str, value: str) -> None:
        self.add(name, value.encode("utf-8") + b"\0")

    def replace(self, name: str, raw: bytes) -> bytes:
        offset = self.offsets[name]
        return bytes(self.data[:offset] + raw + self.data[offset + len(raw) :])


def _document(
    version: int,
    *,
    player_count: int = 1,
    upgrade_count: int = 1,
    columns: int = 2,
) -> _Document:
    """Independent byte fixture from the pinned War3Net binary writer layout."""
    d = _Document()
    d.integer("version", version)
    d.add("revisions", struct.pack("<ii", 37, 6060))
    if version >= 27:
        d.add("game_version", struct.pack("<4i", 1, 32, 10, 18820))
    d.text("map_name", "TRIGSTR_001")
    d.text("author", "作者\n甲")
    d.text("description", "描述\r\n完整")
    d.text("recommended", "2–8")
    d.add(
        "camera_bounds", struct.pack("<8f", -512, -256, 512, 256, -512, 256, 512, -256)
    )
    d.add("margins", struct.pack("<4i", 1, 2, 3, 4))
    d.add("dimensions", struct.pack("<2i", 64, 32))
    d.integer("flags", 0x744)
    d.add("tileset", b"L")
    d.integer("loading_background", -1)
    if version >= 39:
        d.integer("race_hud", 128)
    if version >= 23:
        d.text("loading_path", "TRIGSTR_002")
    d.text("loading_text", "TRIGSTR_002")
    d.text("loading_title", "加载标题")
    d.text("loading_subtitle", "加载副标题")
    if version >= 23:
        d.integer("dataset", 2)
        d.text("prologue_path", "UI\\Loading.mdx")
    else:
        d.integer("prologue_background", 7)
    d.text("prologue_text", "序章文本")
    d.text("prologue_title", "序章标题")
    d.text("prologue_subtitle", "序章副标题")
    if version >= 23:
        d.integer("fog_style", 1)
        d.add("fog_numbers", struct.pack("<3f", 100, 200, 0.5))
        d.add("fog_color", bytes((1, 2, 3, 4)))
        if version >= 39:
            d.add("fog_extra", struct.pack("<5fi", 10, 20, 30, 40, 0.75, 1))
        if version >= 25:
            d.add("weather", b"RAhr")
        d.text("sound", "Default")
        d.add("light", b"A")
        d.add("water", bytes((5, 6, 7, 8)))
    if version >= 28:
        d.integer("script", 1)
    if version >= 31:
        d.integer("modes", 3)
        d.integer("data_version", 1)
    if version >= 32:
        d.add("zoom", struct.pack("<2i", 1650, 2200))
    if version >= 33:
        d.integer("min_zoom", 900)
    if version >= 39:
        d.add("hd_water", struct.pack("<7i", 11, 22, 33, 44, 55, 66, 77))
        d.add("hd_color", bytes((9, 10, 11, 12)))
        d.integer("hd_reflectivity", 88)
        d.add("alpha_color", bytes((13, 14, 15, 16)))
    d.integer("players", player_count)
    for index in range(player_count):
        d.add(f"player{index}", struct.pack("<3i", index, 1, 4))
        if version >= 39:
            d.integer(f"player{index}.race_hud", 64)
        d.integer(f"player{index}.flags", 3)
        d.text(f"player{index}.name", f"玩家{index}")
        d.add(f"player{index}.position", struct.pack("<2f", 128.25, -64.5))
        d.add(f"player{index}.allies", struct.pack("<2I", 0x80000000, 2))
        if version >= 31:
            d.add(f"player{index}.enemies", struct.pack("<2I", 4, 0x80000000))
    d.integer("forces", 1)
    d.add("force", struct.pack("<2I", 0x3F, 0x80000001))
    d.text("force_name", "TRIGSTR_003")
    d.integer("upgrades", upgrade_count)
    for index in range(upgrade_count):
        d.add(
            f"upgrade{index}", struct.pack("<I4sii", 0x80000000, b"R\xff !", index, 2)
        )
    d.integer("techs", 1)
    d.add("tech0", struct.pack("<I4s", 0xFFFFFFFF, b" A  "))
    d.integer("unit_tables", 1)
    d.integer("unit_table_index", 5)
    d.text("unit_table_name", "TRIGSTR_004")
    d.integer("unit_columns", columns)
    for index in range(columns):
        d.integer(f"unit_column{index}", index % 3)
    d.integer("unit_rows", 2)
    for row, chance in enumerate((30, 70)):
        d.integer(f"unit_row{row}", chance)
        for index in range(columns):
            d.add(f"unit_row{row}.id{index}", b"hfoo" if row == 0 else b"I001")
    if version >= 24:
        d.integer("item_tables", 1)
        d.integer("item_table_index", 9)
        d.text("item_table_name", "TRIGSTR_005")
        d.integer("item_sets", 2)
        d.integer("item_set0_count", 2)
        d.add("item0", struct.pack("<i4s", 25, b"I001"))
        d.add("item1", struct.pack("<i4s", 75, b"I002"))
        d.integer("item_set1_count", 0)
    if version in (26, 27):
        d.integer("reserved", 0)
    return d


def _parsed(data: bytes | bytearray) -> W3iInfo:
    info = parse_w3i(
        bytes(data), {1: "地图名", 2: "加载正文", 3: "队伍名", 4: "单位表", 5: "物品表"}
    )
    assert info is not None
    return info


def _assert_evidence_reconstructs(info: W3iInfo, original: bytes | bytearray) -> None:
    cursor = 0
    for record in info.fields:
        assert record.offset == cursor
        assert record.raw == original[record.offset : record.end_offset]
        cursor = record.end_offset
    assert cursor == info.consumed_bytes
    assert (
        b"".join(record.raw for record in info.fields) + info.unconsumed_data
        == original
    )


@pytest.mark.parametrize("version", (18, 23, 24, 25, 26, 27, 28, 31, 32, 33, 39))
def test_verified_layouts_reach_every_table_and_reconstruct_every_byte(
    version: int,
) -> None:
    d = _document(version)
    info = _parsed(d.data)
    assert info.complete, info.parse_issue
    assert info.header_complete and info.tables_complete
    assert info.map_version == 37 and info.editor_version == 6060
    assert info.map_name == "地图名"
    assert info.description == "描述\r\n完整"
    assert info.width == 64 and info.height == 32
    assert info.game_version == ((1, 32, 10, 18820) if version >= 27 else ())
    assert info.script_type == ("Lua" if version >= 28 else "")
    assert info.game_data_set == (2 if version >= 23 else None)
    assert info.weather_id == ("RAhr" if version >= 25 else None)
    assert info.game_data_version == (1 if version >= 31 else None)
    assert info.players[0].id == 0 and info.players[0].name == "玩家0"
    assert info.players[0].start_x == 128.25
    assert info.players[0].ally_low_priority_flags == 0x80000000
    assert info.players[0].enemy_high_priority_flags == (
        0x80000000 if version >= 31 else None
    )
    assert info.forces[0].name == "队伍名" and info.forces[0].players == [1, 32]
    assert info.forces[0].share_advanced_control
    assert info.upgrades[0].object_id == "Rÿ !"
    assert info.techs[0].object_id == " A  "
    assert info.random_unit_tables[0].name == "单位表"
    assert info.random_unit_tables[0].rows[1].object_ids == ("I001", "I001")
    assert len(info.random_item_tables) == (1 if version >= 24 else 0)
    if version >= 24:
        assert info.random_item_tables[0].sets[0].items[1].chance == 75
        assert info.random_item_tables[0].sets[1].complete
    if version >= 32:
        assert (info.default_camera_zoom, info.max_camera_zoom) == (1650, 2200)
    if version >= 33:
        assert info.min_camera_zoom == 900
    if version == 39:
        assert info.race_hud == 128 and info.players[0].race_hud == 64
        assert info.fog_max_opacity == 0.75
        assert info.hd_water_wave_normal_strength == 77
        assert info.hd_water_envmap_reflectivity == 88
        assert info.alpha_tile_minimap_color_bgra == (13, 14, 15, 16)
    _assert_evidence_reconstructs(info, d.data)


def test_display_wts_does_not_rewrite_original_cells_or_paths() -> None:
    info = _parsed(_document(31).data)
    assert info.loading_screen_text == "加载正文"
    assert info.loading_screen_path == "TRIGSTR_002"
    name = next(record for record in info.fields if record.name == "map_name")
    assert name.value == "TRIGSTR_001" and name.raw == b"TRIGSTR_001\0"


@pytest.mark.parametrize("version", (18, 23, 27, 31, 39))
def test_every_truncated_boundary_retains_confirmed_bytes_and_reports_incomplete(
    version: int,
) -> None:
    data = bytes(_document(version).data)
    for length in range(4, len(data)):
        prefix = data[:length]
        info = _parsed(prefix)
        assert not info.complete, (version, length)
        assert info.diagnostics and info.parse_issue
        _assert_evidence_reconstructs(info, prefix)


@pytest.mark.parametrize("value", (-1, 2, 2147483647))
def test_unknown_script_is_not_jass_and_keeps_encoded_value(value: int) -> None:
    d = _document(31)
    info = _parsed(d.replace("script", struct.pack("<i", value)))
    assert info.script_type == "unknown" and info.script_language_raw == value
    assert info.tables_complete and not info.complete
    diagnostic = next(
        item for item in info.diagnostics if item.field == "script_language_raw"
    )
    assert diagnostic.code == W3iDiagnosticCode.UNKNOWN_VALUE
    assert diagnostic.offset == d.offsets["script"]


def test_truncated_language_never_looks_like_an_old_undeclared_format() -> None:
    d = _document(31)
    for missing in range(4):
        info = _parsed(d.data[: d.offsets["script"] + missing])
        assert info.script_type == "unknown" and info.script_language_raw is None
        assert info.map_name == "地图名" and not info.header_complete
    info = _parsed(d.replace("script", struct.pack("<i", 0)))
    assert info.script_type == "JASS"


def test_unknown_data_modes_and_flags_remain_raw_without_choosing_a_default() -> None:
    d = _document(31)
    data = bytearray(d.replace("dataset", struct.pack("<i", 99)))
    struct.pack_into("<i", data, d.offsets["data_version"], -77)
    struct.pack_into("<I", data, d.offsets["flags"], 0x80000004)
    struct.pack_into("<I", data, d.offsets["modes"], 0x40000003)
    info = _parsed(data)
    assert (info.game_data_set, info.game_data_version, info.flags) == (
        99,
        -77,
        0x80000004,
    )
    assert info.supported_modes == 0x40000003 and info.melee
    assert len(info.diagnostics) == 4 and info.tables_complete
    _assert_evidence_reconstructs(info, data)


def test_counts_are_bounded_by_bytes_without_player_column_or_255_sentinel_caps() -> (
    None
):
    d = _document(39, player_count=129, upgrade_count=255, columns=257)
    info = _parsed(d.data)
    assert info.complete, info.parse_issue
    assert len(info.players) == 129 and len(info.upgrades) == 255
    assert len(info.random_unit_tables[0].column_types) == 257
    assert len(info.random_unit_tables[0].rows[1].object_ids) == 257
    _assert_evidence_reconstructs(info, d.data)


def test_impossible_count_retains_confirmed_record_then_stops_on_byte_boundary() -> (
    None
):
    d = _document(31)
    data = d.replace("upgrades", struct.pack("<i", 2147483647))[: d.offsets["techs"]]
    info = _parsed(data)
    assert len(info.upgrades) == 1
    assert {item.code for item in info.diagnostics} == {
        W3iDiagnosticCode.INVALID_COUNT,
        W3iDiagnosticCode.TRUNCATED,
    }
    assert info.diagnostics[0].offset == d.offsets["upgrades"]
    _assert_evidence_reconstructs(info, data)


def test_negative_count_is_a_diagnostic_not_an_empty_successful_table() -> None:
    d = _document(31)
    data = d.replace("techs", struct.pack("<i", -1))
    info = _parsed(data)
    assert len(info.upgrades) == 1 and info.techs == [] and not info.tables_complete
    assert info.diagnostics[-1].code == W3iDiagnosticCode.INVALID_COUNT
    assert info.unconsumed_data == data[d.offsets["techs"] + 4 :]


def test_partial_random_tables_retain_every_complete_child_and_unfinished_evidence() -> (
    None
):
    d = _document(31)
    info = _parsed(d.data[: d.offsets["unit_row1.id1"] + 2])
    table = info.random_unit_tables[0]
    assert table.name == "单位表" and table.column_types == [0, 1]
    assert len(table.rows) == 1 and not table.complete
    assert any(item.name.endswith("rows[1].object_ids[0]") for item in info.fields)
    assert info.unconsumed_data == b"I0"
    info = _parsed(d.data[: d.offsets["item1"] + 6])
    item_table = info.random_item_tables[0]
    assert item_table.name == "物品表" and not item_table.complete
    assert len(item_table.sets[0].items) == 1 and not item_table.sets[0].complete
    assert info.unconsumed_data == b"I0"


def test_nonfinite_geometry_is_evidence_but_never_usable_coordinates() -> None:
    d = _document(39)
    data = bytearray(d.replace("camera_bounds", struct.pack("<f", math.nan)))
    struct.pack_into("<f", data, d.offsets["player0.position"], math.inf)
    struct.pack_into("<f", data, d.offsets["fog_numbers"] + 8, -math.inf)
    info = _parsed(data)
    assert info.camera_bounds == () and info.players[0].start_x is None
    assert info.players[0].start_y == -64.5 and info.fog_density is None
    assert len(info.diagnostics) == 3
    assert info.tables_complete and not info.complete
    exported = w3i_info_to_dict(info)
    serialized = json.dumps(exported, ensure_ascii=False, allow_nan=False)
    restored = json.loads(serialized)
    raw_fields = {item["name"]: item for item in restored["fields"]}
    assert raw_fields["camera_bounds"]["value"][0] == {"non_finite": "nan"}
    assert raw_fields["players[0].start_x"]["value"] == {"non_finite": "+infinity"}
    assert raw_fields["fog_density"]["value"] == {"non_finite": "-infinity"}
    assert (
        bytes.fromhex(raw_fields["camera_bounds"]["raw"]["data"])
        == data[d.offsets["camera_bounds"] : d.offsets["camera_bounds"] + 32]
    )
    _assert_evidence_reconstructs(info, data)


def test_nonpositive_dimensions_are_not_published_as_a_usable_size() -> None:
    d = _document(31)
    info = _parsed(d.replace("dimensions", struct.pack("<2i", -1, 0)))
    assert info.width == info.height == 0
    assert [item.field for item in info.diagnostics] == ["width", "height"]
    assert next(item.value for item in info.fields if item.name == "width") == -1


def test_unknown_version_and_trailing_bytes_are_retained_without_layout_guessing() -> (
    None
):
    d = _document(31)
    data = d.replace("version", struct.pack("<i", 34))
    info = _parsed(data)
    assert info.version == 34 and info.script_type == "unknown"
    assert info.map_name == "" and info.unconsumed_data == data[4:]
    assert info.diagnostics[0].code == W3iDiagnosticCode.UNSUPPORTED_VERSION
    data = bytes(d.data) + b"unknown\x00tail\xff"
    info = _parsed(data)
    assert info.tables_complete and not info.complete
    assert info.unconsumed_data == b"unknown\x00tail\xff"
    assert info.diagnostics[0].code == W3iDiagnosticCode.TRAILING_DATA
    _assert_evidence_reconstructs(info, data)


def test_single_ff_is_explicit_omission_not_proof_of_empty_tables() -> None:
    d = _document(31)
    info = _parsed(d.data[: d.offsets["upgrades"]] + b"\xff")
    assert info.complete and info.optional_data_skipped and not info.tables_complete
    assert not any(record.name == "upgrades.count" for record in info.fields)


def test_json_retains_all_model_fields_nested_records_and_original_bytes() -> None:
    data = bytes(_document(39).data)
    info = _parsed(data)
    restored = json.loads(json.dumps(w3i_info_to_dict(info), allow_nan=False))
    assert set(info.__dict__) <= set(restored)
    assert (
        restored["random_item_tables"][0]["sets"][0]["items"][1]["object_id"] == "I002"
    )
    assert (
        b"".join(bytes.fromhex(item["raw"]["data"]) for item in restored["fields"])
        == data
    )
    assert restored["unconsumed_data"] == {"encoding": "hex", "data": ""}


@pytest.mark.parametrize("name", ("w3i_v18.w3i", "w3i_v25.w3i"))
def test_existing_real_fixtures_are_read_only_and_byte_complete(name: str) -> None:
    path = Path(__file__).parent / "fixtures" / name
    before = path.read_bytes()
    info = _parsed(before)
    assert info.complete and info.header_complete and info.tables_complete
    assert info.players and info.forces and info.consumed_bytes == len(before)
    _assert_evidence_reconstructs(info, before)
    assert path.read_bytes() == before


def test_existing_positional_model_constructors_still_work() -> None:
    player = Player(1, 2, 3, 1, "玩家", 10.0, 20.0)
    force = Force("队伍", True, False, True, False, [1, 2])
    info = W3iInfo(25, "地图", "作者", "描述", "人数", 64, 32, "JASS")
    assert player.type_name == "电脑" and player.race_name == "不死"
    assert force.players == [1, 2] and force.share_vision
    assert info.script_type == "JASS" and info.width == 64


@pytest.mark.parametrize(
    ("name_bytes", "expected", "lossy"),
    (
        (b"\x81", "\ufffd", True),
        ("地图甲".encode("gbk"), "地图甲", False),
        ("地图乙\ufffd".encode("utf-8"), "地图乙\ufffd", False),
    ),
)
def test_lossy_strings_are_diagnosed_without_rejecting_valid_legacy_or_replacement_text(
    name_bytes: bytes,
    expected: str,
    lossy: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gametool import w3i_reader

    monkeypatch.setattr(w3i_reader, "default_legacy_codecs", lambda: ("gbk", "gb18030"))
    d = _document(31)
    data = (
        bytes(d.data[: d.offsets["map_name"]])
        + name_bytes
        + b"\0"
        + bytes(d.data[d.offsets["author"] :])
    )
    info = _parsed(data)
    assert info.map_name == expected
    assert info.complete is not lossy and info.tables_complete
    issues = [
        item for item in info.diagnostics if item.code == W3iDiagnosticCode.LOSSY_STRING
    ]
    assert len(issues) == int(lossy)
    if lossy:
        assert (
            issues[0].field == "map_name" and issues[0].offset == d.offsets["map_name"]
        )
    original = next(item for item in info.fields if item.name == "map_name")
    assert original.raw == name_bytes + b"\0"
    _assert_evidence_reconstructs(info, data)

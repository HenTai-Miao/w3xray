"""Live names and icons consume complete cells through one shared TSV boundary."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gametool.batch_tsv import format_tsv_rows
from gametool.knowledge_object_exports import format_object_fields, write_object_ids
from gametool.live_inventory import _icon_paths_from_pack, load_names
from gametool.map_data import GameObject, MapData


def _export_objects(pack: Path, objects: list[GameObject]) -> None:
    md = MapData("synthetic.w3x", "名称往返")
    for obj in objects:
        md.objects.setdefault(obj.category, []).append(obj)
    assert write_object_ids(md, str(pack / "对象ID")) == len(md.objects)


def _object(category: str, code: str, name: str) -> GameObject:
    return GameObject(
        category, "w3t" if category == "物品" else "w3u", code, code, name, True
    )


@pytest.mark.parametrize(
    "name",
    (
        '名字"引号',
        "名称\t制表符",
        "首行\n第二行",
        "首行\r\n第二行",
        '组合"\t首行\r\n第二行\n末尾\ufeffBOM',
    ),
)
def test_live_names_round_trip_complete_csv_cells(tmp_path: Path, name: str) -> None:
    _export_objects(tmp_path, [_object("物品", "I~01", name)])

    assert load_names(tmp_path)[b"I~01"] == name


@pytest.mark.parametrize("code", ("-123", "+123", "@123", "=123", "'=12"))
def test_live_names_keep_formula_and_native_quote_ids(
    tmp_path: Path, code: str
) -> None:
    _export_objects(tmp_path, [_object("物品", code, "=完整名称")])

    assert load_names(tmp_path)[code.encode()] == "=完整名称"


def test_live_names_use_native_latin1_four_byte_keys(tmp_path: Path) -> None:
    _export_objects(tmp_path, [_object("物品", "i!é?", "原生四字节物品")])

    names = load_names(tmp_path)

    assert names.get(b"i!\xe9?") == "原生四字节物品"
    assert b"i!\xc3\xa9?" not in names


def test_live_names_decode_a_literal_safety_prefix_only_once(tmp_path: Path) -> None:
    name = "'\u2060保留原始前缀\t完整名称"
    _export_objects(tmp_path, [_object("物品", "I~01", name)])

    assert load_names(tmp_path)[b"I~01"] == name


@pytest.mark.parametrize(
    "category, code",
    (("物品", "I~01"), ("单位", "h~01"), ("英雄", "H~01")),
)
def test_live_names_keep_categories_custom_names_and_color_cleanup(
    tmp_path: Path, category: str, code: str
) -> None:
    objects = [
        _object("物品", "I~01", "|cffff0000物品名|r"),
        _object("单位", "h~01", "|cffff0000单位名|r"),
        _object("英雄", "H~01", "|cffff0000英雄名|r"),
    ]
    _export_objects(tmp_path, objects)

    names = load_names(tmp_path, category)

    assert names[code.encode()] == category + "名"
    assert not any(
        obj.obj_id.encode() in names for obj in objects if obj.category != category
    )
    assert (b"Hpal" in names) == (category != "物品")


def test_live_names_keep_first_headerless_record_and_legacy_quote_id(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "对象ID"
    directory.mkdir()
    (directory / "物品.tsv").write_text(
        format_tsv_rows(
            [
                ("物品", "'-123", "1", "'-123", "首条\t名称", "是", ""),
                ("物品", "I~02", "2", "I~02", "第二条\n名称", "是", ""),
            ]
        ),
        encoding="utf-8",
        newline="",
    )

    names = load_names(tmp_path)

    assert names[b"-123"] == "首条\t名称"
    assert names[b"I~02"] == "第二条\n名称"


def test_live_names_resolve_declared_columns_after_one_file_bom(tmp_path: Path) -> None:
    directory = tmp_path / "对象ID"
    directory.mkdir()
    (directory / "物品.tsv").write_bytes(
        b"\xef\xbb\xbf"
        + format_tsv_rows(
            [
                ("名称", "ID", "分类"),
                ("\ufeff名称\t第二段", "I~01", "物品"),
            ]
        ).encode("utf-8")
    )

    assert load_names(tmp_path)[b"I~01"] == "\ufeff名称\t第二段"


def test_live_names_keep_a_complete_large_name(tmp_path: Path) -> None:
    name = "完整" * 70000 + "\t尾部"
    _export_objects(tmp_path, [_object("物品", "I~01", name)])

    assert load_names(tmp_path)[b"I~01"] == name


def test_live_names_refresh_same_size_same_mtime_source_bytes(tmp_path: Path) -> None:
    _export_objects(tmp_path, [_object("物品", "I~01", "原始名称")])
    path = tmp_path / "对象ID" / "物品.tsv"
    before = path.stat()
    assert load_names(tmp_path)[b"I~01"] == "原始名称"
    _export_objects(tmp_path, [_object("物品", "I~01", "更新名称")])
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    assert load_names(tmp_path)[b"I~01"] == "更新名称"


@pytest.mark.parametrize(
    "name", ('名字"引号', "名称\t制表符", "首行\n第二行", "首行\r\n第二行")
)
def test_live_icons_round_trip_complete_exported_name_cells(
    tmp_path: Path, name: str
) -> None:
    item = _object("物品", "I~01", name)
    item.field_values = {"display:icon": "CommandButtons\\BTNcustom.blp"}
    item.field_sources = {"display:icon": "war3map.w3t"}
    md = MapData("synthetic.w3x", "图标往返")
    md.objects = {"物品": [item]}
    (tmp_path / "对象字段.tsv").write_text(
        format_object_fields(md), encoding="utf-8", newline=""
    )

    assert _icon_paths_from_pack(tmp_path) == {"I~01": "CommandButtons/BTNcustom.blp"}


def _write_field_rows(pack: Path, rows: list[tuple[str, ...]]) -> None:
    (pack / "对象字段.tsv").write_text(
        format_tsv_rows(
            [("分类", "ID", "名称", "字段键", "字段名", "值", "来源"), *rows]
        ),
        encoding="utf-8",
        newline="",
    )


def test_live_icons_keep_decoded_identities_categories_and_case(tmp_path: Path) -> None:
    codes = ("-123", "+123", "@123", "=123", "'=12", "I~01", "i~01")
    _write_field_rows(
        tmp_path,
        [
            (
                "物品",
                code,
                "物品名称",
                "display:icon",
                "图标",
                "CommandButtons\\BTNcustom.blp",
                "war3map.w3t",
            )
            for code in codes
        ]
        + [
            (
                "单位",
                "h~01",
                "单位名称",
                "display:icon",
                "图标",
                "CommandButtons\\BTNunit.blp",
                "war3map.w3u",
            )
        ],
    )

    assert _icon_paths_from_pack(tmp_path) == {
        code: "CommandButtons/BTNcustom.blp" for code in codes
    }


def test_live_icons_keep_latin1_identity_keys_as_strings(tmp_path: Path) -> None:
    _write_field_rows(
        tmp_path,
        [
            (
                "物品",
                "i!é?",
                "原生四字节物品",
                "display:icon",
                "图标",
                "CommandButtons\\BTNlatin1.blp",
                "war3map.w3t",
            )
        ],
    )

    assert _icon_paths_from_pack(tmp_path) == {"i!é?": "CommandButtons/BTNlatin1.blp"}


@pytest.mark.parametrize(
    "path, expected",
    (
        ("=CommandButtons\\BTNformula.blp", "=CommandButtons/BTNformula.blp"),
        (
            "'\u2060CommandButtons\\BTNliteral.blp",
            "'\u2060CommandButtons/BTNliteral.blp",
        ),
        (
            'CommandButtons\\目录\t"quoted"\r\nBTN尾\ufeff.blp',
            'CommandButtons/目录\t"quoted"\r\nBTN尾\ufeff.blp',
        ),
    ),
)
def test_live_icons_decode_each_complete_path_only_once(
    tmp_path: Path, path: str, expected: str
) -> None:
    _write_field_rows(
        tmp_path,
        [("物品", "I~01", "物品", "display:icon", "图标", path, "war3map.w3t")],
    )

    assert _icon_paths_from_pack(tmp_path) == {"I~01": expected}


@pytest.mark.parametrize("custom_first", (False, True))
def test_live_icons_keep_custom_precedence_with_complete_csv_rows(
    tmp_path: Path, custom_first: bool
) -> None:
    custom = (
        "物品",
        "I~01",
        "名称\t第二段",
        "display:icon",
        "图标",
        "CommandButtons\\BTNcustom.blp",
        "war3map.w3t",
    )
    inherited = (
        "物品",
        "I~01",
        "名称\t第二段",
        "base:art",
        "art",
        "CommandButtons\\BTNbase.blp",
        "base:item",
    )
    _write_field_rows(
        tmp_path, [custom, inherited] if custom_first else [inherited, custom]
    )

    assert _icon_paths_from_pack(tmp_path) == {"I~01": "CommandButtons/BTNcustom.blp"}

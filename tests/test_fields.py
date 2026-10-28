"""字段标签：手工精选优先、MetaData.slk 全量生成兜底、未知码原样返回。"""

import csv
import io
import json
from pathlib import Path
import struct
import unittest

import pytest

from gametool.fields import label_for, field_type, FIELD_LABELS
from gametool.knowledge_object_exports import (
    format_object_fields as export_object_fields,
    write_object_ids,
)
from gametool.map_data import MapData
from gametool.object_detail_presentation import format_object_fields
from gametool.object_pipeline import load_object_pipeline
from gametool.pack_query_objects import OBJECT_TABLES
from gametool.reference_cli import run_reference_cli


class _FieldArchive:
    """Encoded map object files exercise the actual parser and materializer."""

    path = "field-roles.w3x"
    _data = b""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def has_file(self, name: str) -> bool:
        return name in self.files

    def read_file(self, name: str) -> bytes:
        return self.files[name]

    def list_files(self) -> list[str]:
        return list(self.files)

    def close(self) -> None:
        pass


def _object_bytes(
    code: str, ext: str, fields: tuple[tuple[str, int | float | str], ...]
) -> bytes:
    mods: list[bytes] = []
    for key, value in fields:
        if isinstance(value, str):
            kind, encoded = 3, value.encode("utf-8") + b"\0"
        elif isinstance(value, int):
            kind, encoded = 0, struct.pack("<i", value)
        else:
            kind, encoded = 2, struct.pack("<f", value)
        mods.append(
            key.encode("ascii")
            + struct.pack("<i", kind)
            + (struct.pack("<ii", 0, 0) if ext in {"w3a", "w3q"} else b"")
            + encoded
            + b"\0" * 4
        )
    return (
        struct.pack("<iii", 2, 0, 1)
        + code.encode("ascii") * 2
        + struct.pack("<i", len(fields))
        + b"".join(mods)
    )


def _semantic_map() -> MapData:
    definitions: tuple[
        tuple[str, str, tuple[tuple[str, int | float | str], ...]], ...
    ] = (
        (
            "U001",
            "w3u",
            (
                ("ussc", 1.5),
                ("uhos", 1),
                ("ufoo", 3),
                ("ufma", 8),
                ("ua1d", 2),
                ("ua1c", 1.25),
                ("udp1", 0.375),
                ("uspe", 1),
                ("usin", 600),
                ("upgr", "R001"),
                ("ucbs", 0.5),
            ),
        ),
        (
            "I001",
            "w3t",
            (
                ("iclb", 31),
                ("idrp", 0),
                ("ilvo", 7),
                ("ifil", 'Models\\quoted\tpart\n"x".mdx'),
            ),
        ),
        ("A001", "w3a", (("arut", "学习扩展全文"), ("acas", 0.75))),
        ("R001", "w3q", (("gtib", 40), ("gtim", 7), ("glmb", 99), ("glmm", 5))),
    )
    archive = _FieldArchive(
        {
            f"war3map.{ext}": _object_bytes(code, ext, values)
            for code, ext, values in definitions
        }
    )
    md = MapData(path=archive.path, name="独立字段角色")
    load_object_pipeline(md, archive, {}, base_objects={})
    return md


class TestFieldLabels(unittest.TestCase):
    def test_curated_label_takes_precedence(self):
        # "unam" 在精选表里是「名称」，全量表里是「名字」——精选优先
        self.assertEqual(FIELD_LABELS["unam"], "名称")
        self.assertEqual(label_for("unam"), "名称")

    def test_generated_label_fallback(self):
        # 精选表没有的字段码应回退到全量生成标签（不再显示原始 4cc）
        self.assertNotIn("uarm", FIELD_LABELS)
        self.assertEqual(label_for("uarm"), "装甲类型")

    def test_unknown_code_returns_itself(self):
        self.assertEqual(label_for("zzzz"), "zzzz")

    def test_field_type_lookup(self):
        self.assertEqual(field_type("iabi"), "abilityList")
        self.assertEqual(field_type("unam"), "string")
        self.assertEqual(field_type("zzzz"), "")

    def test_is_concat_type(self):
        from gametool.fields import is_concat_type

        self.assertTrue(is_concat_type("iabi"))  # abilityList
        self.assertFalse(is_concat_type("unam"))  # string


class TestExpandCodes(unittest.TestCase):
    def test_resolves_known_codes_keeps_unknown(self):
        from gametool.api import _expand_codes

        names = {"Hpal": "圣骑士", "AHbz": "暴风雪"}
        out = _expand_codes("Hpal,AHbz,xxyy", names)
        self.assertEqual(out, "圣骑士(Hpal), 暴风雪(AHbz), xxyy")

    def test_non_list_value_unchanged(self):
        from gametool.api import _expand_codes

        self.assertEqual(_expand_codes("单个值", {}), "单个值")


def test_encoded_field_roles_survive_materialization_detail_and_export() -> None:
    md = _semantic_map()
    exported = list(
        csv.DictReader(io.StringIO(export_object_fields(md)), delimiter="\t")
    )
    rows = {(row["ID"], row["字段键"]): row for row in exported}
    # Distinct encoded roles must remain distinct all the way to player-facing
    # evidence. In particular times must not become counts or resource costs.
    expected = {
        ("U001", "ussc"): ("选择圈缩放", "1.5"),
        ("U001", "uhos"): ("可作为中立敌对显示", "1"),
        ("U001", "ufoo"): ("占用人口", "3"),
        ("U001", "ua1d"): ("攻击伤害骰子数", "2"),
        ("U001", "ua1c"): ("攻击间隔", "1.25"),
        ("U001", "udp1"): ("攻击伤害前摇", "0.375"),
        ("U001", "uspe"): ("特殊分类", "1"),
        ("U001", "usin"): ("视野(夜晚)", "600"),
        ("U001", "upgr"): ("使用的科技", "R001"),
        ("U001", "ucbs"): ("施法后摇", "0.5"),
        ("I001", "iclb"): ("染色(蓝色)", "31"),
        ("I001", "ilvo"): ("等级(旧版)", "7"),
        ("I001", "ifil"): ("模型", 'Models\\quoted\tpart\n"x".mdx'),
        ("A001", "arut"): ("学习扩展提示", "学习扩展全文"),
        ("A001", "acas"): ("施法时间", "0.75"),
        ("R001", "gtib"): ("基础时间", "40"),
        ("R001", "gtim"): ("时间增量", "7"),
    }
    assert len(rows) == len(exported) == 21
    for (code, key), (label, value) in expected.items():
        row = rows[(code, key)]
        assert (row["字段名"], row["值"]) == (label, value)
        obj = md.obj_index[code]
        assert row["来源"] == f"war3map.{obj.ext}"
        assert label in format_object_fields(obj, detailed=True)
    assert rows[("U001", "ufma")]["值"] == "8"
    assert rows[("I001", "idrp")]["值"] == "0"
    assert rows[("R001", "glmb")]["值"] == "99"
    assert rows[("R001", "glmm")]["值"] == "5"


def test_reference_cli_retains_corrected_roles_and_raw_export_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    md = _semantic_map()
    pack = tmp_path / "pack"
    pack.mkdir()
    field_path = pack / "对象字段.tsv"
    payload = export_object_fields(md).encode("utf-8")
    field_path.write_bytes(payload)
    for category in OBJECT_TABLES:
        md.objects.setdefault(category, [])
    write_object_ids(md, str(pack / "对象ID"))
    assert (
        run_reference_cli(
            [
                "iclb || ifil || gtib || gtim",
                "--kind",
                "fields",
                "--pack",
                str(pack),
                "--source",
                str(field_path),
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    rows = {row["id"]: row for row in report["records"]}
    assert set(rows) == {"iclb", "ifil", "gtib", "gtim"}
    color = rows["iclb"]
    assert color["label"] == "染色(蓝色)"
    assert "染色 3 (蓝色)" in color["aliases"]
    assert dict(color["details"])["字段类型"] == "int"
    assert dict(color["details"])["maxVal"] == "255"
    assert color["values"][0]["value"] == "31"
    assert color["values"][0]["provenance"] == "war3map.w3t"
    assert rows["ifil"]["label"] == "模型"
    assert rows["ifil"]["values"][0]["value"] == 'Models\\quoted\tpart\n"x".mdx'
    assert (rows["gtib"]["label"], rows["gtim"]["label"]) == ("基础时间", "时间增量")
    assert [rows[key]["values"][0]["value"] for key in ("gtib", "gtim")] == ["40", "7"]
    assert field_path.read_bytes() == payload


if __name__ == "__main__":
    unittest.main()

"""Independent counterexamples across real SLK loading, exports and queries."""

from __future__ import annotations

import csv
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import struct

import pytest

from gametool import pack_query_cli as queries
from gametool.knowledge_object_exports import (
    format_object_fields,
    write_box_ids,
    write_object_ids,
)
from gametool.load_context import MapLoadContext
from gametool.map_data import MapData
from gametool.map_loader import _load_map_impl
from gametool.object_pipeline import load_object_pipeline
from gametool.pack_query_object_details import load_object_records
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_tech_details import _scalar
from gametool.slk import parse_slk
from gametool.slk_evidence import parse_slk_evidence
from gametool.slkmeta import build_slk_inventory
from tests.test_slk_evidence_names import _Archive


def _table(
    field: str = "Name",
    value: str = '"alpha"',
    *,
    header: str = "unitID",
    code: str = "hfoo",
    extra: str = "",
    producer: str = "P",
) -> bytes:
    return (
        f'ID;{producer}\nC;X1;Y1;K"{header}"\nC;X2;Y1;K"{field}"\n'
        f'C;X1;Y2;K"{code}"\nC;X2;Y2;K{value}\n{extra}E\n'
    ).encode()


def _pack(md: MapData, root: Path) -> Path:
    write_object_ids(md, str(root / "对象ID"))
    write_box_ids(md, str(root / "box"))
    (root / "对象字段.tsv").write_text(format_object_fields(md), encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("producer", "raw", "expected"),
    [
        ("PCALCOOO32", '"a"b"', 'a"b'),
        ("PCALCOOO32", '"a""b"', 'a""b'),
        ("PCALCOOO32", '"a";;b"', 'a";b'),
        ("PWXL;N;E", '"a"b"', 'a"b'),
        ("PWXL;N;E", '"a""b"', 'a""b'),
        ("PSCAlC3", '"a""b"', 'a""b'),
        ("PSCALC3", '"a""b"', 'a"b'),
        ("PSCALC3", '"a;;b"', "a;;b"),
    ],
)
def test_producer_declared_sylk_quote_dialects(
    producer: str, raw: str, expected: str
) -> None:
    payload = _table(value=raw, producer=producer)
    assert parse_slk(payload.decode())["hfoo"]["Name"] == expected
    md = _load_map_impl(
        _Archive({"UnitData.slk": payload}), "quote.w3x", 0, None, MapLoadContext()
    )
    assert md.obj_identity_index[("单位", "hfoo")].name == expected


def test_actual_loader_conflicting_names_never_export_base_name(tmp_path: Path) -> None:
    archive = _Archive({"UnitData.slk": _table(), "UnitUI.slk": _table(value='"beta"')})
    md = _load_map_impl(archive, "conflict.w3x", 0, None, MapLoadContext())
    obj = md.obj_identity_index[("单位", "hfoo")]
    assert obj.name == "hfoo"
    assert "display:name" not in obj.field_values
    assert {row.value for row in obj.field_blockers} == {"alpha", "beta"}
    pack = _pack(md, tmp_path / "pack")
    with (pack / "对象ID/单位.tsv").open(encoding="utf-8", newline="") as stream:
        row = next(
            row for row in csv.reader(stream, delimiter="\t") if row[1] == "hfoo"
        )
    assert row[4] == "hfoo"
    assert "名字：hfoo\n" in (pack / "box/单位ID.txt").read_text(encoding="utf-8")
    fields = (pack / "对象字段.tsv").read_text(encoding="utf-8")
    assert (
        "证据状态" in fields
        and "alpha" in fields
        and "beta" in fields
        and "conflict" in fields
    )


def test_unknown_formula_blocks_old_cell_and_sibling_and_retains_diagnostics() -> None:
    payload = _table(extra="C;X2;Y2;E1+2\n")
    evidence = parse_slk_evidence(payload.decode())
    assert evidence.as_dict() == {"hfoo": {}}
    assert ("hfoo", "Name") in evidence.blocked_fields
    opaque = [evidence.cells[index] for index in evidence.opaque]
    assert any(
        cell.x == 2 and cell.y == 2 and cell.value_kind == "opaque" for cell in opaque
    )
    md = MapData("unknown.w3x", "unknown")
    load_object_pipeline(
        md,
        _Archive({"UnitData.slk": payload, "UnitUI.slk": _table(value='"sibling"')}),
        {},
        base_objects={},
    )
    assert md.obj_index["hfoo"].name == "hfoo"
    assert md.obj_index["hfoo"].field_blockers
    assert any("E1+2" in item.message for item in md.diagnostics)


def test_case_alias_conflict_does_not_select_a_canonical_winner() -> None:
    payload = _table(extra='C;X3;Y1;K"name"\nC;X3;Y2;K"beta"\n')
    md = MapData("alias.w3x", "alias")
    load_object_pipeline(md, _Archive({"UnitData.slk": payload}), {}, base_objects={})
    assert md.obj_index["hfoo"].name == "hfoo"
    assert "display:name" not in md.obj_index["hfoo"].field_values
    assert any("semantic_field_conflict" in item.message for item in md.diagnostics)


def test_opaque_only_source_stays_in_inventory() -> None:
    payload = _table().replace(
        b'C;X1;Y2;K"hfoo"\nC;X2;Y2;K"alpha"\n', b"C;X2;Y2;E1+2\n"
    )
    report = build_slk_inventory({"formula.slk": payload})
    assert len(report.files) == 1
    assert report.files[0].rows == 1 and report.files[0].evidence is not None


def test_confirmed_slk_fields_keep_actual_source_encoded_cell_and_type() -> None:
    md = MapData("source.w3x", "source")
    load_object_pipeline(
        md,
        _Archive({"Units\\UnitData.slk": _table(value='"a;;b"')}),
        {},
        base_objects={},
    )
    obj = md.obj_index["hfoo"]
    row = next(row for row in obj.field_evidence if row.key == "Name")
    assert row.source == "Units\\UnitData.slk" and row.value_type == "string"
    encoded = json.loads(row.encoded_evidence)
    assert encoded["cell"]["raw"] == 'K"a;;b"'
    assert encoded["cell"]["value_kind"] == "quoted" and row.value == "a;b"


def test_higher_priority_name_evidence_releases_slk_blocker() -> None:
    value = b"unam" + struct.pack("<i", 3) + b"resolved\0" + struct.pack("<I", 0)
    binary = (
        struct.pack("<ii", 2, 0)
        + struct.pack("<i", 1)
        + b"hfoohfoo"
        + struct.pack("<i", 1)
        + value
    )
    md = MapData("higher.w3x", "higher")
    archive = _Archive(
        {
            "UnitData.slk": _table(),
            "UnitUI.slk": _table(value='"beta"'),
            "war3map.w3u": binary,
        }
    )
    load_object_pipeline(md, archive, {}, base_objects={})
    assert md.obj_index["hfoo"].name == "resolved"
    assert not md.obj_index["hfoo"].field_blockers
    assert {row.value for row in md.obj_index["hfoo"].field_evidence} >= {
        "alpha",
        "beta",
        "resolved",
    }


@pytest.mark.parametrize(
    ("field", "first", "second", "command"),
    [("goldcost", "100", "200", "price"), ("iabi", '"A001"', '"A002"', "item")],
)
def test_item_unknown_fields_survive_export_and_query_without_base_fallback(
    tmp_path: Path, field: str, first: str, second: str, command: str
) -> None:
    payload = _table(
        field, first, header="itemID", code="ratf", extra=f"C;X2;Y2;K{second}\n"
    )
    md = MapData("item.w3x", "item")
    load_object_pipeline(
        md,
        _Archive({"ItemData.slk": payload}),
        {},
        base_objects={"ratf": ("物品", (("金币", "9"), ("技能", "A000")))},
    )
    pack = _pack(md, tmp_path / "pack")
    result = queries.execute_pack_query(PackQueryCliOptions(str(pack), command, "ratf"))
    rendered = result.render()
    assert "未确认" in rendered
    if command == "price":
        assert (
            "金币: 9" not in rendered
            and "金币: 100" not in rendered
            and "金币: 200" not in rendered
        )
    else:
        assert "关联技能 [A000]" not in rendered and "关联技能 [A001]" not in rendered


def test_unknown_stock_is_not_empty_and_does_not_restore_inherited_goods(
    tmp_path: Path,
) -> None:
    payload = _table("Sellitems", '"I001"', extra='C;X2;Y2;K"I002"\n')
    md = MapData("shop.w3x", "shop")
    load_object_pipeline(
        md,
        _Archive({"UnitData.slk": payload}),
        {},
        base_objects={"hfoo": ("单位", (("Sellitems", "I000"),))},
    )
    pack = _pack(md, tmp_path / "pack")
    assert queries.load_shop_stocks(pack) == []
    rendered = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "shop", "hfoo")
    ).render()
    assert "货架字段未确认" in rendered and "货架字段显式为空" not in rendered
    assert "I000" not in rendered


@pytest.mark.parametrize(
    ("field", "raw", "command", "category", "filename", "header"),
    [
        ("goldcost", "100", "price", "物品", "ItemData.slk", "itemID"),
        ("iabi", '"A001"', "item", "物品", "ItemData.slk", "itemID"),
        ("Sellitems", '"I001"', "shop", "单位", "UnitData.slk", "unitID"),
    ],
)
def test_cached_literal_with_unknown_formula_is_never_a_confirmed_query_value(
    tmp_path: Path,
    field: str,
    raw: str,
    command: str,
    category: str,
    filename: str,
    header: str,
) -> None:
    payload = _table(field, raw, header=header, code="hfoo").replace(
        f"K{raw}\n".encode(), f"K{raw};E1+2\n".encode()
    )
    md = MapData("formula.w3x", "formula")
    load_object_pipeline(md, _Archive({filename: payload}), {}, base_objects={})
    assert md.obj_identity_index[(category, "hfoo")].field_blockers
    pack = _pack(md, tmp_path / "pack")
    rendered = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, "hfoo")
    ).render()
    assert "未确认" in rendered
    assert "金币: 100" not in rendered and "关联技能 [A001]" not in rendered
    if command == "shop":
        assert queries.load_shop_stocks(pack) == []


def test_higher_priority_gold_releases_blocker_through_export_and_price_query(
    tmp_path: Path,
) -> None:
    slk = _table(
        "goldcost", "100", header="itemID", code="ratf", extra="C;X2;Y2;K200\n"
    )
    value = b"igol" + struct.pack("<i", 3) + b"300\0" + struct.pack("<I", 0)
    binary = (
        struct.pack("<ii", 2, 0)
        + struct.pack("<i", 1)
        + b"ratfratf"
        + struct.pack("<i", 1)
        + value
    )
    md = MapData("gold.w3x", "gold")
    load_object_pipeline(
        md, _Archive({"ItemData.slk": slk, "war3map.w3t": binary}), {}, base_objects={}
    )
    assert not md.obj_index["ratf"].field_blockers
    pack = _pack(md, tmp_path / "pack")
    rendered = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "price", "ratf")
    ).render()
    assert "金币: 300" in rendered
    assert "overridden" in (pack / "对象字段.tsv").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("native", "canonical"),
    [
        ("goldbase", "gglb"),
        ("goldmod", "gglm"),
        ("lumberbase", "glmb"),
        ("lumbermod", "glmm"),
        ("maxlevel", "glvl"),
    ],
)
@pytest.mark.parametrize(
    "kind", ["conflict", "cached_formula", "no_k_formula", "binary_release"]
)
def test_native_tech_scalar_state_survives_real_loading_exports_and_query(
    tmp_path: Path, native: str, canonical: str, kind: str
) -> None:
    extra = (
        "C;X2;Y2;E1+2\n"
        if kind == "no_k_formula"
        else "C;X2;Y2;K200\n"
        if kind in {"conflict", "binary_release"}
        else ""
    )
    slk = _table(
        native,
        "100;E1+2" if kind == "cached_formula" else "100",
        header="upgradeID",
        code="Rhar",
        extra=extra,
    )
    files = {"UpgradeData.slk": slk}
    release = kind == "binary_release"
    if release:
        modification = (
            canonical.encode()
            + struct.pack("<iii", 3, 0, 0)
            + b"300\0"
            + struct.pack("<I", 0)
        )
        files["war3map.w3q"] = (
            struct.pack("<iii", 2, 0, 1)
            + b"RharRhar"
            + struct.pack("<i", 1)
            + modification
        )
    md = _load_map_impl(_Archive(files), "tech.w3x", 0, None, MapLoadContext())
    obj = md.obj_identity_index[("科技", "Rhar")]
    assert bool(obj.field_blockers) is not release
    native_evidence = [row for row in obj.field_evidence if row.key == native]
    assert native_evidence and all(row.encoded_evidence for row in native_evidence)
    assert any(
        json.loads(row.encoded_evidence)["cell"]["raw"] == "K100"
        for row in native_evidence
    )
    # Keep the actually loaded object unchanged while focusing the export fixture.
    pack = _pack(replace(md, objects={"科技": [obj]}), tmp_path / "pack")
    with (pack / "对象字段.tsv").open(encoding="utf-8", newline="") as stream:
        native_rows = [
            row
            for row in csv.DictReader(stream, delimiter="\t")
            if row["字段键"] == native
        ]
    assert native_rows
    assert {row["证据状态"] for row in native_rows} <= (
        {"overridden"} if release else {"unknown", "conflict"}
    )
    record = next(
        record
        for record in load_object_records(pack, "科技", queries).records
        if record.row[1] == "Rhar"
    )
    notes: list[str] = []
    scalar = _scalar(record, canonical, queries._tech_base_fields()["Rhar"], notes)
    assert scalar == (Decimal(300) if release else None)
    rendered = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "tech", "Rhar --level 2")
    ).render()
    if release:
        assert f"{canonical} 字段未确认" not in rendered
        assert obj.field_values[canonical] == "300"
    else:
        assert f"{canonical} 字段未确认" in rendered
        assert "300" not in obj.field_values.values()

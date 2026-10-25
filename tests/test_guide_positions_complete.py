"""Guide and minimap locations must include every coordinate of a rawcode."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from gametool.archive_source import ArchiveSource
from gametool.doo import Doodad, Unit
from gametool.guide_minimap import (
    GuideMinimapError,
    crop_to_playable,
    extra_marks_from_json,
    load_minimap_assets,
    render_marks,
    script_unit_positions,
    shop_marks,
)
from gametool.guide_report import format_guide_report
from gametool.item_relation_models import (
    ItemRelation,
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationEvidence,
    RelationObject,
)
from gametool.map_data import GameObject, MapData
from gametool.placement_positions import unit_position_groups


def _map() -> MapData:
    md = MapData(path="read-only.w3x", name="多处商店")
    md.objects["单位"] = [
        GameObject(
            "单位", "w3u", "n001", "n001", "商店", True, fields=[("usei", "I001")]
        )
    ]
    md.units = [
        Unit("n001", 0, 10.0, 20.0, 0.0, 0.0),
        Unit("n001", 0, 30.0, 40.0, 0.0, 0.0),
    ]
    md.scripts = {
        "war3map.j": "call CreateUnit(Player(0),'n001',10,20,0)\ncall CreateUnit(Player(0),'n001',50,60,0)"
    }
    relation = ItemRelation(
        kind=ItemRelationKind.SHOP_SELL,
        item=RelationObject("物品", "I001", "装备"),
        source=RelationObject("单位", "n001", "商店"),
        evidence=RelationEvidence(source="fixture"),
        confidence=RelationConfidence.CONFIRMED,
        completeness=RelationCompleteness.COMPLETE,
    )
    md.item_relations = ItemRelationIndex.build((relation,))
    return md


def test_script_positions_keep_all_locations_of_one_code() -> None:
    assert script_unit_positions(_map()) == {"n001": ((10.0, 20.0), (50.0, 60.0))}


def test_minimap_marks_every_location_of_one_shop() -> None:
    positions = {"n001": ((10.0, 20.0), (30.0, 40.0), (50.0, 60.0))}
    assert shop_marks(_map(), positions) == (
        ("商店", 10.0, 20.0),
        ("商店", 30.0, 40.0),
        ("商店", 50.0, 60.0),
    )


def test_guide_shows_preplaced_and_script_positions_without_mirrored_duplicates() -> (
    None
):
    report = format_guide_report(_map(), section="shops")
    for x, y in ((10, 20), (30, 40), (50, 60)):
        assert f"@({x},{y})" in report
    assert report.count("@(10,20)") == 1


def test_all_script_sources_languages_and_many_locations() -> None:
    md = _map()
    md.scripts["war3map.lua"] = "\n".join(
        f"CreateUnit(Player(0),FourCC('n001'),{index},-{index},0)"
        for index in range(512)
    )
    points = unit_position_groups(md)["n001"]
    assert len(points) == 515
    assert points[-1] == (511.0, -511.0)
    assert len(shop_marks(md, {"n001": points})) == 515


def _with_archive(
    md: MapData, monkeypatch: pytest.MonkeyPatch, units: list[Unit] | Exception
) -> None:
    def parse(_raw: bytes) -> list[Unit]:
        if isinstance(units, Exception):
            raise units
        return units

    @contextmanager
    def opened():
        yield SimpleNamespace(
            has_file=lambda name: name == "war3mapUnits.doo",
            read_file=lambda _name: b"synthetic",
        )

    md.archive_source = cast(ArchiveSource, cast(object, SimpleNamespace(open=opened)))
    monkeypatch.setattr("gametool.doo.parse_units", parse)


def test_archive_positions_merge_without_replacing_loaded_or_script_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = _map()
    _with_archive(
        md,
        monkeypatch,
        [
            Unit("n001", 0, 30, 40, 0, 0),
            Unit("n001", 0, 70, 80, 0, 0),
        ],
    )
    image, positions = load_minimap_assets(md)
    assert image is None
    assert positions["n001"] == ((10, 20), (30, 40), (70, 80), (50, 60))


def test_malformed_archive_placements_cannot_be_presented_as_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = _map()
    _with_archive(md, monkeypatch, ValueError("truncated record"))
    with pytest.raises(GuideMinimapError, match="无法确认全部点位"):
        load_minimap_assets(md)


def _drop(
    code: str,
    name: str,
    source: str,
    point: tuple[float, float] | None = None,
    *,
    kind: ItemRelationKind = ItemRelationKind.UNIT_DROP,
) -> ItemRelation:
    return ItemRelation(
        kind=kind,
        item=RelationObject("物品", code, name),
        source=RelationObject(
            "可破坏物" if kind == ItemRelationKind.DESTRUCTABLE_DROP else "单位",
            source,
            "掉落来源",
        ),
        x=None if point is None else float(point[0]),
        y=None if point is None else float(point[1]),
        chance=100,
        evidence=RelationEvidence(source="fixture"),
        confidence=RelationConfidence.CONFIRMED,
        completeness=RelationCompleteness.COMPLETE,
    )


def test_instance_drops_do_not_spread_to_other_locations_of_same_code() -> None:
    md = _map()
    md.item_relations = ItemRelationIndex.build(
        (
            _drop("I001", "专属甲", "n001", (10, 20)),
            _drop("I002", "专属乙", "n001", (30, 40)),
            _drop("I003", "共有物品", "n001"),
        )
    )
    rows = format_guide_report(md, section="drops").splitlines()
    first = next(row for row in rows if "@(10,20)" in row)
    second = next(row for row in rows if "@(30,40)" in row)
    script = next(row for row in rows if "@(50,60)" in row)
    assert "专属甲" in first and "专属乙" not in first
    assert "专属乙" in second and "专属甲" not in second
    assert "专属" not in script and "[脚本位置]" in script
    assert all("共有物品" in row for row in (first, second, script))


def test_destructable_and_relation_only_positions_keep_opaque_rawcodes() -> None:
    md = _map()
    md.doodads = [Doodad("B!01", 0, 1.25, -2.5, 0, 0)]
    md.scripts["war3map.lua"] = "CreateDestructable(FourCC('B!01'),3.5,-4.75,0,1,0)"
    md.item_relations = ItemRelationIndex.build(
        (
            _drop("I001", "箱内物品", "B!01", kind=ItemRelationKind.DESTRUCTABLE_DROP),
            _drop("I002", "隐蔽物品", "n!02", (1e-6, -9.125)),
        )
    )
    report = format_guide_report(md, section="drops")
    assert "@(1.25,-2.5)" in report and "@(3.5,-4.75)" in report
    assert "@(1e-06,-9.125) [关系记录位置]" in report
    assert report.count("箱内物品") == 2


@pytest.mark.parametrize("coordinate", ["true", "NaN", "Infinity", "1e9999"])
def test_extra_marks_reject_non_numeric_and_non_finite_coordinates(
    tmp_path: Path, coordinate: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(f'[["bad", {coordinate}, 0]]', encoding="utf-8")
    with pytest.raises(GuideMinimapError):
        extra_marks_from_json(str(path))


def test_long_legend_grows_to_include_full_name_and_coordinates(tmp_path: Path) -> None:
    from PIL import Image

    image = Image.new("RGB", (20, 20), (40, 80, 40))
    short = tmp_path / "short.png"
    long = tmp_path / "long.png"
    render_marks(image, (0, 0, 100, 100), (("短名", 50, 50),), str(short), scale=1)
    render_marks(
        image,
        (0, 0, 100, 100),
        (("完整商店名称" * 40, 50.125, 50.25), ("远处", 1e308, -1e308)),
        str(long),
        scale=1,
    )
    with Image.open(short) as first, Image.open(long) as second:
        assert second.width > first.width * 2
        assert second.height >= first.height
        assert second.getbbox() == (0, 0, second.width, second.height)


def test_grid_handles_extreme_aspect_and_large_coordinate_offsets(
    tmp_path: Path,
) -> None:
    from PIL import Image

    image = Image.new("RGB", (8, 8))
    assert crop_to_playable(image, (0, 0, 1, 1e100)).size == (1, 8)
    for index, bounds in enumerate(
        ((0, 0, 1, 1e100), (1e20, 1e20, 1e20 + 65536, 1e20 + 65536))
    ):
        path = tmp_path / f"extreme{index}.png"
        render_marks(image, bounds, (), str(path), scale=1)
        assert path.is_file()

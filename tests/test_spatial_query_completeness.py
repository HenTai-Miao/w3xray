"""Complete spatial data from source exports through shared query results."""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.api import MapData
from gametool.doo import Unit
from gametool.knowledge_preplaced_exports import format_preplaced_units_tsv
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_placements import script_placements
from gametool.pack_query_spatial import cluster_points


@pytest.fixture(autouse=True)
def isolated_query_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _placed_pack(pack: Path, category: str, code: str, x: float, y: float) -> None:
    objects = pack / "对象ID"
    objects.mkdir(parents=True)
    (objects / f"{category}.tsv").write_text(
        f"分类\tID\t数值\t基础ID\t名称\t自定义\t说明\n{category}\t{code}\t1\t{code}\t目标\t是\t\n",
        encoding="utf-8",
    )
    (pack / "预放置单位.tsv").write_text(
        f"序号\t类型ID\t名称\t玩家\tX\tY\tZ\n1\t{code}\t目标\t0\t{x!r}\t{y!r}\t0\n",
        encoding="utf-8",
    )


def test_deep_static_coordinate_is_not_limited_by_python_parser() -> None:
    value = "(" * 2000 + "123.25" + ")" * 2000
    assert script_placements(f"call CreateItem('I001',{value},0)") == [
        ("I001", 123.25, 0.0, "item")
    ]


def test_placement_export_preserves_every_float_digit() -> None:
    md = MapData(path="read-only.w3x", name="坐标精度")
    x, y = 12345.6787109375, -9876.5439453125
    md.units = [Unit("n001", 0, x, y, 0.0, 0.0)]
    row = format_preplaced_units_tsv(md).splitlines()[1].split("\t")
    assert (float(row[4]), float(row[5])) == (x, y)


def test_near_json_preserves_source_coordinates_and_distance(tmp_path: Path) -> None:
    x, y = 12345.6787109375, -9876.5439453125
    _placed_pack(tmp_path, "单位", "n001", x, y)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", f"{x} {y} 1")
    )
    entry = json.loads(result.render(as_json=True))["entries"][0]
    assert (entry["x"], entry["y"], entry["dist"]) == (x, y, 0.0)


def test_near_item_filter_includes_preplaced_ground_items(tmp_path: Path) -> None:
    _placed_pack(tmp_path, "物品", "I001", 20.25, -10.5)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "20 -10 1", near_kind="物品")
    )
    assert result.exit_code == 0
    entries = json.loads(result.render(as_json=True))["entries"]
    assert [
        (entry["kind"], entry["code"], entry["x"], entry["y"]) for entry in entries
    ] == [("物品", "I001", 20.25, -10.5)]


@pytest.mark.parametrize("category", ["单位", "物品"])
def test_where_reads_preplaced_coordinates_by_code_and_name(
    tmp_path: Path, category: str
) -> None:
    _placed_pack(tmp_path, category, "X001", 12345.6787109375, -9876.5439453125)
    for needle in ("X001", "目标"):
        result = queries.execute_pack_query(
            PackQueryCliOptions(str(tmp_path), "where", needle)
        )
        assert result.exit_code == 0
        assert "12345.6787109375, -9876.5439453125" in result.render()
        assert "[预放置]" in result.render()


def test_near_group_keeps_every_instance_and_fractional_distance(
    tmp_path: Path,
) -> None:
    _placed_pack(tmp_path, "单位", "n001", 1.25, 2.5)
    with (tmp_path / "预放置单位.tsv").open("a", encoding="utf-8") as handle:
        handle.write("2\tn001\t目标\t0\t3.25\t4.5\t0\n")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "0 0 100")
    )
    entry = json.loads(result.render(as_json=True))["entries"][0]
    assert entry["positions"] == [[1.25, 2.5], [3.25, 4.5]]
    assert entry["count"] == 2
    assert entry["dist"] == math.hypot(2.25, 3.5)
    assert "positions" in result.render()


def test_group_center_preserves_subnormal_values(tmp_path: Path) -> None:
    value = 5e-324
    _placed_pack(tmp_path, "单位", "n001", value, value)
    with (tmp_path / "预放置单位.tsv").open("a", encoding="utf-8") as handle:
        handle.write(f"2\tn001\t目标\t0\t{value!r}\t{value!r}\t0\n")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", f"{value!r} {value!r} 0")
    )
    entry = json.loads(result.render(as_json=True))["entries"][0]
    assert (entry["x"], entry["y"], entry["count"]) == (value, value, 2)


def test_near_accepts_full_rawcodes_and_avoids_centroid_overflow(
    tmp_path: Path,
) -> None:
    _placed_pack(tmp_path, "单位", "!001", 1e308, 1e308)
    with (tmp_path / "预放置单位.tsv").open("a", encoding="utf-8") as handle:
        handle.write("2\t!001\t目标\t0\t1e308\t1e308\t0\n")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1e308 1e308 0")
    )
    assert result.exit_code == 0
    entry = json.loads(result.render(as_json=True))["entries"][0]
    assert (entry["code"], entry["x"], entry["y"], entry["count"]) == (
        "!001",
        1e308,
        1e308,
        2,
    )


def test_near_outside_radius_respects_explicit_limit_and_discloses_count(
    tmp_path: Path,
) -> None:
    _placed_pack(tmp_path, "单位", "n001", 10.0, 0.0)
    with (tmp_path / "预放置单位.tsv").open("a", encoding="utf-8") as handle:
        for index in range(1, 8):
            handle.write(f"{index + 1}\tn001\t目标\t0\t{10 + index}\t0\t0\n")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "0 0 0", limit=3)
    )
    assert result.render().count("半径外最近单位") == 3
    assert "其余 5 条" in result.render()


def test_lua_and_jass_rectangles_use_full_numeric_parser(tmp_path: Path) -> None:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "a.j").write_text(
        "set gg_rct_jass = Rect(-(5+5),-2e1,20,20)\n// set gg_rct_fake = Rect(-1,-1,1,1)\n",
        encoding="utf-8",
    )
    (scripts / "b.lua").write_text(
        "gg_rct_lua = Rect(-2^4, -(9//2), 20, 20)\n", encoding="utf-8"
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "0 0 0", near_kind="脚本")
    )
    assert result.exit_code == 0
    assert "gg_rct_jass" in result.render() and "gg_rct_lua" in result.render()
    assert "gg_rct_fake" not in result.render()


def test_spatial_grid_preserves_greedy_groups_and_duplicates() -> None:
    rng = random.Random(42)
    points = [
        (rng.uniform(-10000, 10000), rng.uniform(-10000, 10000)) for _ in range(400)
    ]
    points.extend(points[:20])
    remaining = list(points)
    expected = []
    while remaining:
        seed = remaining[0]
        group = tuple(
            point
            for point in remaining
            if math.hypot(point[0] - seed[0], point[1] - seed[1]) < 1200
        )
        expected.append(group)
        selected = set(group)
        remaining = [point for point in remaining if point not in selected]
    assert list(cluster_points(points)) == expected
    assert sum(len(group) for group in expected) == len(points)


def test_sparse_spatial_grid_does_not_rescan_every_remaining_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gametool import pack_query_spatial

    count = 0
    hypot = math.hypot

    def distance(x: float, y: float) -> float:
        nonlocal count
        count += 1
        return hypot(x, y)

    monkeypatch.setattr(pack_query_spatial.math, "hypot", distance)
    points = [(index * 5000.0, index * 3000.0) for index in range(8000)]
    groups = list(cluster_points(points))
    assert len(groups) == len(points)
    assert count <= 2 * len(points)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows live command adapter")
def test_live_coordinate_copy_template_keeps_full_precision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gametool import live_inventory

    x, y = 12345.6787109375, -9876.5439453125
    unit = {"unit": "目标", "code": "n001", "x": x, "y": y, "items": []}
    report = {
        "strategy_used": "handle",
        "selected_unit": unit,
        "units": [unit],
        "slots": [1],
    }
    monkeypatch.setattr(live_inventory, "read_live", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(live_inventory, "append_live_journal", lambda _report: None)
    assert live_inventory.main(["--pack", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert f"坐标反查模板：near {x} {y}" in text

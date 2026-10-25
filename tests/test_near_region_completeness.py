"""Near retains every source/context region with exact structured provenance."""

import json
import math
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_regions import containing_regions
from gametool.query_coordinates import coordinates_from_text
from gametool.script_sources import AnalysisScriptSource


@pytest.fixture(autouse=True)
def isolate_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _pack(pack: Path, text: str, source: str = "war3map.lua") -> Path:
    scripts = pack / "脚本可读文本"
    scripts.mkdir(parents=True, exist_ok=True)
    path = scripts / source
    path.write_text(text, encoding="utf-8")
    return path


def _query(pack: Path, point: str = "0 0 0", limit: int = 0, kind: str = ""):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "near", point, limit=limit, near_kind=kind)
    )


@pytest.mark.parametrize("lua", [True, False, None])
def test_region_metadata_keeps_known_language_or_explicit_unknown(
    lua: bool | None,
) -> None:
    text = (
        "gg_rct_Test=Rect(-1,-2,3,4)"
        if lua is not False
        else "set gg_rct_Test=Rect(-1,-2,3,4)"
    )
    row = containing_regions((AnalysisScriptSource("source.txt", text, lua),), 0, 0)[0]
    assert row["language"] == (
        "Lua" if lua is True else "JASS" if lua is False else "unknown"
    )
    assert row["source"] == "source.txt" and row["bounds"] == (-1.0, -2.0, 3.0, 4.0)


def test_same_region_name_keeps_all_parameter_context_bounds(tmp_path: Path) -> None:
    _pack(tmp_path, "function R(x)gg_rct_Test=Rect(-x,-x,x,x)end R(1);R(2);R(3)")
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and not data["entries"]
    assert [row["bounds"] for row in data["regions"]] == [
        [-1.0, -1.0, 1.0, 1.0],
        [-2.0, -2.0, 2.0, 2.0],
        [-3.0, -3.0, 3.0, 3.0],
    ]
    assert data["regions_total"] == 3 and data["regions_omitted"] == 0
    assert result.render().count("    区域 gg_rct_Test:") == 3
    assert all(
        f"R({i})" in "\n".join(row["evidence"])
        for i, row in enumerate(data["regions"], 1)
    )


def test_distinct_source_assignments_with_identical_name_and_bounds_remain_visible(
    tmp_path: Path,
) -> None:
    text = "gg_rct_Test=Rect(-1,-2,3,4);gg_rct_Test=Rect(-1,-2,3,4)"
    _pack(tmp_path, text)
    rows = json.loads(_query(tmp_path).render(as_json=True))["regions"]
    assert len(rows) == 2 and rows[0]["offset"] != rows[1]["offset"]
    assert rows[0]["bounds"] == rows[1]["bounds"]


def test_identical_regions_in_different_sources_preserve_each_source(
    tmp_path: Path,
) -> None:
    for name in ["one.lua", "two.lua"]:
        _pack(tmp_path, "gg_rct_Test=Rect(-1,-2,3,4)", name)
    rows = json.loads(_query(tmp_path).render(as_json=True))["regions"]
    assert len(rows) == 2 and {row["source"] for row in rows} == {"one.lua", "two.lua"}


def test_unicode_multiline_expression_offsets_round_trip_to_original_source(
    tmp_path: Path,
) -> None:
    text = "-- 开头\n_G . gg_rct_区域 = Rect(\n -1.25, -2.5,\n 3.75, 4.125\n)\n"
    _pack(tmp_path, text)
    row = json.loads(_query(tmp_path).render(as_json=True))["regions"][0]
    assert row["name"] == "gg_rct_区域" and row["line"] == 2 and row["end_line"] == 5
    assert text[row["offset"] : row["end_offset"]] == row["expression"]
    assert row["bounds"] == [-1.25, -2.5, 3.75, 4.125]


@pytest.mark.parametrize("point", ["0 0 0", "-1 -2 0", "3 4 0", "-1 4 0", "3 -2 0"])
def test_region_containment_includes_edges_and_corners(
    tmp_path: Path, point: str
) -> None:
    _pack(tmp_path, "gg_rct_Test=Rect(-1,-2,3,4)")
    data = json.loads(_query(tmp_path, point).render(as_json=True))
    assert len(data["regions"]) == 1 and data["exit_code"] == 0


@pytest.mark.parametrize(
    "point", ["-1.0001 0 100", "3.0001 0 100", "0 -2.0001 100", "0 4.0001 100"]
)
def test_radius_does_not_turn_noncontaining_regions_into_hits(
    tmp_path: Path, point: str
) -> None:
    _pack(tmp_path, "gg_rct_Test=Rect(-1,-2,3,4)")
    data = json.loads(_query(tmp_path, point).render(as_json=True))
    assert (
        data["regions"] == [] and data["regions_total"] == data["regions_omitted"] == 0
    )
    assert data["exit_code"] == 2


def test_reversed_source_bounds_are_retained_alongside_query_envelope(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, "gg_rct_Reverse=Rect(3,4,-1,-2)")
    row = json.loads(_query(tmp_path).render(as_json=True))["regions"][0]
    assert row["bounds"] == [-1.0, -2.0, 3.0, 4.0] and row["source_bounds"] == [
        3.0,
        4.0,
        -1.0,
        -2.0,
    ]


@pytest.mark.parametrize("value", [5e-324, 1e308, -1e308])
def test_region_json_preserves_finite_precision_without_center_arithmetic(
    tmp_path: Path, value: float
) -> None:
    _pack(tmp_path, f"gg_rct_Test=Rect({value!r},{value!r},{value!r},{value!r})")
    data = json.loads(_query(tmp_path, f"{value!r} {value!r} 0").render(as_json=True))
    assert data["regions"][0]["bounds"] == [value] * 4
    assert all(math.isfinite(x) for x in data["regions"][0]["bounds"])


@pytest.mark.parametrize("limit", [0, 1, 2, 3, 5])
def test_explicit_region_limits_count_complete_records_and_disclose_exact_omissions(
    tmp_path: Path, limit: int
) -> None:
    _pack(tmp_path, "function R(x)gg_rct_Test=Rect(-x,-x,x,x)end R(1);R(2);R(3)")
    result = _query(tmp_path, limit=limit)
    data = json.loads(result.render(as_json=True))
    kept = min(limit, 3) if limit else 3
    assert (
        len(data["regions"]) == kept
        and data["regions_total"] == 3
        and data["regions_omitted"] == 3 - kept
    )
    assert result.render().count("    区域 gg_rct_Test:") == kept
    assert all(
        row["expression"] == "gg_rct_Test=Rect(-x,-x,x,x)" and row["evidence"]
        for row in data["regions"]
    )
    assert (f"其余 {3 - kept} 条未显示" in result.render()) == (kept < 3)


@pytest.mark.parametrize(
    "kind,expected", [("", 1), ("脚本", 1), ("单位", 1), ("物品", 0), ("装饰", 0)]
)
def test_region_kind_filters_keep_existing_layer_semantics(
    tmp_path: Path, kind: str, expected: int
) -> None:
    _pack(tmp_path, "gg_rct_Test=Rect(-1,-2,3,4)")
    data = json.loads(_query(tmp_path, kind=kind).render(as_json=True))
    assert len(data["regions"]) == data["regions_total"] == expected


def test_region_and_placement_records_have_independent_complete_limits(
    tmp_path: Path,
) -> None:
    _pack(
        tmp_path,
        "function R(x)gg_rct_Test=Rect(-x,-x,x,x);CreateItem(FourCC('I001'),x,0)end R(1);R(2);R(3)",
    )
    result = _query(tmp_path, "0 0 10", limit=2)
    data = json.loads(result.render(as_json=True))
    assert len(data["entries"]) == len(data["regions"]) == 2
    assert data["regions_total"] == 3 and data["regions_omitted"] == 1
    assert result.render().count("其余 1 条未显示") == 2


def test_unknown_or_mutated_regions_are_diagnostics_not_structured_hits(
    tmp_path: Path,
) -> None:
    _pack(
        tmp_path,
        "gg_rct_Moved=Rect(-1,-2,3,4);RemoveRect(gg_rct_Moved);gg_rct_Unknown=RuntimeRect()",
    )
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert (
        data["regions"] == [] and data["regions_total"] == 0 and data["exit_code"] == 2
    )
    assert all(name in result.render() for name in ["gg_rct_Moved", "gg_rct_Unknown"])


def test_campaign_regions_keep_same_names_and_sources_under_each_pack(
    tmp_path: Path,
) -> None:
    for index in range(3):
        _pack(
            tmp_path / "子地图" / f"{index:03}",
            "function R(x)gg_rct_Test=Rect(-x,-x,x,x)end R(1);R(2);R(3)",
        )
    result = _query(tmp_path, limit=2)
    data = json.loads(result.render(as_json=True))
    assert result.campaign and result.exit_code == 0 and len(data["sections"]) == 3
    assert (
        len(data["regions"]) == 6
        and data["regions_total"] == 9
        and data["regions_omitted"] == 3
    )
    assert all(
        len(section["regions"]) == 2
        and section["regions_total"] == 3
        and section["regions_omitted"] == 1
        for section in data["sections"]
    )
    assert {row["pack"] for row in data["regions"]} == {
        str(tmp_path / "子地图" / f"{index:03}") for index in range(3)
    }
    assert all(
        row["section"].startswith("子地图 ") and row["source"] == "war3map.lua"
        for row in data["regions"]
    )


def test_container_level_regions_are_preserved_with_child_regions(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, "gg_rct_Test=Rect(-1,-2,3,4)")
    _pack(tmp_path / "子地图" / "001", "gg_rct_Test=Rect(-3,-4,5,6)")
    data = json.loads(_query(tmp_path).render(as_json=True))
    assert len(data["regions"]) == 2 and {
        row["section"] for row in data["regions"]
    } == {"容器级", "子地图 001"}


def test_again_preserves_structured_regions_and_original_query_memo(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, "function R(x)gg_rct_Test=Rect(-x,-x,x,x)end R(1);R(2);R(3)")
    first = _query(tmp_path)
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()
    again = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "again", ""))
    one = json.loads(first.render(as_json=True))
    two = json.loads(again.render(as_json=True))
    assert (
        two["regions"] == one["regions"]
        and two["regions_total"] == one["regions_total"] == 3
    )
    assert memo.read_bytes() == before and "[重跑] near" in again.render()


def test_source_edit_with_same_size_and_mtime_refreshes_region_bounds(
    tmp_path: Path,
) -> None:
    path = _pack(tmp_path, "gg_rct_Test=Rect(-1,-2,3,4)")
    before = path.stat()
    one = json.loads(_query(tmp_path).render(as_json=True))
    path.write_text("gg_rct_Test=Rect(-9,-2,3,4)", encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    two = json.loads(_query(tmp_path).render(as_json=True))
    assert (
        one["regions"][0]["bounds"][0] == -1.0
        and two["regions"][0]["bounds"][0] == -9.0
    )


def test_1500_same_name_regions_are_visible_in_text_and_json(tmp_path: Path) -> None:
    count = 1500
    _pack(
        tmp_path,
        "function R(x)gg_rct_Test=Rect(-x,-x,x,x)end\n"
        + "\n".join(f"R({index + 1})" for index in range(count)),
    )
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert (
        len(data["regions"]) == data["regions_total"] == count
        and data["regions_omitted"] == 0
    )
    assert result.render().count("    区域 gg_rct_Test:") == count
    assert data["regions"][-1]["bounds"] == [
        -float(count),
        -float(count),
        float(count),
        float(count),
    ]


def test_region_bounds_and_provenance_numbers_never_become_a_coordinate_handoff(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, "gg_rct_Test=Rect(-1,-2,3,4)")
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert coordinates_from_text(json.dumps(data["regions"][0])) is None
    assert coordinates_from_text(result.render(as_json=True)) is None
    assert coordinates_from_text(result.render().split("    区域 ")[-1]) is None


def test_other_query_json_keeps_its_existing_nonspatial_schema(tmp_path: Path) -> None:
    _pack(tmp_path, "gg_rct_Test=Rect(-1,-2,3,4)")
    data = json.loads(
        queries.execute_pack_query(
            PackQueryCliOptions(str(tmp_path), "stats", "")
        ).render(as_json=True)
    )
    assert "regions" not in data and "regions_total" not in data

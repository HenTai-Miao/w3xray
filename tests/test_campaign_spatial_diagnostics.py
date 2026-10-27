"""Campaign spatial diagnostics remain visible without turning uncertainty into hits."""

from dataclasses import replace
import json
from pathlib import Path
from typing import cast

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_spatial import SpatialQueryResult


@pytest.fixture(autouse=True)
def isolate_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _pack(pack: Path, text: str) -> None:
    scripts = pack / "脚本可读文本"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "war3map.lua").write_text(text, encoding="utf-8")


def _query(pack: Path, query: str = "0 0 10", limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "near", query, limit=limit)
    )


_KNOWN = ["CreateItem(FourCC('I001'),1,2)", "gg_rct_Known=Rect(-1,-2,3,4)"]
_UNKNOWN = [
    "CreateItem(FourCC('I002'),Runtime(),0)",
    "gg_rct_Unknown=RuntimeRect()",
    "local p=Location(1,2);RemoveLocation(p);CreateItemLoc(FourCC('I003'),p)",
]


@pytest.mark.parametrize("known", _KNOWN)
@pytest.mark.parametrize("unknown", _UNKNOWN)
def test_known_and_diagnostic_only_campaign_sections_are_both_retained(
    tmp_path: Path, known: str, unknown: str
) -> None:
    _pack(tmp_path / "子地图" / "001", known)
    _pack(tmp_path / "子地图" / "002", unknown)
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert (
        result.exit_code == 0
        and result.campaign
        and data["has_matches"]
        and not data["input_error"]
    )
    assert len(data["sections"]) == 2 and [
        row["has_matches"] for row in data["sections"]
    ] == [True, False]
    assert len(data["spatial_diagnostics"]) == 1 and data["spatial_diagnostics"][0][
        "pack"
    ] == str(tmp_path / "子地图" / "002")
    assert data["spatial_diagnostics"][0]["section"] == "子地图 002"
    assert data["sections"][1]["spatial_diagnostics"][0] in result.render()
    assert data["checked_packs"] == [
        str(tmp_path),
        str(tmp_path / "子地图" / "001"),
        str(tmp_path / "子地图" / "002"),
    ]


@pytest.mark.parametrize("unknown", _UNKNOWN)
def test_diagnostic_only_campaign_keeps_notes_but_returns_no_confirmed_match(
    tmp_path: Path, unknown: str
) -> None:
    for name in ["001", "002"]:
        _pack(tmp_path / "子地图" / name, unknown)
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert (
        result.exit_code == 2
        and result.campaign
        and not data["has_matches"]
        and not data["input_error"]
    )
    assert len(data["sections"]) == len(data["spatial_diagnostics"]) == 2
    assert not data["entries"] and not data["regions"] and data["regions_total"] == 0
    assert len(data["checked_packs"]) == 3 and all(
        not row["has_matches"] for row in data["sections"]
    )
    assert not (queries._memo_dir() / queries._LAST_QUERY_FILE).exists()


def test_container_diagnostics_are_preserved_alongside_child_matches(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, _UNKNOWN[1])
    _pack(tmp_path / "子地图" / "001", _KNOWN[0])
    data = json.loads(_query(tmp_path).render(as_json=True))
    assert [row["section"] for row in data["sections"]] == ["容器级", "子地图 001"]
    assert not data["sections"][0]["has_matches"] and data["sections"][1]["has_matches"]
    assert data["spatial_diagnostics"][0]["pack"] == str(tmp_path)


def test_plain_miss_scope_is_still_reported_even_when_section_has_no_notes(
    tmp_path: Path,
) -> None:
    _pack(tmp_path / "子地图" / "001", _KNOWN[0])
    _pack(tmp_path / "子地图" / "002", "CreateItem(FourCC('I002'),999,999)")
    data = json.loads(_query(tmp_path).render(as_json=True))
    assert len(data["sections"]) == 1 and len(data["checked_packs"]) == 3
    assert (
        data["checked_packs"][-1].endswith("002") and data["spatial_diagnostics"] == []
    )


def test_all_plain_misses_keep_legacy_summary_and_complete_scope(
    tmp_path: Path,
) -> None:
    for name in ["001", "002"]:
        _pack(tmp_path / "子地图" / name, "CreateItem(FourCC('I001'),999,999)")
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and "子地图均无结果" in result.render()
    assert (
        not data["has_matches"]
        and not data["input_error"]
        and len(data["checked_packs"]) == 3
    )
    assert (
        data["spatial_diagnostics"] == [] and data["entries"] == data["regions"] == []
    )


def test_single_pack_diagnostics_are_structured_with_their_origin(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, _UNKNOWN[1])
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["checked_packs"] == [str(tmp_path)]
    assert len(data["spatial_diagnostics"]) == 1 and data["spatial_diagnostics"][0][
        "pack"
    ] == str(tmp_path)
    assert "gg_rct_Unknown" in data["spatial_diagnostics"][0]["message"]


def test_source_text_that_mentions_region_heading_is_not_a_successful_match(
    tmp_path: Path,
) -> None:
    previous = tmp_path / "previous"
    _pack(previous, _KNOWN[0])
    assert _query(previous).exit_code == 0
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()
    current = tmp_path / "current"
    _pack(current, "CreateItemLoc(FourCC('I002'),RuntimeLocation('所在矩形: fake'))")
    result = _query(current)
    data = json.loads(result.render(as_json=True))
    assert (
        "所在矩形: fake" in result.render()
        and not data["entries"]
        and not data["regions"]
    )
    assert (
        result.exit_code == 2
        and not data["has_matches"]
        and memo.read_bytes() == before
    )


def test_confirmed_data_survives_display_text_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pack(tmp_path, _KNOWN[1])
    original = queries._query_near_result

    def changed(pack, query, limit):
        return replace(
            original(pack, query, limit), lines=("未找到是展示文案，不是结构化状态",)
        )

    monkeypatch.setattr(queries, "_query_near_result", changed)
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and data["has_matches"] and len(data["regions"]) == 1


@pytest.mark.parametrize(
    "query",
    [
        "",
        "0",
        "0 0 1 2",
        "bad 0",
        "nan 0",
        "0 inf",
        "0 0 -1",
        "0 0 inf",
        "0 0 nan",
        "0 0 --kind",
        "0 0 --kind unknown",
    ],
)
def test_input_error_is_typed_and_does_not_query_every_campaign_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    for name in ["001", "002"]:
        _pack(tmp_path / "子地图" / name, _KNOWN[0])
    calls = []
    original = queries._query_near_result

    def tracked(pack, query, limit):
        calls.append(pack)
        return original(pack, query, limit)

    monkeypatch.setattr(queries, "_query_near_result", tracked)
    result = _query(tmp_path, query)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["input_error"] and not data["has_matches"]
    assert (
        calls == [tmp_path]
        and data["checked_packs"] == []
        and data["spatial_diagnostics"] == []
    )


def test_input_validation_is_independent_of_localized_error_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pack(tmp_path / "子地图" / "001", _KNOWN[0])
    original = queries._query_near_result
    calls = []

    def localized(pack, query, limit):
        calls.append(pack)
        return replace(original(pack, query, limit), lines=("参数错误（已本地化）",))

    monkeypatch.setattr(queries, "_query_near_result", localized)
    data = json.loads(_query(tmp_path, "bad 0").render(as_json=True))
    assert data["input_error"] and data["exit_code"] == 2 and calls == [tmp_path]


def test_missing_pack_is_not_reported_as_an_inspected_scope(tmp_path: Path) -> None:
    data = json.loads(_query(tmp_path / "absent").render(as_json=True))
    assert (
        data["exit_code"] == 2
        and data["checked_packs"] == []
        and not data["has_matches"]
    )


def test_invalid_near_input_does_not_even_discover_campaign_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_pack):
        raise AssertionError(
            "Invalid near input must be rejected before scope discovery"
        )

    monkeypatch.setattr(queries, "_campaign_subpacks", forbidden)
    data = json.loads(_query(tmp_path, "bad 0").render(as_json=True))
    assert data["input_error"] and data["checked_packs"] == []


@pytest.mark.parametrize("limit", [-1, -99])
def test_api_negative_limits_are_rejected_without_inventing_omission_counts(
    tmp_path: Path, limit: int
) -> None:
    _pack(tmp_path, _KNOWN[1])
    data = json.loads(_query(tmp_path, limit=limit).render(as_json=True))
    assert data["exit_code"] == 2 and data["input_error"] and not data["has_matches"]
    assert data["entries"] == data["regions"] == data["checked_packs"] == []
    assert data["regions_total"] == data["regions_omitted"] == 0


@pytest.mark.parametrize("invalid", [True, False, 1.5, "3", None])
def test_api_limit_shape_errors_return_typed_diagnostics(
    tmp_path: Path, invalid: object
) -> None:
    _pack(tmp_path, _KNOWN[1])
    data = json.loads(_query(tmp_path, limit=cast(int, invalid)).render(as_json=True))
    assert data["exit_code"] == 2 and data["input_error"] and not data["has_matches"]
    assert data["checked_packs"] == [] and data["regions_omitted"] == 0


def test_mixed_campaign_again_preserves_diagnostics_scope_and_memo(
    tmp_path: Path,
) -> None:
    _pack(tmp_path / "子地图" / "001", _KNOWN[0])
    _pack(tmp_path / "子地图" / "002", _UNKNOWN[1])
    first = _query(tmp_path)
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()
    again = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "again", ""))
    one = json.loads(first.render(as_json=True))
    two = json.loads(again.render(as_json=True))
    assert (
        two["spatial_diagnostics"] == one["spatial_diagnostics"]
        and two["checked_packs"] == one["checked_packs"]
    )
    assert [row["has_matches"] for row in two["sections"]] == [
        True,
        False,
    ] and memo.read_bytes() == before


def test_diagnostic_only_campaign_does_not_replace_last_successful_query(
    tmp_path: Path,
) -> None:
    previous = tmp_path / "previous"
    _pack(previous, _KNOWN[0])
    assert _query(previous).exit_code == 0
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()
    current = tmp_path / "current"
    _pack(current / "子地图" / "001", _UNKNOWN[1])
    assert _query(current).exit_code == 2
    assert memo.read_bytes() == before
    again = queries.execute_pack_query(PackQueryCliOptions(str(current), "again", ""))
    assert again.pack == str(previous) and again.exit_code == 0


def test_1500_diagnostic_records_survive_a_result_limit_of_one(tmp_path: Path) -> None:
    count = 1500
    _pack(
        tmp_path / "子地图" / "001",
        "CreateItem(FourCC('I001'),1,2);CreateItem(FourCC('I001'),2,3)",
    )
    _pack(
        tmp_path / "子地图" / "002",
        "\n".join(
            f"CreateItem(FourCC('I002'),Runtime(),{index})" for index in range(count)
        ),
    )
    data = json.loads(_query(tmp_path, "0 0 10", limit=1).render(as_json=True))
    assert len(data["entries"]) == 1 and len(data["spatial_diagnostics"]) == count
    assert len(data["sections"][1]["spatial_diagnostics"]) == count
    assert f"Runtime(),{count - 1})" in data["spatial_diagnostics"][-1]["message"]


def test_many_diagnostic_scopes_and_records_are_not_sampled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = 64
    children = [tmp_path / f"child-{index:03}" for index in range(count)]
    monkeypatch.setattr(queries, "_campaign_subpacks", lambda _pack: children)

    def virtual(pack, query, limit):
        del query, limit
        notes = (
            () if pack == tmp_path else (f"{pack.name}: first", f"{pack.name}: last")
        )
        return SpatialQueryResult(("坐标范围内无确认结果",), spatial_diagnostics=notes)

    monkeypatch.setattr(queries, "_query_near_result", virtual)
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and len(data["sections"]) == count
    assert (
        len(data["checked_packs"]) == count + 1
        and len(data["spatial_diagnostics"]) == count * 2
    )


@pytest.mark.parametrize("query", [None, "", "   "])
def test_cli_missing_near_coordinates_reaches_shared_typed_usage(
    tmp_path: Path, query: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [str(tmp_path), "near"] + ([] if query is None else [query]) + ["--json"]
    options = queries.parse_pack_query_cli_options(argv)
    assert options.query == "" and options.as_json
    assert queries.run_pack_query_cli(options) == 2
    data = json.loads(capsys.readouterr().out)
    assert (
        data["input_error"] and not data["has_matches"] and data["checked_packs"] == []
    )
    assert any("坐标来源" in line for line in data["lines"])


def test_other_keyword_commands_keep_their_required_query(tmp_path: Path) -> None:
    with pytest.raises(queries.PackQueryCliOptionError):
        queries.parse_pack_query_cli_options([str(tmp_path), "price", "--json"])


def test_nonspatial_json_does_not_gain_spatial_status_fields(tmp_path: Path) -> None:
    _pack(tmp_path, _KNOWN[0])
    result = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "stats", ""))
    data = json.loads(result.render(as_json=True))
    assert not {
        "spatial_diagnostics",
        "has_matches",
        "input_error",
        "checked_packs",
    }.intersection(data)

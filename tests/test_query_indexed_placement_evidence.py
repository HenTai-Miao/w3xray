"""Indexed coordinates retain late summaries and every unresolved source site."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_placement_index import indexed_placements
from gametool.script_sources import AnalysisScriptSource

_CALL = "CreateItem(FourCC('I001'),1.25,-2.5)"
_OTHER = "CreateItem(FourCC('I002'),300,400)"
_HEADER = [
    "来源",
    "行号",
    "函数",
    "调用",
    "参数序号",
    "参数",
    "字符串",
    "对象码",
    "机制",
    "用途",
    "摘要",
    "调用偏移",
]


def _indexed(
    summary: str, *, offset: str = "99", source: str = "war3map.lua", line: str = "7"
):
    return ((source, line, "Owner", "CreateItem"), summary, offset)


@pytest.mark.parametrize("blank", ["", " ", "\r\n\t"])
@pytest.mark.parametrize("full_first", [False, True])
def test_empty_mirrors_never_hide_a_complete_call_summary(
    blank: str, full_first: bool
) -> None:
    rows = [_indexed(blank), _indexed(_CALL), _indexed(blank)]
    if full_first:
        rows.reverse()
        rows.insert(0, rows.pop(1))
    report = indexed_placements((), tuple(rows))
    assert report.placements == (("I001", 1.25, -2.5, "item"),)
    assert not report.diagnostics


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_summaries_at_one_offset_never_choose_a_point(
    reverse: bool,
) -> None:
    rows = [_indexed(_CALL), _indexed(_OTHER)]
    if reverse:
        rows.reverse()
    report = indexed_placements((), tuple(rows))
    assert not report.placements
    text = "\n".join(report.diagnostics)
    assert _CALL in text and _OTHER in text
    assert "99" in text and "不一致" in text and "未选择" in text


def test_whitespace_mirrors_share_one_call_without_a_false_conflict() -> None:
    report = indexed_placements(
        (),
        (_indexed(_CALL), _indexed("CreateItem ( FourCC ( 'I001' ) , 1.25 , -2.5 )")),
    )
    assert report.placements == (("I001", 1.25, -2.5, "item"),)
    assert not report.diagnostics


def test_conflict_in_one_call_keeps_other_confirmed_offsets() -> None:
    report = indexed_placements(
        (), (_indexed(_CALL), _indexed(_OTHER), _indexed(_OTHER, offset="199"))
    )
    assert report.placements == (("I002", 300.0, 400.0, "item"),)
    assert len(report.diagnostics) == 1


def test_resolved_aliases_share_conflict_checks_and_preserve_both_provenances() -> None:
    contexts = (
        AnalysisScriptSource("folder/war3map.lua", "function Nothing() end", True),
    )
    rows = (
        _indexed(_CALL, source="folder/war3map.lua"),
        _indexed(_OTHER, source="WAR3MAP.LUA", line="8"),
    )
    report = indexed_placements(contexts, rows)
    assert not report.placements
    text = "\n".join(report.diagnostics)
    assert "folder/war3map.lua" in text and "WAR3MAP.LUA" in text
    assert "行号7" in text and "行号8" in text


@pytest.mark.parametrize(
    "summary", [_CALL.replace("1.25", "Runtime()"), "CreateItem(FourCC('I001'),1/0,0)"]
)
def test_index_only_unknown_geometry_keeps_its_original_source_diagnostic(
    summary: str,
) -> None:
    report = indexed_placements((), (_indexed(summary),))
    assert not report.placements
    text = "\n".join(report.diagnostics)
    assert "war3map.lua" in text and "行号7" in text and "99" in text
    assert summary in text


def test_empty_placement_site_retains_a_recovery_diagnostic() -> None:
    report = indexed_placements((), (_indexed(""),))
    assert not report.placements
    assert report.diagnostics and "摘要" in report.diagnostics[0]
    assert "text" in report.diagnostics[0]


def test_source_mirrors_do_not_duplicate_the_sources_unknown_geometry() -> None:
    summary = _CALL.replace("1.25", "Runtime()")
    contexts = (AnalysisScriptSource("war3map.lua", summary, True),)
    assert not indexed_placements(contexts, (_indexed(summary),)).diagnostics


def test_shadowed_native_is_not_promoted_by_a_late_index_summary() -> None:
    contexts = (
        AnalysisScriptSource(
            "war3map.lua", "local CreateItem=function(...) end;" + _CALL, True
        ),
    )
    report = indexed_placements(contexts, (_indexed(""), _indexed(_CALL)))
    assert not report.placements and not report.diagnostics


def _write(pack: Path, summaries: list[str]) -> Path:
    pack.mkdir(parents=True, exist_ok=True)
    path = pack / "脚本调用参数索引.tsv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerows(
            [
                _HEADER,
                *[
                    [
                        "war3map.lua",
                        "7",
                        "Owner",
                        "CreateItem",
                        str(i),
                        "argument",
                        "",
                        "",
                        "",
                        "",
                        summary,
                        "99",
                    ]
                    for i, summary in enumerate(summaries, 1)
                ],
            ]
        )
    return path


def _near(pack: Path, *, limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "near", "0 0 1000", limit=limit)
    )


def test_public_near_keeps_a_summary_after_empty_argument_rows(tmp_path: Path) -> None:
    path = _write(tmp_path, ["", "", _CALL])
    before = path.read_bytes()
    data = json.loads(_near(tmp_path).render(as_json=True))
    assert data["exit_code"] == 0 and not data["warnings"]
    assert [
        (row["code"], row["x"], row["y"], row["count"]) for row in data["entries"]
    ] == [("I001", 1.25, -2.5, 1)]
    assert path.read_bytes() == before


@pytest.mark.parametrize("limit", [0, 1])
def test_public_near_discloses_complete_conflicts_in_structured_diagnostics(
    tmp_path: Path, limit: int
) -> None:
    _write(tmp_path, [_CALL, _OTHER])
    result = _near(tmp_path, limit=limit)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and not data["entries"] and not data["has_matches"]
    assert not data["input_error"] and data["spatial_diagnostics"]
    text = result.render()
    assert _CALL in text and _OTHER in text


def test_full_source_keeps_its_point_despite_conflicting_index_mirrors(
    tmp_path: Path,
) -> None:
    _write(tmp_path, [_CALL, _OTHER])
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(_CALL, encoding="utf-8")
    data = json.loads(_near(tmp_path).render(as_json=True))
    assert data["exit_code"] == 0 and data["spatial_diagnostics"]
    assert [row["code"] for row in data["entries"]] == ["I001"]


def test_campaign_keeps_diagnostic_only_indexed_scopes(tmp_path: Path) -> None:
    good = tmp_path / "子地图" / "001_good"
    unknown = tmp_path / "子地图" / "002_conflict"
    _write(good, ["", _CALL])
    _write(unknown, [_CALL, _OTHER])
    result = _near(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and result.campaign
    assert [row["code"] for row in data["entries"]] == ["I001"]
    assert any(row["pack"] == str(unknown) for row in data["spatial_diagnostics"])
    assert data["checked_packs"] == [str(tmp_path), str(good), str(unknown)]

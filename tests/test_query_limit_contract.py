"""One explicit-count contract for every query route and CLI full-coverage aliases."""

import csv
import json
from pathlib import Path
from typing import cast

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import (
    PackQueryCliOptions,
    parse_query_limit,
    query_limit_error,
)
from gametool.pack_query_spatial import SpatialSources, query_near


@pytest.fixture(autouse=True)
def isolate_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


class _ForbiddenLock:
    def __enter__(self):
        raise AssertionError("Invalid counts must not wait for the query table lock")

    def __exit__(self, *_args):
        return None


@pytest.mark.parametrize("command", queries._COMMANDS)
@pytest.mark.parametrize("invalid", [-1, True, 1.5, "all", None])
def test_every_query_route_rejects_bad_counts_before_locks_or_data(
    command: str, invalid: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = {"keep": [["original"]]}
    monkeypatch.setattr(queries, "_QUERY_ROWS", sentinel)
    monkeypatch.setattr(queries, "_TABLE_READ_LOCK", _ForbiddenLock())
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, "needle", limit=cast(int, invalid))
    )
    assert (
        result.exit_code == 2
        and "--limit" in result.render()
        and "非负整数" in result.render()
    )
    assert queries._QUERY_ROWS is sentinel and not queries._memo_dir().exists()
    assert result.sections[0].input_error
    assert any(note.startswith("[耗时 ") for note in result.diagnostics)
    if command == "near":
        data = json.loads(result.render(as_json=True))
        assert (
            data["input_error"]
            and not data["has_matches"]
            and data["checked_packs"] == []
        )


@pytest.mark.parametrize("value", [0, 1, 2, 10**100])
def test_nonnegative_integers_have_no_numeric_ceiling(value: int) -> None:
    assert query_limit_error(value) == ""


@pytest.mark.parametrize(
    "value", [False, True, -1, -10, 1.0, float("inf"), float("nan"), "0", "all", None]
)
def test_count_shape_is_explicit_and_does_not_coerce_api_values(value: object) -> None:
    assert "非负整数" in query_limit_error(value)


@pytest.mark.parametrize(
    "spelling", ["all", "ALL", "All", " all ", "全部", " 全部 ", "0", "+0", "-0"]
)
def test_full_coverage_cli_spellings_normalize_to_existing_zero(spelling: str) -> None:
    assert parse_query_limit(spelling) == 0
    options = queries.parse_pack_query_cli_options(
        ["pack", "units", "--limit", spelling]
    )
    assert options.limit == 0 and options.query == ""


@pytest.mark.parametrize("spelling", ["1", "2", "1000", str(10**100)])
def test_cli_positive_counts_remain_exact_without_a_ceiling(spelling: str) -> None:
    assert parse_query_limit(spelling) == int(spelling)


@pytest.mark.parametrize(
    "spelling", ["", "-1", "1.5", "True", "None", "NaN", "allx", "全量"]
)
def test_invalid_cli_counts_remain_friendly_option_errors(spelling: str) -> None:
    with pytest.raises(queries.PackQueryCliOptionError):
        queries.parse_pack_query_cli_options(["pack", "units", "--limit", spelling])


def test_all_is_an_ordinary_search_word_without_the_limit_flag() -> None:
    options = queries.parse_pack_query_cli_options(["pack", "text", "all"])
    assert options.query == "all" and options.limit == 0


def _objects(pack: Path, table: str, count: int, description: str = "完整说明") -> None:
    parent = pack / "对象ID"
    parent.mkdir(parents=True, exist_ok=True)
    with (parent / f"{table}.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"])
        for index in range(count):
            code = f"u{index:03x}"
            writer.writerow(
                [
                    table,
                    code,
                    index,
                    code,
                    f"对象{index}",
                    "是",
                    f"{description}:{index}",
                ]
            )


@pytest.mark.parametrize(
    "command,table", [("units", "单位"), ("skills", "技能"), ("buffs", "增益")]
)
def test_default_and_explicit_full_modes_keep_every_record(
    tmp_path: Path, command: str, table: str
) -> None:
    count = 1200
    _objects(tmp_path, table, count)
    defaults = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, "")
    )
    text = defaults.render()
    assert defaults.exit_code == 0 and all(
        f"[u{index:03x}]" in text for index in range(count)
    )
    for spelling in ["0", "all", "全部"]:
        options = queries.parse_pack_query_cli_options(
            [str(tmp_path), command, "--limit", spelling]
        )
        full = queries.execute_pack_query(options)
        assert full.render() == text and "其余" not in full.render()


def test_one_explicit_record_keeps_all_embedded_description_lines(
    tmp_path: Path,
) -> None:
    description = "\n".join(f"完整说明行{index}" for index in range(1000))
    _objects(tmp_path, "单位", 2, description)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "units", "", limit=1)
    )
    assert (
        result.exit_code == 0
        and "[u000]" in result.render()
        and "[u001]" not in result.render()
    )
    assert "完整说明行999" in result.render() and "其余 1 条未显示" in result.render()


def test_invalid_count_does_not_replace_successful_query_memory(tmp_path: Path) -> None:
    _objects(tmp_path, "单位", 2)
    assert (
        queries.execute_pack_query(
            PackQueryCliOptions(str(tmp_path), "units", "")
        ).exit_code
        == 0
    )
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()
    for command in ["units", "again", "diff", "near"]:
        result = queries.execute_pack_query(
            PackQueryCliOptions(str(tmp_path), command, "", limit=-1)
        )
        assert result.exit_code == 2 and memo.read_bytes() == before


def test_again_can_explicitly_request_full_coverage(tmp_path: Path) -> None:
    _objects(tmp_path, "单位", 3)
    first = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "units", "", limit=1)
    )
    assert "[u002]" not in first.render()
    options = queries.parse_pack_query_cli_options(
        [str(tmp_path), "again", "--limit", "all"]
    )
    result = queries.execute_pack_query(options)
    assert result.exit_code == 0 and all(
        f"[u{index:03x}]" in result.render() for index in range(3)
    )


def test_direct_spatial_backend_uses_the_same_invalid_count_contract(
    tmp_path: Path,
) -> None:
    # The guard returns before consulting this backend surface.
    result = query_near(tmp_path, "0 0 1", -1, cast(SpatialSources, object()))
    assert result.input_error and result.lines == (query_limit_error(-1),)

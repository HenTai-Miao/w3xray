"""Quest evidence follows declared call columns, never words inside its text."""

import csv
import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_APIS = (
    "CreateQuestBJ",
    "QuestSetTitle",
    "QuestSetTitleBJ",
    "QuestSetDescription",
    "QuestSetDescriptionBJ",
    "CreateQuestItemBJ",
    "QuestItemSetDescription",
    "QuestItemSetDescriptionBJ",
    "QuestMessageBJ",
    "CreateDefeatConditionBJ",
    "DefeatConditionSetDescription",
    "DefeatConditionSetDescriptionBJ",
    "DisplayTextToPlayer",
    "DisplayTimedTextToPlayer",
    "DisplayTimedTextFromPlayer",
    "DisplayTextToForce",
    "DisplayTimedTextToForce",
)
_HEADER = [
    "来源",
    "行号",
    "函数",
    "调用",
    "用途",
    "字符串",
    "解析文本",
    "摘要",
    "源码偏移",
]
_LAYOUTS = (
    "canonical",
    "reordered",
    "english",
    "minimal",
    "legacy8",
    "legacy4",
    "legacy2",
)


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(pack: Path, rows: list[list[str]]) -> Path:
    path = pack / "脚本字符串索引.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)
    return path


def _row(call: str, body: str, *, function: str = "Init", line: str = "1") -> list[str]:
    return ["war3map.j", line, function, call, "字符串", body, "", "完整摘要", "999"]


def _layout(
    call: str, body: str, layout: str, *, function: str = "Init"
) -> list[list[str]]:
    row = _row(call, body, function=function)
    if layout == "reordered":
        order = [5, 3, 0, 8, 2, 1, 6, 4, 7]
        return [[_HEADER[i] for i in order], [row[i] for i in order]]
    if layout == "english":
        return [
            ["TEXT", "API", "LINE_NUMBER", "SOURCE", "FUNCTION", "SUMMARY"],
            [body, call, "1", "war3map.j", function, "完整摘要"],
        ]
    if layout == "minimal":
        return [["文本", "调用"], [body, call]]
    if layout == "legacy8":
        return [row[:8]]
    if layout == "legacy4":
        return [[row[0], row[1], call, body]]
    if layout == "legacy2":
        return [[call, body]]
    return [_HEADER, row]


def _run(pack: Path, query: str, limit: int = 0, command: str = "quest"):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, query, limit=limit)
    )


@pytest.mark.parametrize("api", _APIS)
@pytest.mark.parametrize("layout", _LAYOUTS)
def test_every_standard_text_api_and_supported_layout_keeps_first_record(
    tmp_path: Path, api: str, layout: str
) -> None:
    path = _write(tmp_path, _layout(api, '任务开头\n独有"尾部"\t完整', layout))
    before = path.read_bytes()
    result = _run(tmp_path, '独有"尾部"\t完整', 1)
    assert result.exit_code == 0 and api in result.render()
    assert "已达 --limit" not in result.render()
    assert not json.loads(result.render(as_json=True))["warnings"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("layout", ["canonical", "reordered", "legacy8"])
@pytest.mark.parametrize(
    "call",
    [
        "BJDebugMsg",
        "CreateQuestBJExtra",
        "my.QuestSetDescription",
        "questsetdescription",
        "MyCreateQuestBJ",
        "GetPlayerName",
    ],
)
def test_words_and_owner_functions_never_masquerade_as_quest_calls(
    tmp_path: Path, layout: str, call: str
) -> None:
    _write(
        tmp_path,
        _layout(
            call,
            "伪造任务 CreateQuestBJ DisplayTimedTextToForce",
            layout,
            function="CreateQuestBJ",
        ),
    )
    result = _run(tmp_path, "伪造任务")
    assert result.exit_code == 2 and "共 0 条" in result.render()
    assert not json.loads(result.render(as_json=True))["warnings"]
    assert _run(tmp_path, "伪造任务", command="text").exit_code == 0


@pytest.mark.parametrize(
    "api",
    ["QuestSetDescription", "QuestItemSetDescriptionBJ", "DisplayTimedTextToPlayer"],
)
def test_explicit_standard_global_names_are_known_calls(
    tmp_path: Path, api: str
) -> None:
    _write(tmp_path, [_HEADER, _row("_G." + api, "标准全局任务正文")])
    result = _run(tmp_path, "标准全局任务正文")
    assert result.exit_code == 0 and "_G." + api in result.render()


@pytest.mark.parametrize(
    "header",
    [
        ["来源", "行号", "函数", "文本"],
        ["来源", "行号", "调用", "CALL", "文本"],
        ["来源", "行号", "API", "调用", "文本"],
    ],
)
def test_missing_or_ambiguous_call_columns_are_source_diagnostics(
    tmp_path: Path, header: list[str]
) -> None:
    row = ["war3map.j", "1", "CreateQuestBJ", "QuestSetTitle", "未确认任务"]
    _write(tmp_path, [header, row[: len(header)]])
    result = _run(tmp_path, "")
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["warnings"]
    assert "调用" in "\n".join(data["warnings"])
    assert "未猜测" in "\n".join(data["warnings"])
    assert all(
        "脚本字符串索引.tsv" in note and str(tmp_path) in note
        for note in data["warnings"]
    )
    assert "text <词>" in result.render()


@pytest.mark.parametrize(
    "rows",
    [
        [["war3map.j", "1", "CreateQuestBJ"]],
        [['call CreateQuestBJ(1,"不能猜列的文本","描述","icon")']],
        [["未知列", "调用"]],
    ],
)
def test_unknown_shapes_keep_explicit_diagnostics_and_fulltext_route(
    tmp_path: Path, rows: list[list[str]]
) -> None:
    _write(tmp_path, rows)
    result = _run(tmp_path, "")
    assert result.exit_code == 2
    assert json.loads(result.render(as_json=True))["warnings"]
    assert "text <词>" in result.render()


@pytest.mark.parametrize("limit", [0, 1, 17, 34, 35])
def test_limits_count_all_known_calls_and_exclude_false_positives(
    tmp_path: Path, limit: int
) -> None:
    rows = [_HEADER]
    rows.extend(
        _row(api, f"命中{index}-{copy}\n完整尾部")
        for index, api in enumerate(_APIS)
        for copy in range(2)
    )
    rows.extend(
        [
            _row("BJDebugMsg", "命中假条目 CreateQuestBJ"),
            _row("GetPlayerName", "命中假条目", function="CreateQuestBJ"),
        ]
    )
    _write(tmp_path, rows)
    result = _run(tmp_path, "命中", limit)
    data = json.loads(result.render(as_json=True))
    shown = min(limit, 34) if limit else 34
    assert result.exit_code == 0
    assert len(data["lines"]) == shown + int(shown < 34)
    assert all("完整尾部" in line for line in data["lines"][:shown])
    assert "假条目" not in result.render()
    if shown < 34:
        assert f"其余 {34 - shown} 条未显示" in data["lines"][-1]


def test_short_rows_keep_confirmed_records_and_logical_indices(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            _HEADER,
            _row("QuestSetTitle", "命中\n" * 5000),
            ["source", "2", "CreateQuestBJ"],
            _row("QuestSetDescription", "命中末项"),
        ],
    )
    result = _run(tmp_path, "命中", 1)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and "其余 1 条未显示" in result.render()
    assert any("记录序号: 3" in note for note in data["warnings"])
    assert "命中末项" not in result.render()


def test_every_bad_record_index_is_visible_without_a_count_cap(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            _HEADER,
            *[["source", str(index), "CreateQuestBJ"] for index in range(5000)],
            _row("QuestSetDescription", "唯一确认任务"),
        ],
    )
    result = _run(tmp_path, "唯一确认任务", 1)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0
    assert ", ".join(map(str, range(2, 5002))) in "\n".join(data["warnings"])


def test_wide_declared_call_column_does_not_pad_sparse_rows(tmp_path: Path) -> None:
    header = ["来源", "行号", *[f"扩展{i}" for i in range(20000)], "调用", "文本"]
    row = ["war3map.j", "1", *[""] * 20000, "QuestSetDescription", "宽表末尾任务"]
    _write(tmp_path, [header, ["source", "1"], row])
    result = _run(tmp_path, "宽表末尾任务", 1)
    assert result.exit_code == 0
    assert any(
        "记录序号: 2" in note
        for note in json.loads(result.render(as_json=True))["warnings"]
    )


@pytest.mark.parametrize("layout", ["legacy2", "legacy4"])
def test_legacy_data_named_like_headers_is_not_skipped(
    tmp_path: Path, layout: str
) -> None:
    rows = _layout("CreateQuestBJ", "调用", layout)
    if layout == "legacy4":
        rows[0][0] = "来源"
    _write(tmp_path, rows)
    result = _run(tmp_path, "调用")
    assert (
        result.exit_code == 0
        and not json.loads(result.render(as_json=True))["warnings"]
    )


def test_declared_empty_call_is_known_non_call_text(tmp_path: Path) -> None:
    _write(tmp_path, [_HEADER, _row("", "CreateQuestBJ 只是全局字符串")])
    result = _run(tmp_path, "")
    assert result.exit_code == 2 and "共 0 条" in result.render()
    assert not json.loads(result.render(as_json=True))["warnings"]


def test_campaign_native_calls_are_kept_and_plain_mentions_are_excluded(
    tmp_path: Path,
) -> None:
    for child, call in [
        ("001", "QuestSetTitle"),
        ("002", "QuestSetDescription"),
        ("003", "BJDebugMsg"),
    ]:
        _write(
            tmp_path / "子地图" / child,
            [_HEADER, _row(call, "任务词 CreateQuestBJ\n完整尾部")],
        )
    result = _run(tmp_path, "任务词", 1)
    assert result.exit_code == 0 and result.campaign
    assert len(result.sections) == 2
    assert "003" not in result.render()
    assert all("完整尾部" in "\n".join(section.lines) for section in result.sections)


@pytest.mark.parametrize("lua", [False, True])
def test_real_string_index_export_reaches_native_quest_query(
    tmp_path: Path, lua: bool
) -> None:
    from gametool.api import MapData
    from gametool.script_string_index import (
        build_script_string_index,
        format_script_string_index_tsv,
    )

    md = MapData(path="synthetic.w3x", name="任务索引测试")
    source = "war3map.lua" if lua else "war3map.j"
    md.scripts = {
        source: (
            "function Init()\n QuestSetDescription(nil, [[原生任务\n独有导出尾部]])\nend"
            if lua
            else 'function Init takes nothing returns nothing\n call QuestSetDescription(null,"原生任务独有导出尾部")\nendfunction'
        )
    }
    path = tmp_path / "脚本字符串索引.tsv"
    path.write_text(
        format_script_string_index_tsv(build_script_string_index(md)),
        encoding="utf-8-sig",
    )
    result = _run(tmp_path, "独有导出尾部")
    assert result.exit_code == 0
    assert source in result.render() and "QuestSetDescription" in result.render()
    assert not json.loads(result.render(as_json=True))["warnings"]


def test_blank_records_before_header_keep_original_diagnostic_indices(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        [
            [],
            ["", ""],
            _HEADER,
            _row("QuestSetTitle", "已确认任务"),
            ["source", "1", "CreateQuestBJ"],
        ],
    )
    result = _run(tmp_path, "已确认任务")
    assert result.exit_code == 0
    assert any(
        "记录序号: 5" in note
        for note in json.loads(result.render(as_json=True))["warnings"]
    )


def test_bad_first_legacy_record_does_not_hide_later_known_call(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [["source", "1", "CreateQuestBJ"], _row("QuestSetDescription", "后续确认任务")],
    )
    result = _run(tmp_path, "后续确认任务")
    assert result.exit_code == 0
    assert any(
        "记录序号: 1" in note
        for note in json.loads(result.render(as_json=True))["warnings"]
    )


def test_every_duplicate_declared_call_column_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            ["来源", "行号", *["调用"] * 5000, "文本"],
            ["source", "1", "CreateQuestBJ", "未确认"],
        ],
    )
    result = _run(tmp_path, "")
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2
    assert ", ".join(map(str, range(3, 5003))) in "\n".join(data["warnings"])


@pytest.mark.parametrize("extra", [[], [""], ["--limit", "1"], ["--limit", "all"]])
def test_cli_empty_keyword_lists_complete_confirmed_quests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str]
) -> None:
    _write(
        tmp_path,
        [
            _HEADER,
            _row("QuestSetTitle", "首个任务"),
            _row("QuestSetDescription", "第二任务\n完整尾部"),
        ],
    )
    options = queries.parse_pack_query_cli_options(
        [str(tmp_path), "quest", *extra, "--json"]
    )
    assert options.query == ""
    assert queries.run_pack_query_cli(options) == 0
    data = json.loads(capsys.readouterr().out)
    assert "首个任务" in "\n".join(data["lines"])
    if extra == ["--limit", "1"]:
        assert "其余 1 条未显示" in data["lines"][-1]
        assert "第二任务" not in "\n".join(data["lines"])
    else:
        assert "第二任务" in "\n".join(data["lines"]) and "完整尾部" in "\n".join(
            data["lines"]
        )


def test_cli_empty_keyword_miss_is_structured_json_with_recovery(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, [_HEADER, _row("BJDebugMsg", "CreateQuestBJ 只是介绍")])
    options = queries.parse_pack_query_cli_options([str(tmp_path), "quest", "--json"])
    assert queries.run_pack_query_cli(options) == 2
    data = json.loads(capsys.readouterr().out)
    assert not data["warnings"] and "共 0 条" in "\n".join(data["lines"])
    assert "text <词>" in "\n".join(data["lines"])


def test_again_replays_an_empty_keyword_quest_listing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, [_HEADER, _row("QuestSetDescription", "全量任务正文")])
    options = queries.parse_pack_query_cli_options([str(tmp_path), "quest", "--json"])
    assert queries.run_pack_query_cli(options) == 0
    capsys.readouterr()
    again = queries.parse_pack_query_cli_options([str(tmp_path), "again", "--json"])
    assert queries.run_pack_query_cli(again) == 0
    data = json.loads(capsys.readouterr().out)
    assert "全量任务正文" in "\n".join(data["lines"])
    assert "[重跑] quest" in "\n".join(data["lines"])

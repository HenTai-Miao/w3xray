"""Text and quest limits count complete logical records, preserving raw evidence."""

import csv
import io
import json
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool import pack_query_text_records as records
from gametool.pack_query_options import PackQueryCliOptions

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


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(
    path: Path,
    rows: list[list[str]],
    *,
    signature: bool = False,
    ending: str = "\n",
    quoted: bool = False,
) -> list[str]:
    encoded: list[str] = []
    for row in rows:
        stream = io.StringIO(newline="")
        csv.writer(
            stream,
            delimiter="\t",
            lineterminator=ending,
            quoting=csv.QUOTE_ALL if quoted else csv.QUOTE_MINIMAL,
        ).writerow(row)
        encoded.append(stream.getvalue()[: -len(ending)])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (b"\xef\xbb\xbf" if signature else b"")
        + (ending.join(encoded) + ending).encode()
    )
    return encoded


def _run(pack: Path, command: str, query: str, limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, query, limit=limit)
    )


def _row(index: int, body: str) -> list[str]:
    return [
        "war3map.j",
        str(index),
        "Init",
        "CreateQuestBJ",
        "任务",
        body,
        "",
        "完整摘要",
        str(index * 100),
    ]


@pytest.mark.parametrize("command", ["quest", "text"])
@pytest.mark.parametrize("signature", [False, True])
@pytest.mark.parametrize("quoted", [False, True])
@pytest.mark.parametrize("limit", [0, 1, 2, 3])
def test_complete_multiline_records_and_exact_limits(
    tmp_path: Path, command: str, signature: bool, quoted: bool, limit: int
) -> None:
    path = tmp_path / "脚本字符串索引.tsv"
    raw = _write(
        path,
        [
            _HEADER,
            *[
                _row(index, f'命中{index}\n命中正文\t"引号"\n命中尾部{index}')
                for index in range(3)
            ],
        ],
        signature=signature,
        quoted=quoted,
    )
    before = path.read_bytes()
    result = _run(tmp_path, command, "命中", limit)
    data = json.loads(result.render(as_json=True))
    shown = min(limit, 3) if limit else 3
    prefix = path.name + ": " if command == "text" else ""
    assert result.exit_code == 0 and not data["warnings"]
    assert data["lines"][:shown] == [prefix + text for text in raw[1 : shown + 1]]
    assert len(data["lines"]) == shown + int(shown < 3)
    if shown < 3:
        assert f"其余 {3 - shown} 条未显示" in data["lines"][-1]
    assert path.read_bytes() == before


@pytest.mark.parametrize("command", ["quest", "text"])
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize("signature", [False, True])
def test_tail_only_matches_keep_original_newlines_and_every_cell(
    tmp_path: Path, command: str, ending: str, signature: bool
) -> None:
    path = tmp_path / "脚本字符串索引.tsv"
    raw = _write(
        path,
        [_HEADER, _row(1, ending.join(["任务开头", "独有尾部", "最终结束"]))],
        ending=ending,
        signature=signature,
    )
    result = _run(tmp_path, command, "独有尾部")
    assert result.exit_code == 0
    assert raw[1] in result.render()
    assert "最终结束" in result.render()


@pytest.mark.parametrize("command", ["quest", "text"])
@pytest.mark.parametrize("quoted", [False, True])
def test_decoded_quote_and_tab_queries_keep_raw_evidence(
    tmp_path: Path, command: str, quoted: bool
) -> None:
    path = tmp_path / "脚本字符串索引.tsv"
    phrase = '独有"引号"\t尾部'
    raw = _write(path, [_HEADER, _row(1, "开头\n" + phrase + "\n结束")], quoted=quoted)
    assert phrase not in raw[1]
    result = _run(tmp_path, command, phrase)
    assert result.exit_code == 0 and raw[1] in result.render()


@pytest.mark.parametrize("command", ["quest", "text"])
@pytest.mark.parametrize("limit", [0, 1, 2])
def test_one_long_record_is_never_truncated_by_physical_line_count(
    tmp_path: Path, command: str, limit: int
) -> None:
    body = '命中\t"完整"\r\n' * 40_000 + "完整最后一行"
    path = tmp_path / "脚本字符串索引.tsv"
    raw = _write(path, [["war3map.j", "1", "CreateQuestBJ", body]])
    previous_limit = csv.field_size_limit()
    result = _run(tmp_path, command, "命中", limit)
    assert result.exit_code == 0 and raw[0] in result.render()
    assert "已达 --limit" not in result.render()
    assert csv.field_size_limit() == previous_limit


@pytest.mark.parametrize("command", ["quest", "text"])
@pytest.mark.parametrize("signature", [False, True])
def test_headerless_legacy_first_record_remains_complete(
    tmp_path: Path, command: str, signature: bool
) -> None:
    path = tmp_path / "脚本字符串索引.tsv"
    raw = _write(
        path,
        [["war3map.j", "1", "CreateQuestBJ", "开头\n独有尾部"]],
        signature=signature,
    )
    result = _run(tmp_path, command, "独有尾部", 1)
    assert result.exit_code == 0 and raw[0] in result.render()
    assert "已达 --limit" not in result.render()


@pytest.mark.parametrize("limit", [0, 1, 3, 4])
def test_text_limits_cover_complete_records_across_files(
    tmp_path: Path, limit: int
) -> None:
    expected: list[str] = []
    for filename, count in [("a.tsv", 2), ("b.tsv", 1)]:
        path = tmp_path / filename
        raw = _write(path, [["来源", f"命中{i}\n命中尾部{i}"] for i in range(count)])
        expected.extend(filename + ": " + text for text in raw)
    result = _run(tmp_path, "text", "命中", limit)
    lines = json.loads(result.render(as_json=True))["lines"]
    shown = min(limit, 3) if limit else 3
    assert lines[:shown] == expected[:shown]
    assert len(lines) == shown + int(shown < 3)
    if shown < 3:
        assert f"其余 {3 - shown} 条未显示" in lines[-1]


def test_quest_miss_counts_logical_records_once(tmp_path: Path) -> None:
    path = tmp_path / "脚本字符串索引.tsv"
    _write(path, [_HEADER, _row(1, "开头\nCreateQuestBJ\n结束"), _row(2, "另一条任务")])
    result = _run(tmp_path, "quest", "未记录的词")
    assert result.exit_code == 2
    assert "本次可确认任务文本共 2 条" in result.render()
    assert "text <词>" in result.render()


@pytest.mark.parametrize("limit", [0, 1, 5])
def test_empty_text_query_keeps_headers_blank_records_and_source_order(
    tmp_path: Path, limit: int
) -> None:
    path = tmp_path / "all.tsv"
    raw = _write(path, [["名称", "值"], [], ["首项", "正文\n尾部"], ["末项", ""]])
    result = _run(tmp_path, "text", "", limit)
    lines = json.loads(result.render(as_json=True))["lines"]
    shown = min(limit, 4) if limit else 4
    assert lines[:shown] == [path.name + ": " + text for text in raw[:shown]]
    assert len(lines) == shown + int(shown < 4)


@pytest.mark.parametrize("command", ["quest", "text"])
def test_same_size_mtime_edits_refresh_full_records(
    tmp_path: Path, command: str
) -> None:
    path = tmp_path / "脚本字符串索引.tsv"
    _write(path, [_row(1, "开头\n独有旧值\n尾部")], signature=True)
    before = path.stat()
    assert _run(tmp_path, command, "独有旧值").exit_code == 0
    path.write_bytes(path.read_bytes().replace("旧值".encode(), "新值".encode()))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    result = _run(tmp_path, command, "独有新值")
    assert result.exit_code == 0 and "独有新值" in result.render()
    assert _run(tmp_path, command, "独有旧值").exit_code == 2


def test_record_iterator_restores_csv_settings_before_yield_and_close() -> None:
    previous = csv.field_size_limit()
    iterator = records.tsv_records(['来源\t"完整\n正文"\n', "末项\t尾部\n"])
    try:
        csv.field_size_limit(1)
        record = next(iterator)
        assert record.cells == ("来源", "完整\n正文")
        assert record.text == '来源\t"完整\n正文"'
        assert csv.field_size_limit() == 1
        iterator.close()
        assert csv.field_size_limit() == 1
    finally:
        csv.field_size_limit(previous)
        iterator.close()


@pytest.mark.parametrize("command", ["quest", "text"])
@pytest.mark.parametrize("query", ["命中", "未记录的词"])
def test_parser_error_retains_confirmed_rows_and_source_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, query: str
) -> None:
    path = tmp_path / "脚本字符串索引.tsv"
    path.write_text("源数据\n", encoding="utf-8")

    def broken(_lines):
        yield records.TextRecord(("CreateQuestBJ", "命中"), "CreateQuestBJ\t命中")
        raise csv.Error("fixture parser error")

    monkeypatch.setattr(records, "tsv_records", broken)
    result = _run(tmp_path, command, query)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == (0 if query == "命中" else 2)
    assert any(
        path.name in note and "fixture parser error" in note
        for note in data["warnings"]
    )
    assert all(str(tmp_path) in note for note in data["warnings"])
    if query == "命中":
        assert "CreateQuestBJ\t命中" in result.render()


@pytest.mark.parametrize("command", ["quest", "text"])
def test_campaign_limits_keep_each_child_record_complete(
    tmp_path: Path, command: str
) -> None:
    for child in ("001", "002"):
        pack = tmp_path / "子地图" / child
        _write(
            pack / "脚本字符串索引.tsv",
            [_HEADER, _row(1, f"命中{child}\n独有尾部{child}")],
            signature=True,
        )
    result = _run(tmp_path, command, "命中", 1)
    assert result.exit_code == 0 and result.campaign
    assert len(result.sections) == 2
    assert all("独有尾部" in "\n".join(section.lines) for section in result.sections)
    assert "已达 --limit" not in result.render()


def test_text_campaign_discovers_any_root_tsv_index(tmp_path: Path) -> None:
    for child in ("001", "002"):
        _write(
            tmp_path / "子地图" / child / "独立证据索引.tsv",
            [["来源", f"命中{child}\n尾部{child}"]],
        )
    result = _run(tmp_path, "text", "命中", 1)
    assert result.exit_code == 0 and result.campaign
    assert len(result.sections) == 2
    assert all("尾部" in "\n".join(section.lines) for section in result.sections)


@pytest.mark.parametrize("command", ["quest", "text"])
def test_changed_source_snapshot_is_discarded_before_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    path = tmp_path / "脚本字符串索引.tsv"
    _write(path, [_row(1, "命中旧值\n尾部")])
    before = path.stat()
    original_fstat = os.fstat
    calls = 0

    def mutate_after_read(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_bytes(
                path.read_bytes().replace("旧值".encode(), "新值".encode())
            )
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        return original_fstat(descriptor)

    monkeypatch.setattr(queries.os, "fstat", mutate_after_read)
    result = _run(tmp_path, command, "命中")
    assert result.exit_code == 0
    assert "命中新值" in result.render() and "命中旧值" not in result.render()
    assert calls >= 4


@pytest.mark.parametrize("command", ["quest", "text"])
def test_unstable_source_discloses_missing_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    path = tmp_path / "脚本字符串索引.tsv"
    _write(path, [_row(1, "命中旧值\n尾部")])
    calls = 0

    def changed_identity(_stat):
        nonlocal calls
        calls += 1
        return (calls, calls, calls, calls)

    monkeypatch.setattr(queries, "_table_identity", changed_identity)
    result = _run(tmp_path, command, "命中")
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["warnings"]
    assert all(path.name in note for note in data["warnings"])
    assert "命中旧值" not in result.render()


@pytest.mark.parametrize("query", ["命中", "未记录的词"])
def test_quest_reads_its_source_once_even_on_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    path = tmp_path / "脚本字符串索引.tsv"
    _write(path, [_row(1, "命中\n尾部")])
    original = queries._iter_tsv_lines
    calls: list[Path] = []

    def tracked(source, **kwargs):
        calls.append(source)
        yield from original(source, **kwargs)

    monkeypatch.setattr(queries, "_iter_tsv_lines", tracked)
    result = _run(tmp_path, "quest", query)
    assert result.exit_code == (0 if query == "命中" else 2)
    assert calls == [path]


@pytest.mark.parametrize("command", ["quest", "text"])
def test_explicit_limit_renders_only_selected_complete_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    path = tmp_path / "脚本字符串索引.tsv"
    _write(path, [_row(index, f"命中完整记录标记{index}\n尾部") for index in range(3)])
    original = queries._clean
    rendered: list[str] = []

    def tracked(value: str) -> str:
        if "完整记录标记" in value:
            rendered.append(value)
        return original(value)

    monkeypatch.setattr(queries, "_clean", tracked)
    result = _run(tmp_path, command, "命中", 1)
    assert result.exit_code == 0 and "其余 2 条未显示" in result.render()
    assert len(rendered) == 1 and "完整记录标记0" in rendered[0]

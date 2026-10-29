"""Complete source calls and original index provenance in isolated packs."""

from dataclasses import asdict
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
from typing import cast

import pytest

from gametool.pack_query_script_calls import query_script_calls
from gametool.script_call_query_models import ScriptCallQueryResult


HEADER = (
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
)


def _source(
    pack: Path, text: str, *, name: str = "war3map.lua", original: bool = True
) -> Path:
    path = pack / ("脚本原始文本" if original else "脚本可读文本") / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _index(
    pack: Path,
    rows: list[tuple[str, ...]],
    *,
    header: tuple[str, ...] = HEADER,
    bom: bool = False,
) -> Path:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\r\n")
    writer.writerows((header, *rows))
    path = pack / "脚本调用参数索引.tsv"
    path.write_bytes(
        ("\ufeff" if bom else "").encode("utf-8") + output.getvalue().encode("utf-8")
    )
    return path


def _row(
    source: str,
    callee: str,
    position: str,
    value: str,
    summary: str,
    offset: str,
    *,
    owner: str = "",
    extras: tuple[str, ...] = (),
) -> tuple[str, ...]:
    return (
        source,
        "1",
        owner,
        callee,
        position,
        value,
        "",
        "",
        "",
        "",
        summary,
        offset,
        *extras,
    )


def _source_calls(result: ScriptCallQueryResult):
    return tuple(record for record in result.calls if record.origin == "source")


def test_empty_query_keeps_zero_argument_and_duplicate_call_sites(
    tmp_path: Path,
) -> None:
    text = "GetLocalPlayer()\nKillUnit(u)\nKillUnit(u)\n"
    _source(tmp_path, text)
    result = query_script_calls(tmp_path, "")
    records = _source_calls(result)
    assert len(records) == result.total == 3
    assert records[0].arguments == ()
    assert records[1].offset != records[2].offset
    assert all(record.call is not None for record in records)
    assert result.has_matches and result.source_stable and not result.input_error
    assert result.omitted == 0


def test_boolean_search_preserves_fields_and_full_control_evidence(
    tmp_path: Path,
) -> None:
    text = "function award()\n if gate then SetPlayerState(p, PLAYER_STATE_RESOURCE_GOLD, 123) end\nend"
    _source(tmp_path, text)
    result = query_script_calls(tmp_path, "award && 123")
    assert result.total == 1
    record = result.calls[0]
    assert record.arguments == ("p", "PLAYER_STATE_RESOURCE_GOLD", "123")
    assert record.call is not None and record.call.controls
    assert record.call.controls[0].predicates[0].raw.strip() == "gate"
    assert query_script_calls(tmp_path, '="awardSetPlayerState"').total == 0
    assert query_script_calls(tmp_path, "gate && 123").total == 1
    payload = json.loads(json.dumps(asdict(result), ensure_ascii=False))
    assert (
        payload["calls"][0]["call"]["controls"][0]["predicates"][0]["raw"].strip()
        == "gate"
    )


def test_limit_selects_complete_calls_and_keeps_global_diagnostics(
    tmp_path: Path,
) -> None:
    _source(tmp_path, "SetPlayerState(p, gold, 23)\nUnknownOutside()\nKillUnit(u)")
    result = query_script_calls(tmp_path, "", 1)
    assert result.total == 3 and result.omitted == 2 and len(result.calls) == 1
    assert result.calls[0].arguments == ("p", "gold", "23")
    assert any("UnknownOutside" in note.raw for note in result.diagnostics)
    assert "其余 2 条" in "\n".join(result.lines)


def test_original_source_owns_crlf_offsets_and_full_file_fingerprint(
    tmp_path: Path,
) -> None:
    text = '\ufeffGetLocalPlayer()\r\nDisplayTextToPlayer(p,0,0,"TRIGSTR_1")\r\n'
    path = _source(tmp_path, text)
    _source(tmp_path, text.replace("TRIGSTR_1", "不同长度的翻译文本"), original=False)
    result = query_script_calls(tmp_path, "TRIGSTR_1")
    record = result.calls[0]
    assert record.offset == str(text.index("DisplayTextToPlayer"))
    assert record.raw == 'DisplayTextToPlayer(p,0,0,"TRIGSTR_1")'
    assert (
        record.source_file_fingerprint == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert record.call is not None
    assert (
        record.call.source_fingerprint
        == hashlib.sha256(text.encode("utf-8")).hexdigest()
    )
    assert "不同长度" not in "\n".join(result.lines)


def test_reordered_bom_index_preserves_original_cell_order_and_full_extensions(
    tmp_path: Path,
) -> None:
    text = "KillUnit(u)"
    _source(tmp_path, text)
    extra = 'extra\t完整\nCRLF\r\n"quoted"\ufeff尾'
    header = (
        "附加",
        "调用偏移",
        "摘要",
        "参数",
        "参数序号",
        "调用",
        "来源",
        "行号",
        "函数",
    )
    values = (extra, "000", text, "u", "1", "KillUnit", "WAR3MAP.LUA", "1", "")
    _index(tmp_path, [values], header=header, bom=True)
    result = query_script_calls(tmp_path, "完整")
    assert result.total == 1 and result.calls[0].origin == "source"
    row = result.calls[0].index_rows[0]
    assert row.ordinal == 2 and row.cells == values
    assert extra in row.cells
    assert row.semantic_cells[0] == "WAR3MAP.LUA"
    assert row.semantic_cells[3] == "KillUnit"
    assert '"quoted"' in row.cells[0]


def test_interleaved_explicit_offsets_attach_all_arguments_to_correct_source_calls(
    tmp_path: Path,
) -> None:
    first = "SetPlayerState(p, gold, 10)"
    second = "SetPlayerState(q, lumber, 20)"
    text = first + "\n" + second
    _source(tmp_path, text)
    rows = []
    for position, a, b in (("1", "p", "q"), ("2", "gold", "lumber"), ("3", "10", "20")):
        rows.append(
            _row(
                "war3map.lua",
                "SetPlayerState",
                position,
                a,
                first if position == "1" else "",
                "0",
            )
        )
        rows.append(
            _row(
                "war3map.lua",
                "SetPlayerState",
                position,
                b,
                second if position == "1" else "",
                str(len(first) + 1),
            )
        )
    _index(tmp_path, rows)
    result = query_script_calls(tmp_path, "")
    assert result.total == 2
    assert [len(record.index_rows) for record in result.calls] == [3, 3]
    assert [row.ordinal for row in result.calls[0].index_rows] == [2, 4, 6]
    assert [row.ordinal for row in result.calls[1].index_rows] == [3, 5, 7]


def test_conflicting_index_retains_source_binding_and_every_original_row(
    tmp_path: Path,
) -> None:
    text = "local _G = {}\n_G.KillUnit(u)"
    _source(tmp_path, text)
    offset = str(text.index("_G.KillUnit"))
    _index(
        tmp_path,
        [
            _row(
                "war3map.lua",
                "KillUnit",
                "1",
                "different",
                "KillUnit(different)",
                offset,
            ),
            _row(
                "war3map.lua",
                "CreateItem",
                "1",
                "conflict",
                "CreateItem(conflict)",
                offset,
            ),
        ],
    )
    result = query_script_calls(tmp_path, "")
    assert result.total == 1
    record = result.calls[0]
    assert record.binding == "unknown"
    assert record.arguments == ("u",) and record.raw == "_G.KillUnit(u)"
    assert len(record.index_rows) == 2
    assert any(note.code == "index.conflict" for note in result.diagnostics)
    assert result.script_coverage.complete is False


def test_identical_source_calls_are_not_collapsed_by_one_legacy_index(
    tmp_path: Path,
) -> None:
    _source(tmp_path, "KillUnit(u)\nKillUnit(u)", original=False)
    _index(tmp_path, [_row("war3map.lua", "KillUnit", "1", "u", "KillUnit(u)", "")])
    result = query_script_calls(tmp_path, "")
    assert len(_source_calls(result)) == 2 and result.total == 3
    assert result.calls[-1].origin == "index"
    assert any(note.code == "index.site_unverified" for note in result.diagnostics)


def test_index_only_never_claims_native_or_control_semantics(tmp_path: Path) -> None:
    _index(
        tmp_path,
        [_row("missing.j", "KillUnit", "1", "u", "if x then KillUnit(u)", "7")],
    )
    result = query_script_calls(tmp_path, "KillUnit")
    assert result.total == 1
    assert result.calls[0].binding == "index-declared" and result.calls[0].call is None
    assert result.script_coverage.complete is None
    assert not result.input_error


def test_huge_encoded_argument_and_offset_do_not_allocate_or_change_integer_quota(
    tmp_path: Path,
) -> None:
    digits = "9" * 6000
    _index(
        tmp_path,
        [_row("a.lua", "KillUnit", digits, "complete-value", "KillUnit(u)", digits)],
    )
    quota = sys.get_int_max_str_digits()
    result = query_script_calls(tmp_path, "complete-value")
    assert result.total == 1 and result.calls[0].offset == digits
    assert result.calls[0].arguments == ()
    assert result.calls[0].index_rows[0].cells[4] == digits
    assert any("不连续" in note.message for note in result.diagnostics)
    assert sys.get_int_max_str_digits() == quota


def test_ambiguous_schema_keeps_all_rows_and_searchable_unparsed_evidence(
    tmp_path: Path,
) -> None:
    _index(
        tmp_path,
        [("KillUnit", "CreateItem", "long\nraw\tvalue")],
        header=("调用", "call", "摘要"),
    )
    result = query_script_calls(tmp_path, "long")
    assert result.total == 1 and result.calls[0].origin == "index-unparsed"
    assert result.calls[0].index_rows[0].cells == (
        "KillUnit",
        "CreateItem",
        "long\nraw\tvalue",
    )
    assert result.script_coverage.complete is False
    assert any("重复语义列" in note.message for note in result.diagnostics)


def test_malformed_csv_retains_confirmed_prefix_and_unparsed_suffix(
    tmp_path: Path,
) -> None:
    path = _index(tmp_path, [_row("a.lua", "KillUnit", "1", "u", "KillUnit(u)", "0")])
    with path.open("ab") as stream:
        stream.write(b'"unterminated\nfull suffix')
    result = query_script_calls(tmp_path, "")
    assert any(record.origin == "index" for record in result.calls)
    assert any(record.raw == '"unterminated\nfull suffix' for record in result.calls)
    assert any(note.code == "index.csv" for note in result.diagnostics)


def test_present_but_missing_original_does_not_use_readable_fallback(
    tmp_path: Path,
) -> None:
    (tmp_path / "脚本原始文本").mkdir()
    _source(tmp_path, "KillUnit(u)", original=False)
    _index(tmp_path, [_row("war3map.lua", "KillUnit", "1", "u", "KillUnit(u)", "0")])
    result = query_script_calls(tmp_path, "")
    assert not _source_calls(result)
    assert result.calls[0].origin == "index" and result.calls[0].call is None
    assert result.script_coverage.complete is False
    assert not result.input_error and result.source_stable


def test_unsafe_and_ambiguous_index_source_labels_never_read_foreign_paths(
    tmp_path: Path,
) -> None:
    _source(tmp_path, "KillUnit(a)", name="first/shared.lua")
    _source(tmp_path, "KillUnit(b)", name="second/shared.lua")
    _index(
        tmp_path,
        [
            _row("shared.lua", "KillUnit", "1", "a", "KillUnit(a)", "0"),
            _row("../outside.lua", "KillUnit", "1", "b", "KillUnit(b)", "0"),
        ],
    )
    result = query_script_calls(tmp_path, "")
    assert len(_source_calls(result)) == 2
    assert sum(record.origin == "index" for record in result.calls) == 2
    assert any("2 个候选" in note.message for note in result.diagnostics)
    assert any("上级目录" in note.message for note in result.diagnostics)


def test_encrypted_report_and_unknown_language_remain_complete_diagnostics(
    tmp_path: Path,
) -> None:
    _source(tmp_path, "KillUnit(u)")
    _source(tmp_path, "UnclassifiedAction()", name="custom.txt")
    path = tmp_path / "未知文件" / "加密脚本检测.txt"
    path.parent.mkdir()
    path.write_text("第一条\n第二条完整报告", encoding="utf-8")
    result = query_script_calls(tmp_path, "KillUnit", 1)
    assert result.has_matches and result.script_coverage.complete is False
    assert "第二条完整报告" in "\n".join(result.lines)
    assert "语言尚未确认" in "\n".join(result.lines)
    assert not result.input_error


@pytest.mark.parametrize("query", ["&&", "()", "|| &&"])
def test_operator_only_queries_are_typed_input_errors_without_reading_pack(
    tmp_path: Path, query: str
) -> None:
    result = query_script_calls(tmp_path / "missing", query)
    assert result.input_error and result.total == 0
    assert "没有关键词" in result.lines[0]


@pytest.mark.parametrize("limit", [-1, True, 1.5, "2"])
def test_invalid_limits_are_rejected_before_any_source_read(
    tmp_path: Path, limit: object
) -> None:
    result = query_script_calls(tmp_path / "missing", "", cast(int, limit))
    assert result.input_error and "非负整数" in result.lines[0]


def test_many_source_calls_preserve_all_sites_and_only_caller_limit_omits(
    tmp_path: Path,
) -> None:
    _source(tmp_path, "\n".join(f"KillUnit(unit{index})" for index in range(1100)))
    full = query_script_calls(tmp_path, "")
    assert full.total == len(full.calls) == 1100
    limited = query_script_calls(tmp_path, "", 1099)
    assert limited.total == 1100 and limited.omitted == 1
    assert "unit1098" in limited.calls[-1].raw


def test_dynamic_receiver_sites_sharing_offset_keep_independent_calls(
    tmp_path: Path,
) -> None:
    text = "factory().member(1).next 'text'"
    _source(tmp_path, text)
    _index(tmp_path, [_row("war3map.lua", "factory", "", "", "factory()", "0")])
    result = query_script_calls(tmp_path, "")
    records = _source_calls(result)
    assert len(records) == result.total == 3
    assert len({record.offset for record in records}) == 1
    assert len({record.call.end_offset for record in records if record.call}) == 3
    attached = [record for record in records if record.index_rows]
    assert len(attached) == 1 and attached[0].callee == "factory"
    assert all(record.binding == "unknown" for record in records)


def test_unknown_syntax_without_calls_is_searchable_complete_recovery(
    tmp_path: Path,
) -> None:
    text = "local message = 'unclosed完整原文"
    _source(tmp_path, text)
    result = query_script_calls(tmp_path, "完整原文")
    assert result.has_matches and not _source_calls(result)
    assert result.calls[0].origin == "diagnostic"
    assert result.calls[0].raw == "'unclosed完整原文"
    assert result.script_coverage.complete is False and not result.input_error


def test_unknown_language_source_without_calls_remains_searchable(
    tmp_path: Path,
) -> None:
    text = 'local message = "unknown language recovery"'
    _source(tmp_path, text, name="custom.txt")
    result = query_script_calls(tmp_path, "recovery")
    assert result.has_matches and result.calls[0].raw == text
    assert result.calls[0].origin == "diagnostic"
    assert result.script_coverage.complete is False


def test_invalid_source_bytes_are_retained_without_guessing_calls(
    tmp_path: Path,
) -> None:
    path = _source(tmp_path, "")
    path.write_bytes(b"KillUnit(u)\xfftail")
    result = query_script_calls(tmp_path, "tail")
    assert not _source_calls(result) and result.has_matches
    assert result.calls[0].raw == r"KillUnit(u)\xfftail"
    assert result.script_coverage.complete is False and not result.input_error


def test_csv_error_retains_every_unparsed_following_line(tmp_path: Path) -> None:
    path = _index(tmp_path, [_row("a.lua", "KillUnit", "1", "u", "KillUnit(u)", "0")])
    with path.open("ab") as stream:
        stream.write(
            b'"closed"bad\tmalformed\nfollowing complete evidence\nlast line\n'
        )
    result = query_script_calls(tmp_path, "following && last")
    assert result.total == 1
    assert result.calls[0].origin == "diagnostic"
    assert (
        result.calls[0].raw
        == '"closed"bad\tmalformed\nfollowing complete evidence\nlast line\n'
    )
    assert any(note.code == "index.csv" for note in result.diagnostics)


def test_leading_blank_records_do_not_turn_declared_header_into_a_call(
    tmp_path: Path,
) -> None:
    path = _index(tmp_path, [_row("a.lua", "KillUnit", "1", "u", "KillUnit(u)", "0")])
    path.write_bytes(b"\n\r\n" + path.read_bytes())
    result = query_script_calls(tmp_path, "")
    assert result.total == 1
    assert result.calls[0].index_rows[0].ordinal == 4
    assert not any(note.code == "index.unparsed" for note in result.diagnostics)

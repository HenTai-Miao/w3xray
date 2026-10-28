"""Complete WTS evidence, ambiguity boundaries and exact string identities."""

from __future__ import annotations

import base64
import json
import sys
from unittest.mock import patch

import pytest

from gametool.extraction_diagnostics import ComponentParseError
from gametool.wts import (
    parse_wts,
    parse_wts_component,
    parse_wts_evidence,
    resolve,
    validate_wts_component,
)
from gametool.wts_models import WtsRecordState, wts_report_to_dict


def _block(sid: str, body: bytes, ending: bytes = b"\n") -> bytes:
    return (
        b"STRING "
        + sid.encode("ascii")
        + ending
        + b"{"
        + ending
        + body
        + ending
        + b"}"
        + ending
    )


def test_conflict_removes_all_values_and_retains_every_original_record() -> None:
    first = _block("001", "第一方".encode(), b"\r\n")
    repeated = _block("1", "第一方".encode("gbk"))
    different = _block("1", "冲突另一方".encode())
    later = _block("2", b"still confirmed")
    raw = first + repeated + different + later
    report = parse_wts_evidence(raw)

    assert report.table == {2: "still confirmed"}
    assert [row.raw_bytes for row in report.records] == [
        first,
        repeated,
        different,
        later,
    ]
    assert [row.state for row in report.records] == [
        WtsRecordState.CONFLICT,
        WtsRecordState.CONFLICT,
        WtsRecordState.CONFLICT,
        WtsRecordState.CONFIRMED,
    ]
    conflict = next(row for row in report.diagnostics if row.kind == "conflict")
    assert conflict.record_ordinals == (1, 2, 3)
    assert (conflict.byte_start, conflict.byte_end) == (
        0,
        len(first + repeated + different),
    )
    assert not report.complete
    assert resolve("TRIGSTR_001", report.table) == "TRIGSTR_001"
    with pytest.raises(ComponentParseError, match="conflicting WTS values"):
        parse_wts_component(raw)
    with pytest.raises(ComponentParseError, match="conflicting WTS values"):
        validate_wts_component(raw, {1: "冲突另一方", 2: "still confirmed"})


def test_equal_duplicates_remain_confirmed_and_all_duplicates_are_visible() -> None:
    raw = _block("0007", b"same") + _block("7", b"same") * 3
    report = parse_wts_evidence(raw)

    assert report.complete
    assert report.table == parse_wts_component(raw) == {7: "same"}
    assert len(report.records) == 4
    assert all(row.state == WtsRecordState.DUPLICATE for row in report.records)
    assert report.diagnostics[0].record_ordinals == (1, 2, 3, 4)
    assert not report.diagnostics[0].blocking


def test_missing_opening_cannot_borrow_the_next_blocks_opening() -> None:
    first = _block("1", b"retained")
    broken = b"STRING 2\r\nno opening or comment here\r\n"
    later = _block("3", b"confirmed later")
    report = parse_wts_evidence(first + broken + later)

    assert report.table == {1: "retained", 3: "confirmed later"}
    assert report.records[1].state == WtsRecordState.INCOMPLETE
    assert report.records[1].raw_bytes == broken
    assert report.records[1].body_bytes is None
    assert report.records[2].raw_bytes == later


def test_body_string_and_opening_lines_stay_literal_until_the_first_close() -> None:
    prefix = b"STRING 1\n{\npossibly damaged\n"
    nested = _block("2", b"literal block-shaped text")
    later = _block("3", b"independent")
    report = parse_wts_evidence(prefix + nested + later)

    assert report.table == {
        1: "possibly damaged\nSTRING 2\n{\nliteral block-shaped text",
        3: "independent",
    }
    assert [row.raw_bytes for row in report.records] == [prefix + nested, later]
    assert all(row.state == WtsRecordState.CONFIRMED for row in report.records)
    assert report.complete and not report.diagnostics
    assert resolve("TRIGSTR_2", report.table) == "TRIGSTR_2"


def test_nested_pasted_block_is_not_promoted_and_outer_close_remains_evidence() -> None:
    raw = (
        b"STRING 1\n{\npasted:\n"
        + _block("99", b"counterfeit")
        + b"}\n"
        + _block("3", b"real")
    )
    report = parse_wts_evidence(raw)

    assert report.table == {1: "pasted:\nSTRING 99\n{\ncounterfeit", 3: "real"}
    assert 99 not in parse_wts(raw)
    assert any(
        row.kind == "unparsed" and row.raw_bytes == b"}\n" for row in report.regions
    )
    assert {row.kind for row in report.diagnostics} == {"unparsed"}


def test_comment_continuations_follow_the_writer_grammar_and_preserve_original_bytes() -> (
    None
):
    raw = (
        b"STRING 1\r\n// first comment line\r\nsecond comment line\r\n"
        b"\r\nSTRING 999\r\n{still comment text}\r\n{\r\ncorrect title\r\n}\r\n"
    )
    report = parse_wts_evidence(raw)

    assert report.table == parse_wts_component(raw) == {1: "correct title"}
    assert report.complete and not report.diagnostics
    assert len(report.records) == 1
    assert report.records[0].raw_bytes == raw
    assert report.records[0].raw_text == raw.decode()
    assert report.records[0].body_bytes == b"correct title"
    assert report.records[0].body_start == raw.index(b"correct title")


def test_comment_without_opening_keeps_header_shaped_continuations_in_one_record() -> (
    None
):
    raw = b"STRING 1\n// first comment\nSTRING 2\ncontinued without an opening"
    report = parse_wts_evidence(raw)

    assert report.table == {}
    assert len(report.records) == 1
    assert report.records[0].raw_bytes == raw
    assert report.records[0].state == WtsRecordState.INCOMPLETE


def test_body_literal_header_has_no_duplicate_or_conflict_effect_on_real_header() -> (
    None
):
    first = b"STRING 1\n{\nSTRING 2\n{\nthis is literal body text\n}\n"
    second = _block("2", b"real second string")
    report = parse_wts_evidence(first + second)

    assert report.table == {
        1: "STRING 2\n{\nthis is literal body text",
        2: "real second string",
    }
    assert report.complete and not report.diagnostics
    assert [row.raw_bytes for row in report.records] == [first, second]


def test_header_words_comments_and_body_lines_do_not_fabricate_declarations() -> None:
    prefix = b"// STRING 99\n// {\n// counterfeit\n// }\n"
    body = b'prefix STRING 91\nSTRING 92\ntext follows the bare header\n"STRING 93"\n} else {'
    raw = prefix + _block("1", body)
    report = parse_wts_evidence(raw)

    assert report.complete
    assert report.table == {1: body.decode()}
    assert [row.string_id for row in report.records] == [1]


def test_nonanchored_header_text_and_invalid_decimal_tail_are_retained_not_parsed() -> (
    None
):
    prefix = b"prefix STRING 99\n{\nfalse\n}\n"
    invalid = b"STRING 12suffix\n{\ninvalid identifier\n}\n"
    report = parse_wts_evidence(prefix + invalid + _block("2", b"valid"))

    assert report.table == {2: "valid"}
    assert report.regions[0].raw_bytes == prefix
    assert report.records[0].state == WtsRecordState.INVALID
    assert report.records[0].string_id is None
    assert report.records[0].raw_bytes == invalid


def test_incomplete_duplicate_prevents_an_earlier_value_becoming_authoritative() -> (
    None
):
    report = parse_wts_evidence(
        _block("1", b"possibly stale") + b"STRING 1\n{\nnew unfinished"
    )

    assert report.table == {}
    assert [row.state for row in report.records] == [
        WtsRecordState.AMBIGUOUS,
        WtsRecordState.INCOMPLETE,
    ]
    assert report.records[1].body_bytes == b"new unfinished"
    assert {row.kind for row in report.diagnostics} == {"incomplete", "ambiguous"}


def test_all_source_bytes_partition_across_records_regions_and_bom() -> None:
    raw = b"\xef\xbb\xbf// intro\r\n\r\n" + _block(
        "7", "首\ufeff内\r\n尾  ".encode(), b"\r\n"
    )
    raw += b"unknown trailing bytes\x81\r" + _block(
        "8", "混合编码".encode("gbk"), b"\r"
    )
    report = parse_wts_evidence(raw)
    pieces = sorted((*report.records, *report.regions), key=lambda row: row.byte_start)
    position = 0
    for row in pieces:
        assert row.byte_start == position
        assert row.raw_bytes == raw[row.byte_start : row.byte_end]
        position = row.byte_end
    assert position == len(raw)
    assert b"".join(row.raw_bytes for row in pieces) == raw == report.raw_bytes
    assert report.table == {7: "首\ufeff内\r\n尾  ", 8: "混合编码"}
    assert report.records[0].line_start == 3
    assert report.records[0].line_end == 7
    assert report.regions[0].kind == "bom"


def test_embedded_bom_before_a_header_is_not_stripped() -> None:
    raw = (
        _block("1", b"first")
        + b"\xef\xbb\xbf"
        + _block("2", b"not a file leading BOM")
        + _block("3", b"last")
    )
    report = parse_wts_evidence(raw)
    assert report.table == {1: "first", 3: "last"}
    assert any(
        row.kind == "unparsed" and row.raw_bytes.startswith(b"\xef\xbb\xbf")
        for row in report.regions
    )


@pytest.mark.parametrize(
    "opening", [b"STRING 1 {value\n", b"STRING 1\n{value\n", b"STRING 1 {\nvalue\n"]
)
def test_existing_inline_opening_forms_keep_their_body(opening: bytes) -> None:
    assert parse_wts_component(opening + b"}\n" + _block("2", b"next")) == {
        1: "value",
        2: "next",
    }


def test_replacement_decoding_retains_bytes_without_confirming_a_lossy_value() -> None:
    raw = _block("1", b"\x81") + _block("2", b"still valid")
    with patch("gametool.wts_parser.default_legacy_codecs", return_value=("ascii",)):
        with patch(
            "gametool.war3_encoding.default_legacy_codecs", return_value=("ascii",)
        ):
            report = parse_wts_evidence(raw)
    assert report.table == {2: "still valid"}
    assert report.records[0].body_bytes == b"\x81"
    assert report.records[0].state == WtsRecordState.INVALID
    assert report.diagnostics[0].kind == "decode"


def test_long_decimal_ids_and_serialization_preserve_every_digit_without_global_change() -> (
    None
):
    digits = "9" * 5000
    sid = 10**5000 - 1
    quota = sys.get_int_max_str_digits()
    raw = _block(digits, b"large") + _block("0" * 5000 + "1", b"leading zeros")
    report = parse_wts_evidence(raw)
    assert resolve("TRIGSTR_" + digits, report.table) == "large"
    assert resolve("TRIGSTR_" + "0" * 5000 + "1", report.table) == "leading zeros"
    assert report.table[sid] == "large"
    serialized = json.loads(json.dumps(wts_report_to_dict(report), ensure_ascii=False))
    assert serialized["records"][0]["string_id"] == digits
    assert serialized["records"][1]["id_text"] == "0" * 5000 + "1"
    assert base64.b64decode(serialized["raw_bytes_base64"]) == raw
    assert base64.b64decode(serialized["records"][0]["body_bytes_base64"]) == b"large"
    assert sys.get_int_max_str_digits() == quota


@pytest.mark.parametrize(
    "value",
    ["TRIGSTR_+1", "TRIGSTR_-1", "TRIGSTR_ 1", "TRIGSTR_1 ", "TRIGSTR_1_0", "TRIGSTR_"],
)
def test_invalid_reference_spellings_do_not_resolve(value: str) -> None:
    assert resolve(value, {1: "wrong", 10: "also wrong"}) == value


def test_strict_validation_checks_values_not_just_presence_of_ids() -> None:
    raw = _block("1", b"correct")
    with pytest.raises(ComponentParseError, match="differs from confirmed source"):
        validate_wts_component(raw, {1: "invented"})


def test_record_count_tracks_all_encoded_blocks_with_no_result_ceiling() -> None:
    count = 12007
    raw = b"".join(_block(str(index), str(index).encode()) for index in range(count))
    report = parse_wts_evidence(raw)
    assert len(report.records) == len(report.table) == count
    assert report.records[-1].byte_end == len(raw)
    assert report.table[count - 1] == str(count - 1)
    assert report.complete

"""BOM-declared UTF-16 WTS keeps exact source evidence through real loading."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from gametool.api import load_map
from gametool.map_metadata_exports import format_map_string_evidence
from gametool.wts import parse_wts_component, parse_wts_evidence, resolve
from gametool.wts_models import WtsRecordState, WtsReport, wts_report_to_dict
from tests.test_archive_export_recovery import _archive_bytes
from tests.test_object_pipeline import _binary_object


_ENCODINGS = (("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff"))


def _partition(report: WtsReport) -> None:
    cursor = 0
    for row in sorted(
        (*report.records, *report.regions), key=lambda row: row.byte_start
    ):
        assert row.byte_start == cursor
        assert row.raw_bytes == report.raw_bytes[row.byte_start : row.byte_end]
        cursor = row.byte_end
    assert cursor == len(report.raw_bytes)
    for row in report.records:
        if row.body_start is not None:
            assert row.body_bytes == report.raw_bytes[row.body_start : row.body_end]


@pytest.mark.parametrize(("codec", "bom"), _ENCODINGS)
@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_utf16_body_and_offsets_keep_unicode_units_and_exact_line_endings(
    codec: str, bom: bytes, ending: str
) -> None:
    # U+010A contains 0A in UTF-16LE; it must never become a false newline.
    body = '  "名称🌍\u010a\ufeff\t' + ending + "second  "
    text = (
        "// source"
        + ending
        + "STRING 001"
        + ending
        + "// first comment"
        + ending
        + "continued comment"
        + ending
        + "{"
        + ending
        + body
        + ending
        + "}"
        + ending
        + "STRING 2"
        + ending
        + "{"
        + ending
        + "next"
        + ending
        + "}"
        + ending
    )
    raw = bom + text.encode(codec)
    report = parse_wts_evidence(raw)

    assert report.complete
    assert report.table == parse_wts_component(raw) == {1: body, 2: "next"}
    assert resolve("TRIGSTR_001", report.table) == body
    first = report.records[0]
    assert first.body_start == raw.index(body.encode(codec))
    assert first.body_bytes == body.encode(codec)
    assert first.raw_text.startswith("STRING 001" + ending)
    assert (first.line_start, first.line_end) == (2, 8)
    assert report.regions[0].raw_bytes == bom
    assert report.regions[0].byte_end == 2
    encoded = wts_report_to_dict(report)
    assert base64.b64decode(str(encoded["raw_bytes_base64"])) == raw
    _partition(report)


@pytest.mark.parametrize(("codec", "bom"), _ENCODINGS)
def test_utf16_conflicts_incomplete_duplicates_and_literal_headers_share_grammar(
    codec: str, bom: bytes
) -> None:
    text = (
        "STRING 1\n{\nsame\n}\nSTRING 001\n{\nsame\n}\n"
        "STRING 2\n{\nfirst\n}\nSTRING 2\n{\nsecond\n}\n"
        "STRING 3\n{\nSTRING 99\n{\nliteral\n}\n"
        "STRING 4\n{\npossibly stale\n}\nSTRING 4\n{\nunfinished"
    )
    raw = bom + text.encode(codec)
    report = parse_wts_evidence(raw)
    assert report.table == {1: "same", 3: "STRING 99\n{\nliteral"}
    assert [row.state for row in report.records] == [
        WtsRecordState.DUPLICATE,
        WtsRecordState.DUPLICATE,
        WtsRecordState.CONFLICT,
        WtsRecordState.CONFLICT,
        WtsRecordState.CONFIRMED,
        WtsRecordState.AMBIGUOUS,
        WtsRecordState.INCOMPLETE,
    ]
    assert not report.complete
    _partition(report)


@pytest.mark.parametrize(("codec", "bom"), _ENCODINGS)
@pytest.mark.parametrize("invalid", ["\ud800", "\udc00"])
def test_utf16_invalid_surrogate_does_not_confirm_or_discard_later_strings(
    codec: str, bom: bytes, invalid: str
) -> None:
    text = "STRING 1\n{\n" + invalid + "\n}\nSTRING 2\n{\nconfirmed\n}\n"
    raw = bom + text.encode(codec, errors="surrogatepass")
    report = parse_wts_evidence(raw)
    assert report.table == {2: "confirmed"}
    assert report.records[0].state == WtsRecordState.INVALID
    assert report.records[0].body_bytes == invalid.encode(codec, errors="surrogatepass")
    assert report.records[0].text == "\ufffd"
    issue = next(row for row in report.diagnostics if row.kind == "decode")
    assert issue.byte_start == 2
    assert issue.byte_end == report.records[0].byte_end
    assert not report.complete
    _partition(report)


@pytest.mark.parametrize(("codec", "bom"), _ENCODINGS)
def test_utf16_odd_tail_and_embedded_bom_remain_original_diagnostic_bytes(
    codec: str, bom: bytes
) -> None:
    text = (
        "STRING 1\n{\nfirst\n}\n\ufeffSTRING 2\n{\nunconfirmed\n}\n"
        "STRING 3\n{\nlast\n}\n"
    )
    raw = bom + text.encode(codec) + b"\x7f"
    report = parse_wts_evidence(raw)
    assert report.table == {1: "first", 3: "last"}
    assert report.regions[-1].raw_bytes == b"\x7f"
    assert report.regions[-1].byte_end == len(raw)
    assert not report.complete
    _partition(report)


@pytest.mark.parametrize(("codec", "bom"), _ENCODINGS)
def test_utf16_without_bom_is_not_inferred(codec: str, bom: bytes) -> None:
    raw = "STRING 1\n{\nnot declared UTF-16\n}\n".encode(codec)
    report = parse_wts_evidence(raw)
    assert report.table == {}
    assert not report.complete
    assert not any(row.kind == "bom" for row in report.regions)
    _partition(report)


@pytest.mark.parametrize(("codec", "bom"), _ENCODINGS)
def test_real_map_load_resolves_utf16_objects_and_exports_exact_wts(
    tmp_path: Path, codec: str, bom: bytes
) -> None:
    text = "STRING 1\r\n{\r\n地图名称🌍\r\n}\r\n"
    wts = bom + text.encode(codec)
    script = b"function main takes nothing returns nothing\r\nendfunction\r\n"
    raw = _archive_bytes(
        [
            ("war3map.wts", 0, 0, wts, False),
            (
                "war3map.w3u",
                0,
                0,
                _binary_object("hfoo", "H001", (("unam", "TRIGSTR_1"),)),
                False,
            ),
            ("war3map.j", 0, 0, script, False),
        ]
    )
    path = tmp_path / "utf16.w3x"
    path.write_bytes(raw)
    before = path.stat()
    md = load_map(str(path))
    try:
        assert md.obj_identity_index[("单位", "H001")].name == "地图名称🌍"
        assert md.scripts["war3map.wts"] == text
        assert md.scripts["war3map.j"].encode() == script
        report = md.wts_reports["war3map.wts"]
        assert report.complete and report.raw_bytes == wts
        exported = json.loads(format_map_string_evidence(md))
        assert exported["complete"]
        assert base64.b64decode(exported["sources"][0]["raw_bytes_base64"]) == wts
        assert not any(row.component == "wts" for row in md.diagnostics)
    finally:
        md.close()
    assert path.read_bytes() == raw
    assert path.stat().st_mtime_ns == before.st_mtime_ns

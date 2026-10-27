"""Complete JASS/Lua/plain text save candidates and exact byte provenance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gametool.api import MapData
from gametool.save_analysis import build_save_report, format_save_report_tsv
from gametool.save_code_cli import run_save_code_cli
from gametool.save_codes import (
    extract_save_codes,
    extract_save_codes_bytes,
    extract_save_text_carriers,
)


def test_multiline_calls_correct_argument_and_all_prefixes() -> None:
    text = (
        '// Preload("-load COMMENT123")\r\n'
        "call BlzSetAbilityTooltip(\r\n"
        "    'A001',\r\n"
        '    "intro -load ABCD-EFGH\\n!save OTHER123",\r\n'
        "    0)\r\n"
        'call Preload("-load ab")\r\n'
        'call Foo("-load BEFORE123") call Preload("-load AFTER123")\r\n'
    )
    hits = extract_save_codes(text, "war3map.j", lua=False)
    assert [hit.code for hit in hits] == [
        "-load ABCD-EFGH",
        "!save OTHER123",
        "-load AFTER123",
    ]
    assert hits[0].line == 4
    assert hits[0].carrier == "BlzSetAbilityTooltip"
    assert (
        text[hits[0].offset : hits[0].end] == '"intro -load ABCD-EFGH\\n!save OTHER123"'
    )
    assert all(hit.to_dict()["map_validation"] == "not_performed" for hit in hits)
    assert (
        len(extract_save_text_carriers(text, lua=False)) == 3
    )  # short carrier retained


def test_long_brackets_single_quotes_concatenation_comments_and_custom_members() -> (
    None
):
    text = (
        '-- Preload("-load COMMENT123")\n'
        "Preload([========[\n-load LONG123\n!save NEXT456]========])\n"
        "_G . BlzSetAbilityExtendedTooltip(FourCC('A001'), '-load ' .. -- gap\n"
        "'CONCAT789', 0)\n"
        'obj . Preload("-load CUSTOM123")\n'
        'obj:Preload("-load CUSTOM456")\n'
    )
    hits = extract_save_codes(text, "war3map.lua", lua=True)
    assert [hit.code for hit in hits] == [
        "-load LONG123",
        "!save NEXT456",
        "-load CONCAT789",
    ]
    assert hits[0].raw.startswith("[========[")
    assert hits[-1].carrier == "BlzSetAbilityExtendedTooltip"
    assert "-- gap" in hits[-1].raw
    assert len(extract_save_codes_bytes(text.encode(), lua=True)) == 3


@pytest.mark.parametrize(
    "encoding,bom",
    (
        ("utf-8", b"\xef\xbb\xbf"),
        ("utf-16-le", b"\xff\xfe"),
        ("utf-16-be", b"\xfe\xff"),
        ("gb18030", b""),
    ),
)
def test_actual_encoding_raw_line_and_offsets_are_exact(
    encoding: str, bom: bytes
) -> None:
    text = '// 中文前缀\r\ncall Preload( "-load 中文ABC123" )\r\n'
    payload = bom + text.encode(encoding)
    hits = extract_save_codes_bytes(payload, "profile.pld", lua=False)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.line == 2 and hit.encoding == encoding
    assert hit.byte_offset is not None and hit.byte_end is not None
    assert payload[hit.byte_offset : hit.byte_end] == hit.raw.encode(encoding)
    assert hit.raw_hex == payload[hit.byte_offset : hit.byte_end].hex()
    assert hit.source_sha256
    assert text[hit.offset : hit.end] == hit.raw
    assert payload == bom + text.encode(encoding)


def test_long_command_prefix_and_plain_lines_keep_every_candidate() -> None:
    command = "-" + "long" * 50
    payload = f"{command} CODE123\r\n!save SECOND456\r\n".encode()
    hits = extract_save_codes_bytes(payload)
    assert [hit.command for hit in hits] == [command, "!save"]
    assert hits[0].carrier == "command-line"
    assert hits[1].line == 2


def test_lua_numeric_unicode_and_whitespace_escapes_are_static_text() -> None:
    text = r"""Preload("\x2dload \065\066\067\z  
        \u{4E2D}123")"""
    hits = extract_save_codes(text, lua=True)
    assert len(hits) == 1
    assert hits[0].code == "-load ABC中123"
    assert hits[0].diagnostics == ()
    carriers = extract_save_text_carriers(r'Preload("-load ABC\q123")', lua=False)
    assert carriers[0].state == "unknown-text"
    assert carriers[0].diagnostics


def test_map_save_analysis_exposes_text_evidence_as_candidates() -> None:
    text = 'call Preload("-load MAP123")\ncall StoreInteger(g, "hero", "level", 7)\n'
    md = MapData(path="map.w3x", name="map", scripts={"war3map.j": text})
    report = build_save_report(md)
    assert len(report.codes) == len(report.text_carriers) == 1
    code = report.codes[0]
    assert code.source == "war3map.j"
    clue = next(row for row in report.rows if row.mechanism == "SaveCode")
    assert clue.state == "text-candidate"
    assert clue.offset == code.offset
    assert "static-declaration" in format_save_report_tsv(report)
    assert "text-candidate" in format_save_report_tsv(report)


def test_cli_scans_nested_lua_and_plain_carriers_with_complete_diagnostics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nested = tmp_path / "deep" / "more"
    nested.mkdir(parents=True)
    (nested / "war3map.lua").write_text("Preload('-load LUA123')", encoding="utf-8")
    (nested / "codes.txt").write_text("-load TEXT456", encoding="utf-8")
    (nested / "broken.txt").write_bytes(b"\xff\xfe\0")
    assert run_save_code_cli((str(tmp_path), "--json", "--limit", "1")) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["total"] == 2 and result["omitted"] == 1
    assert len(result["text_carriers"]) == 2
    assert result["diagnostics"] and "broken.txt" in result["diagnostics"][0]
    assert result["codes"][0]["byte_offset"] is not None


def test_cli_invalid_limit_rejected_before_scanning(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        run_save_code_cli((str(tmp_path), "--limit", "-1"))
    assert exc.value.code == 2

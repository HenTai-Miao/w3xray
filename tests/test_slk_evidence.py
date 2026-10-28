"""Lossless SLK cells and conservative compatibility projections."""

from __future__ import annotations

import pytest
from decimal import Decimal, getcontext
import json
from pathlib import Path

from gametool.slk import SlkParseError, parse_slk
from gametool.slk_evidence import parse_slk_evidence


_BASE = (
    'ID;PWXL;N;E\nC;Y1;X1;K"ID"\nC;Y1;X2;K"Name"\nC;Y1;X3;K"race"\nC;Y2;X1;K"hfoo"\n'
)


def test_conflicting_cell_retains_independent_field_and_other_object() -> None:
    text = (
        _BASE + 'C;Y2;X2;K"first"\nC;Y2;X2;K"second"\n'
        'C;Y2;X3;K"human"\nC;Y3;X1;K"hrif"\nC;Y3;X2;K"Rifleman"\nE\n'
    )
    assert parse_slk(text) == {
        "hfoo": {"race": "human"},
        "hrif": {"Name": "Rifleman"},
    }


def test_duplicate_object_rows_do_not_choose_last_conflicting_value() -> None:
    text = (
        _BASE + 'C;Y2;X2;K"first"\nC;Y2;X3;K"human"\n'
        'C;Y3;X1;K"hfoo"\nC;Y3;X2;K"second"\nE\n'
    )
    assert parse_slk(text) == {"hfoo": {"race": "human"}}


def test_duplicate_header_does_not_choose_last_column() -> None:
    text = (
        _BASE.replace('X3;K"race"', 'X3;K"Name"')
        + 'C;Y2;X2;K"first"\nC;Y2;X3;K"second"\nE\n'
    )
    assert parse_slk(text) == {"hfoo": {}}


@pytest.mark.parametrize(
    ("raw", "value"),
    [('K"a""b"', 'a""b'), ('K"a;;b"', "a;b"), ('K""', "")],
)
def test_quoted_values_preserve_explicit_empty_and_decode_escapes(
    raw: str, value: str
) -> None:
    assert parse_slk(_BASE + f"C;Y2;X2;{raw}\nE\n")["hfoo"]["Name"] == value


def test_unterminated_quote_never_becomes_confirmed_field() -> None:
    text = _BASE + 'C;Y2;X2;K"unterminated\nC;Y2;X3;K"human"\nE\n'
    assert parse_slk(text) == {"hfoo": {"race": "human"}}


def test_every_record_cell_and_offset_survives_duplicate_identical_values() -> None:
    text = _BASE.replace("\n", "\r\n") + (
        'C;;Y2;X2;K"a;;b";\r\nC;Y2;X2;K"a;b"\r\nC;Y2;X3;K"\x00literal"\r\nE\r\n'
    )
    evidence = parse_slk_evidence(text, raw_bytes=text.encode())
    assert evidence.raw_bytes == text.encode()
    assert "".join(record.raw for record in evidence.records) == text
    for record in evidence.records:
        assert text[record.start : record.end] == record.raw
        for field in record.fields:
            assert text[field.start : field.end] == field.raw
    assert evidence.as_dict() == {"hfoo": {"Name": "a;b", "race": "\x00literal"}}
    duplicates = [
        issue for issue in evidence.diagnostics if issue.code == "duplicate_cell"
    ]
    assert len(duplicates) == 1 and not duplicates[0].conflict
    assert len(duplicates[0].cell_indexes) == 2
    raw = json.loads(evidence.diagnostic_text(duplicates[0]))
    assert [cell["raw"] for cell in raw["cells"]] == ['K"a;;b"', 'K"a;b"']
    record = next(record for record in evidence.records if record.raw.startswith("C;;"))
    assert [field.raw for field in record.fields] == [
        "C",
        "",
        "Y2",
        "X2",
        'K"a;;b"',
        "",
    ]


def test_unnamed_columns_and_orphan_rows_remain_complete_opaque_evidence() -> None:
    text = (
        _BASE + 'C;Y2;X2;K"Footman"\nC;Y2;X99;K"extension;not-a-header"\n'
        'C;Y17;X2;K"missing ID"\nZ;arbitrary;opaque\nE\n'
    )
    evidence = parse_slk_evidence(text)
    assert evidence.as_dict() == {"hfoo": {"Name": "Footman"}}
    assert [row.number for row in evidence.rows] == [2, 17]
    assert evidence.rows[1].key is None
    opaque = [evidence.cells[index].value for index in evidence.opaque]
    assert "extension;not-a-header" in opaque and "missing ID" in opaque
    assert {issue.code for issue in evidence.diagnostics} >= {
        "unnamed_column",
        "missing_row_key",
        "opaque_record",
    }


def test_duplicate_physical_rows_keep_every_origin_and_independent_fields() -> None:
    text = (
        _BASE + 'C;Y2;X2;K"Footman"\nC;Y3;X1;K"hfoo"\n'
        'C;Y3;X2;K"Footman"\nC;Y3;X3;K"human"\nE\n'
    )
    evidence = parse_slk_evidence(text)
    assert evidence.as_dict() == {"hfoo": {"Name": "Footman", "race": "human"}}
    assert evidence.objects[0].row_numbers == (2, 3)
    diagnostic = next(
        issue for issue in evidence.diagnostics if issue.code == "duplicate_object_id"
    )
    payload = json.loads(evidence.diagnostic_text(diagnostic))
    assert len(payload["cells"]) == 5
    assert len(payload["records"]) == 5


def test_missing_or_duplicated_key_header_never_invents_a_layout() -> None:
    no_key_header = _BASE.replace('C;Y1;X1;K"ID"\n', "") + 'C;Y2;X2;K"Footman"\nE\n'
    duplicate_key_header = _BASE + 'C;Y1;X8;K"ID"\nC;Y2;X2;K"Footman"\nE\n'
    for text in (no_key_header, duplicate_key_header):
        evidence = parse_slk_evidence(text)
        assert evidence.as_dict() == {}
        assert any(issue.code == "missing_key_header" for issue in evidence.diagnostics)
        assert evidence.rows and evidence.opaque


def test_unknown_cell_fields_and_types_stay_raw_without_a_cached_guess() -> None:
    text = _BASE + 'C;Y2;X2;K"cached";Eopaque-formula\nC;Y2;X3;K42\nE\n'
    evidence = parse_slk_evidence(text)
    assert evidence.as_dict() == {"hfoo": {"race": "42"}}
    assert dict(evidence.objects[0].value_kinds) == {"race": "bare"}
    assert any(issue.code == "opaque_cell_fields" for issue in evidence.diagnostics)
    assert evidence.records[-3].fields[-1].raw == "Eopaque-formula"


def test_different_encoded_value_types_are_not_identical_duplicates() -> None:
    text = _BASE + 'C;Y2;X2;K42\nC;Y2;X2;K"42"\nC;Y2;X3;K"human"\nE\n'
    evidence = parse_slk_evidence(text)
    assert evidence.as_dict() == {"hfoo": {"race": "human"}}
    assert ("hfoo", "Name") in evidence.blocked_fields


def test_coordinate_digit_quota_does_not_bound_sparse_input_or_diagnostics() -> None:
    digits = "9" * 5001
    text = (
        'ID;P\nC;X1;Y1;K"ID"\nC;X' + digits + ';Y1;K"Name"\n'
        "C;X1;Y" + digits + ';K"hfoo"\nC;X' + digits + ";Y" + digits + ';K"far"\n'
        "C;X" + digits + ";Y" + digits + ';K"far"\nE\n'
    )
    context = getcontext().copy()
    evidence = parse_slk_evidence(text)
    assert evidence.as_dict() == {"hfoo": {"Name": "far"}}
    assert Decimal(evidence.max_x) == Decimal(digits) == Decimal(evidence.max_y)
    assert len(evidence.cells) == 5 and len(evidence.rows) == 1
    diagnostic = next(
        issue for issue in evidence.diagnostics if issue.code == "duplicate_cell"
    )
    assert json.loads(evidence.diagnostic_text(diagnostic))["cells"][0]["x"] == digits
    assert getcontext().prec == context.prec
    assert getcontext().flags == context.flags and getcontext().traps == context.traps


@pytest.mark.parametrize("coordinate", ["X0", "Y-1", "XNaN", "Y1.5", "X"])
def test_invalid_coordinate_keeps_explicit_boundary(coordinate: str) -> None:
    text = _BASE + f'C;{coordinate};K"bad"\nE\n'
    with pytest.raises(SlkParseError, match="invalid_coordinate"):
        parse_slk(text)
    evidence = parse_slk_evidence(text)
    assert any(issue.code == "invalid_coordinate" for issue in evidence.diagnostics)
    assert evidence.opaque


def test_pinned_reference_fixture_has_full_literal_fields() -> None:
    payload = (
        Path(__file__).parent / "fixtures/reference/AbilityDataSmall.slk"
    ).read_bytes()
    evidence = parse_slk_evidence(payload.decode("latin-1"), raw_bytes=payload)
    assert evidence.diagnostics == ()
    assert len(evidence.rows) == 49 and len(evidence.columns) == 95
    assert evidence.as_dict()["AHwe"]["UnitID1"] == "hwat"
    assert (
        "".join(record.raw for record in evidence.records).encode("latin-1") == payload
    )


def test_inherited_cursor_and_incomplete_quote_positions_reach_diagnostics() -> None:
    text = _BASE + 'F;Y2;X2\nC;K"unfinished\nF;X0\nC;K"unbound"\nE\n'
    evidence = parse_slk_evidence(text)
    quote = next(
        issue for issue in evidence.diagnostics if issue.code == "incomplete_quote"
    )
    cell = json.loads(evidence.diagnostic_text(quote))["cells"][0]
    assert (cell["x"], cell["y"]) == ("2", "2")
    unbound = next(
        issue for issue in evidence.diagnostics if issue.code == "unbound_cell"
    )
    cell = json.loads(evidence.diagnostic_text(unbound))["cells"][0]
    assert cell["x"] is None and cell["raw"] == 'K"unbound"'

"""Equipment plan interpretation keeps exact declarations and all evidence."""

import base64
import hashlib
import json

from gametool.loadout_documents import inspect_loadout_document


def _record(**changes):
    return {
        "name": "旅途装备",
        "unit_type_id": int.from_bytes(b"Hpal", "big"),
        "equipment": [[int.from_bytes(b"I001", "big"), 5]] * 9,
        "equipment_charges": list(range(9)),
        "requires_any_slot": False,
        **changes,
    }


def _inspect(value):
    return inspect_loadout_document(
        json.dumps(value, ensure_ascii=False).encode("utf-8"), "plans.json"
    )


def test_artifact_plan_keeps_exact_latin1_codes_and_every_repeated_slot():
    codes = ["I001", " I0 ", "0xAB", "éA,;", "I001", "i001"]
    result = _inspect({"schema": 1, "codes": codes})
    assert result.status == "confirmed"
    assert result.kind == "artifact-plan"
    assert [slot.code for slot in result.records[0].slots] == codes
    assert [slot.index for slot in result.records[0].slots] == list(range(1, 7))
    assert result.records[0].unit_state == "not-declared"


def test_loadout_records_preserve_empty_slots_names_types_and_charges():
    rows = _record(
        equipment=[[0, 0], [int.from_bytes(b"\xe9A,;", "big"), 9]]
        + [[int.from_bytes(b"I001", "big"), 5]] * 7
    )
    result = _inspect({"schema": 1, "records": [rows, rows]})
    assert result.status == "confirmed"
    assert len(result.records) == 2
    for record in result.records:
        assert record.name == "旅途装备"
        assert record.unit_code == "Hpal"
        assert record.slots[0].state == "empty"
        assert record.slots[0].code is None
        assert record.slots[1].code == "éA,;"
        assert record.slots[1].type_literal == "9"
        assert [slot.charge_literal for slot in record.slots] == [
            str(n) for n in range(9)
        ]
        assert record.requires_any_slot is False


def test_more_than_source_limits_and_extra_slots_are_retained_without_padding():
    rows = [
        _record(
            equipment=[[int.from_bytes(b"I001", "big"), 5]] * 11,
            equipment_charges=list(range(10)),
        )
    ] * 513
    result = _inspect({"schema": 1, "records": rows})
    assert result.status == "partial"
    assert len(result.records) == 513
    assert all(
        len(record.slots) == 11 and len(record.charges) == 10
        for record in result.records
    )
    assert all(record.slots[-1].charge_literal is None for record in result.records)
    assert sum(note.code == "quantity-count" for note in result.diagnostics) == 513


def test_duplicate_roles_never_choose_last_values_or_guess_quantity_pairing():
    record = json.dumps(_record(), ensure_ascii=False)
    record = record[:-1] + ',"name":"另一个名称","equipment_charges":[99]}'
    raw = ('{"schema":1,"records":[' + record + "]}").encode("utf-8")
    result = inspect_loadout_document(raw)
    assert result.status == "partial"
    parsed = result.records[0]
    assert parsed.name is None
    assert len(parsed.charges) == 10
    assert all(slot.charge_literal is None for slot in parsed.slots)
    assert sum(note.code == "duplicate-json-key" for note in result.diagnostics) == 2
    assert base64.b64decode(result.raw_base64) == raw
    assert result.sha256 == hashlib.sha256(raw).hexdigest()


def test_duplicate_artifact_arrays_and_format_conflict_keep_both_declarations():
    raw = b'{"schema":1,"codes":["I001"],"codes":["I002"],"records":[]}'
    result = inspect_loadout_document(raw)
    assert result.kind == "ambiguous"
    assert result.status == "partial"
    assert [record.slots[0].code for record in result.records] == ["I001", "I002"]
    assert all(record.slots[0].state == "unverified" for record in result.records)
    assert result.root is not None
    root = result.nodes[result.root]
    assert [member.key for member in root.members] == [
        "schema",
        "codes",
        "codes",
        "records",
    ]


def test_unknown_fields_and_byte_spans_preserve_full_unicode_crlf_and_bom():
    text = '{\r\n"schema":1,"codes":["I001","I002","I003","I004","I005","I006"],"扩展":{"a":"中文\\n全量","a":[1,2,3]}\r\n}'
    raw = b"\xff\xfe" + text.encode("utf-16-le")
    result = inspect_loadout_document(raw, "six-artifacts.json")
    assert result.raw_text == text
    assert result.encoding == "utf-16-le"
    for index, (node, (start, end)) in enumerate(
        zip(result.nodes, result.byte_spans, strict=True)
    ):
        assert (
            raw[start:end].decode("utf-16-le")
            == text[node.start : node.end]
            == result.raw_token(index)
        )
    assert any(note.code == "extension-field" for note in result.diagnostics)
    assert any(note.code == "duplicate-json-key" for note in result.diagnostics)
    exported = json.dumps(result.to_dict(), ensure_ascii=False).encode("utf-8")
    assert json.loads(exported)["raw_text"] == text


def test_arbitrarily_long_quantity_and_deep_extensions_do_not_convert_to_int():
    row = json.dumps(_record(equipment_charges=[0] * 9), separators=(",", ":"))
    row = row.replace(
        '"equipment_charges":[0,', '"equipment_charges":[' + "9" * 5000 + ",", 1
    )
    raw = (
        '{"schema":1,"records":['
        + row
        + '],"extension":'
        + "[" * 1500
        + "0"
        + "]" * 1500
        + "}"
    ).encode()
    result = inspect_loadout_document(raw)
    assert result.status == "confirmed"
    assert result.records[0].slots[0].charge_literal == "9" * 5000
    assert result.records[0].charges[0].literal == "9" * 5000
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "9" * 5000 in serialized


def test_invalid_types_empty_and_non_plan_documents_have_distinct_states():
    assert _inspect({"hello": [1, 2]}).status == "not-plan"
    assert _inspect({"schema": 1, "records": []}).status == "confirmed"
    assert not _inspect({"schema": 1, "records": []}).records
    result = _inspect(
        {
            "schema": True,
            "records": [
                _record(
                    unit_type_id=True,
                    requires_any_slot=1,
                    equipment=[[1.0, False]],
                    equipment_charges=[-1],
                )
            ],
        }
    )
    assert result.status == "partial"
    assert result.records[0].unit_code is None
    assert result.records[0].requires_any_slot is None
    assert result.records[0].slots[0].code is None
    assert result.records[0].charges[0].literal is None
    assert {note.code for note in result.diagnostics} >= {
        "unsupported-schema",
        "invalid-identity",
        "invalid-boolean",
        "invalid-quantity",
        "invalid-equipment-type",
    }


def test_broken_json_and_unknown_encoding_retain_complete_raw_sources():
    for raw in (b'{"schema":1,"records":[', b"\x00\x01\x02"):
        result = inspect_loadout_document(raw)
        assert result.status == "partial"
        assert not result.recognized
        assert base64.b64decode(result.raw_base64) == raw
        assert result.diagnostics
        assert result.to_dict()["recovery"]


def test_unpaired_surrogate_extensions_export_as_evidence_without_encoding_crash():
    raw = b'{"schema":1,"records":[],"extension":"\\ud800"}'
    result = inspect_loadout_document(raw)
    assert result.status == "partial"
    exported = json.dumps(result.to_dict(), ensure_ascii=False).encode("utf-8")
    assert json.loads(exported)["raw_text"] == raw.decode()


def test_negative_zero_is_an_exact_zero_integer_token_not_a_missing_slot():
    row = json.dumps(
        _record(unit_type_id=0, equipment=[[0, 0]] * 9, equipment_charges=[0] * 9),
        separators=(",", ":"),
    )
    raw = (
        '{"schema":1,"records":['
        + row.replace(":0", ":-0").replace("[0", "[-0").replace(",0", ",-0")
        + "]}"
    ).encode()
    result = inspect_loadout_document(raw)
    assert result.status == "confirmed"
    assert result.records[0].unit_state == "empty"
    assert all(
        slot.code is None and slot.state == "empty" for slot in result.records[0].slots
    )
    assert all(
        slot.type_literal == "-0" and slot.charge_literal == "-0"
        for slot in result.records[0].slots
    )

"""Complete encoded game-cache records, partial recovery and layout ambiguity."""

from __future__ import annotations

import json
import struct

import pytest

from gametool.save_gamecache import extract_embedded_gamecaches, parse_gamecache
from tests.save_structure_fixture import (
    cache_bytes,
    embedded_cache,
    hero_bytes,
    rawcode,
    u32,
)


def test_all_five_types_keep_raw_names_reserved_bytes_and_offsets() -> None:
    long_text = "完整文本\t\r\n" * 2000
    raw = cache_bytes(
        (
            (("signed", struct.pack("<i", -7)),),
            (("zero", struct.pack("<f", 0)),),
            (("false", u32(0)),),
            (),
            (("message", long_text.encode() + b"\0"),),
        )
    )
    report = parse_gamecache(raw, source="Campaigns.w3v", offset=101)
    assert report.complete
    assert [(field.key, field.value) for field in report.fields] == [
        ("signed", -7),
        ("zero", 0.0),
        ("false", False),
        ("message", long_text),
    ]
    assert report.structure[0].value == 0x01020304  # reserved, not an invented version
    reserved = next(
        field for field in report.structure if field.name.endswith("reserved_types")
    )
    assert reserved.raw == bytes(range(20))
    for field in report.fields:
        assert raw[field.record_offset - 101 : field.end - 101] == field.raw
        for component in field.fields:
            assert raw[component.offset - 101 : component.end - 101] == component.raw
    encoded = json.loads(json.dumps(report.to_dict(), allow_nan=False))
    assert encoded["tail_hex"] == ""
    assert encoded["raw_hex"] == raw.hex()


@pytest.mark.parametrize(
    "layout", ("classic", "modern_skills", "classic_extension", "reforged")
)
def test_hero_layouts_preserve_every_encoded_field_and_unknown_tail(
    layout: str,
) -> None:
    unit = hero_bytes(layout)
    raw = cache_bytes(((), (), (), (("hero1", unit),), ()))
    evidence = parse_gamecache(raw)
    assert evidence.complete, evidence.diagnostics
    assert evidence.layouts == (layout,)
    record = evidence.fields[0]
    assert record.value_type == "unit"
    fields = {field.name: field for field in record.fields}
    assert fields["unit_id"].value == "H001"
    assert fields["inventory.1.item"].value == "I001"
    assert fields["inventory.1.item"].raw == b"100I"
    assert fields["inventory.1.charges"].value == 7
    assert fields["inventory.1.flags"].value == 0xAABBCCDD
    assert fields["experience"].value == 23456
    assert fields["level_minus_one"].value == 7
    assert fields["unspent_skill_points"].value == 0
    assert fields["strength_bonus"].value == 1.5
    assert fields["agility_bonus"].value == 2.75
    assert fields["intelligence_bonus"].value == -3.5
    assert fields["attack_increment_1"].value == -9
    assert fields["tail_reserved_bytes"].raw == b"\xc1\xfe"
    assert len(fields["raw_tail"].raw) == 30
    assert fields["skills.1.level"].value == 100001
    if layout in {"reforged", "classic_extension"}:
        assert fields["extensions.2.1.2"].value == 0xFFFFFFFF
    for field in record.fields:
        assert raw[field.offset : field.end] == field.raw


def test_layout_ambiguity_keeps_common_fields_and_every_candidate() -> None:
    unit = hero_bytes("modern_skills", skills=0)
    # Both a classic and a modern skill stream consume this cache completely,
    # but classic sees two extra empty strings. No layout is chosen by order.
    unit = (
        unit[:-34]
        + u32(1)
        + rawcode("A001")
        + u32(0)
        + u32(1)
        + b"\0" * 26
        + b"\2\0\0\0"
    )
    raw = cache_bytes(((), (), (), (("hero1", unit),), ()))
    evidence = parse_gamecache(raw)
    assert not evidence.complete
    assert "classic" in evidence.layouts and "modern_skills" in evidence.layouts
    assert any("ambiguous" in note for note in evidence.diagnostics)
    assert len(evidence.candidates) == 4
    assert evidence.fields[0].state == "partial"
    value = evidence.fields[0].value
    assert isinstance(value, dict)
    assert value["unit_id"] == "H001"
    assert "skills.1.level" not in value
    assert evidence.to_dict()["raw_hex"] == raw.hex()


def test_truncated_encoded_count_recovers_prefix_without_count_allocation() -> None:
    raw = cache_bytes(((("one", u32(7)),), (), (), (), ()))
    count_offset = raw.index(b"one\0") - 4
    damaged = bytearray(raw[: raw.index(b"one\0") + 8])
    struct.pack_into("<I", damaged, count_offset, 0xFFFFFFFF)
    evidence = parse_gamecache(bytes(damaged))
    assert not evidence.complete
    assert evidence.fields[0].key == "one"
    assert evidence.fields[0].value == 7
    assert any("encoded bounds" in note for note in evidence.diagnostics)
    assert evidence.to_dict()["raw_hex"] == damaged.hex()


def test_unknown_tail_retains_all_confirmed_fields_and_exact_tail() -> None:
    raw = cache_bytes(((("one", u32(7)),), (), (), (), ()))
    tail = b"\xde\xad\x00\xffextension"
    evidence = parse_gamecache(raw + tail)
    assert not evidence.complete
    assert evidence.fields[0].value == 7
    assert evidence.consumed == len(raw)
    assert evidence.to_dict()["tail_hex"] == tail.hex()


def test_invalid_scalars_and_conflicting_values_do_not_erase_later_records() -> None:
    raw = cache_bytes(
        (
            (("duplicate", u32(0)), ("duplicate", u32(9))),
            (("nan", struct.pack("<f", float("nan"))),),
            (("bad", u32(2)),),
            (),
            (("after", b"still here\0"),),
        )
    )
    evidence = parse_gamecache(raw)
    assert evidence.complete  # encoded structure consumed; value states remain separate
    assert [field.state for field in evidence.fields] == [
        "conflict",
        "conflict",
        "invalid",
        "invalid",
        "confirmed",
    ]
    assert evidence.fields[2].value is None
    assert evidence.fields[-1].value == "still here"
    json.dumps(evidence.to_dict(), allow_nan=False)


def test_encoded_inventory_skills_and_extensions_have_no_empirical_ceiling() -> None:
    unit = hero_bytes("reforged", slots=513, skills=4097, extensions=4097)
    evidence = parse_gamecache(cache_bytes(((), (), (), (("hero", unit),), ())))
    assert evidence.complete
    fields = {field.name: field.value for field in evidence.fields[0].fields}
    assert fields["inventory.513.item"] == "I001"
    assert fields["skills.4097.level"] == 104097
    assert fields["extensions.2.4097.3"] == 3


def test_all_embedded_frames_keep_raw_layer_offsets_and_opaque_frame_bytes() -> None:
    cache = cache_bytes(((("gold", u32(42)),), (), (), (), ()))
    frame = embedded_cache(cache)
    raw = b"unknown save prefix" + frame * 70 + b"unknown save tail"
    evidence = extract_embedded_gamecaches(raw, source="save.w3z::decompressed")
    assert len(evidence) == 70
    for record in evidence:
        assert record.complete
        assert record.raw == cache
        assert raw[record.offset : record.offset + len(cache)] == cache
        assert record.frame[2].raw == bytes(range(32))
        assert record.fields[0].value == 42


def test_unframed_name_is_not_a_cache_and_truncated_frame_is_visible() -> None:
    cache = cache_bytes(((("gold", u32(42)),), (), (), (), ()))
    assert extract_embedded_gamecaches(b"Campaigns.w3v\0" + cache) == ()
    frame = embedded_cache(cache)
    evidence = extract_embedded_gamecaches(frame[:-4])
    assert len(evidence) == 1
    assert not evidence[0].complete
    assert evidence[0].fields[0].value == 42
    assert any("truncated embedded cache" in note for note in evidence[0].diagnostics)

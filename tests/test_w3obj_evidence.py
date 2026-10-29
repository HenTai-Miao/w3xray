"""W3OBJ record boundaries follow pinned War3Net readers and retain source bytes."""

from __future__ import annotations

import struct

import pytest

from gametool.w3obj import Modification, W3Object, parse_object_data_report


def _mod(
    field_id: bytes,
    raw_value: bytes,
    *,
    var_type: int = 3,
    level: int | None = None,
    pointer: int = 0,
    trailer: int = 0xF1234567,
) -> bytes:
    data = field_id + struct.pack("<i", var_type)
    if level is not None:
        data += struct.pack("<ii", level, pointer)
    return data + raw_value + struct.pack("<I", trailer)


def _object(
    mods: tuple[bytes, ...],
    *,
    version: int = 3,
    extra_ints: tuple[int, ...] = (),
    old_id: bytes = b"ratc",
    new_id: bytes = b"S001",
) -> bytes:
    data = old_id + new_id
    if version == 3:
        data += struct.pack("<i", len(extra_ints))
        data += b"".join(struct.pack("<i", value) for value in extra_ints)
    return data + struct.pack("<i", len(mods)) + b"".join(mods)


def _custom_file(obj: bytes, version: int = 3) -> bytes:
    return struct.pack("<iii", version, 0, 1) + obj


def test_four_argument_modification_constructor_retains_compatibility() -> None:
    mod = Modification("unam", 3, 0, "Name")
    obj = W3Object("ratc", "S001", True, [mod])

    assert (mod.data_pointer, mod.offset, mod.end_offset) == (0, -1, -1)
    assert (mod.raw_bytes, mod.trailer, obj.extra_ints) == (b"", 0, ())


@pytest.mark.parametrize("ext", ("w3u", "w3t", "w3a", "w3q", "w3b", "w3d", "w3h"))
@pytest.mark.parametrize("extra_ints", ((), (0,), (0, 1), (-2147483648, 2147483647)))
def test_v3_extra_int_array_precedes_one_modification_table(
    ext: str, extra_ints: tuple[int, ...]
) -> None:
    level = 4 if ext in {"w3a", "w3q", "w3d"} else None
    encoded = _mod(b"unam", b"V3 NAME\0", level=level, pointer=-17)
    payload = _custom_file(_object((encoded,), extra_ints=extra_ints))

    report = parse_object_data_report(payload, ext)

    assert report.issues == ()
    assert len(report.objects) == 1
    obj = report.objects[0]
    assert (obj.old_id, obj.new_id, obj.is_custom) == ("ratc", "S001", True)
    assert obj.extra_ints == extra_ints
    assert [(m.field_id, m.value) for m in obj.mods] == [("unam", "V3 NAME")]
    mod = obj.mods[0]
    assert mod.offset == 28 + 4 * len(extra_ints)
    assert mod.end_offset == len(payload)
    assert mod.raw_bytes == payload[mod.offset : mod.end_offset] == encoded
    assert mod.trailer == 0xF1234567
    assert mod.level == (level or 0)
    assert mod.data_pointer == (-17 if level is not None else 0)


@pytest.mark.parametrize("version", (1, 2, 3))
def test_levels_columns_and_repeated_fields_keep_independent_raw_records(
    version: int,
) -> None:
    first = _mod(b"Z001", b"Column one\0", level=1, pointer=1, trailer=0)
    second = _mod(b"Z001", b"Column two\0", level=1, pointer=2, trailer=0x31303053)
    payload = _custom_file(_object((first, second), version=version), version)

    report = parse_object_data_report(payload, "w3a")

    assert report.issues == ()
    mods = report.objects[0].mods
    assert [(m.level, m.data_pointer, m.value) for m in mods] == [
        (1, 1, "Column one"),
        (1, 2, "Column two"),
    ]
    assert [m.trailer for m in mods] == [0, 0x31303053]
    assert [m.raw_bytes for m in mods] == [first, second]
    assert mods[0].end_offset == mods[1].offset
    assert mods[1].end_offset == len(payload)
    assert report.objects[0].extra_ints == ()


def test_original_and_custom_offsets_and_latin1_ids_remain_source_absolute() -> None:
    original_mod = _mod(b"\xff +!", b"original\0")
    custom_mod = _mod(b"unam", '\ufeffa\t\r\nb"'.encode() + b"\0")
    original = _object((original_mod,), old_id=b"hfoo", new_id=b"\0" * 4)
    custom = _object((custom_mod,), extra_ints=(2, -3))
    payload = struct.pack("<ii", 3, 1) + original + struct.pack("<i", 1) + custom

    report = parse_object_data_report(payload, "w3u")

    assert report.issues == ()
    assert [obj.is_custom for obj in report.objects] == [False, True]
    mods = [obj.mods[0] for obj in report.objects]
    assert mods[0].field_id == "\xff +!"
    assert mods[0].offset == 24
    assert mods[1].offset == 8 + len(original) + 4 + 24
    assert [payload[m.offset : m.end_offset] for m in mods] == [
        original_mod,
        custom_mod,
    ]


@pytest.mark.parametrize("var_type", (1, 2))
def test_float_bits_are_preserved_without_reencoding(var_type: int) -> None:
    negative_zero = bytes.fromhex("00000080")
    encoded = _mod(b"real", negative_zero, var_type=var_type)

    report = parse_object_data_report(_custom_file(_object((encoded,))), "w3t")

    assert report.issues == ()
    assert report.objects[0].mods[0].raw_bytes == encoded
    assert report.objects[0].mods[0].raw_bytes[8:12] == negative_zero


@pytest.mark.parametrize("version", (1, 2, 3))
def test_trailing_bytes_are_diagnosed_without_losing_confirmed_object(
    version: int,
) -> None:
    encoded = _mod(b"unam", b"GOOD\0")
    payload = _custom_file(_object((encoded,), version=version), version)
    tail = b"UNRECOGNIZED-TAIL\x00\xff"

    report = parse_object_data_report(payload + tail, "w3t")

    assert report.objects[0].mods[0].raw_bytes == encoded
    assert len(report.issues) == 1
    assert f"trailing bytes at {len(payload)}" in report.issues[0]
    assert f"raw_hex={tail.hex()}" in report.issues[0]


@pytest.mark.parametrize("version", (2, 3))
def test_empty_tables_do_not_hide_unconsumed_bytes(version: int) -> None:
    report = parse_object_data_report(struct.pack("<iii", version, 0, 0) + b"\0", "w3u")

    assert report.objects == ()
    assert "trailing bytes at 12" in report.issues[0]


@pytest.mark.parametrize("version", (2, 3))
def test_each_truncated_mod_boundary_keeps_earlier_confirmed_fields(
    version: int,
) -> None:
    first = _mod(b"unam", b"CONFIRMED\0")
    second = _mod(b"utip", b"INCOMPLETE\0")
    payload = _custom_file(_object((first, second), version=version), version)
    second_offset = len(payload) - len(second)

    for kept in range(len(second)):
        report = parse_object_data_report(payload[: second_offset + kept], "w3t")

        assert len(report.objects) == 1, (kept, report)
        assert report.objects[0].mods[0].raw_bytes == first, (kept, report)
        assert len(report.objects[0].mods) == 1, (kept, report)
        assert report.objects[0].mods[0].end_offset == second_offset
        assert any(
            "retained 1 confirmed modifications" in issue for issue in report.issues
        )
        assert any("reader offset" in issue for issue in report.issues)


def test_partial_object_and_later_complete_object_are_both_retained() -> None:
    first = _mod(b"unam", b"FIRST\0")
    broken = b"utip" + struct.pack("<i", 99) + b"corrupt bytes"
    obj = _object((first, broken), version=2)
    later_mod = _mod(b"unam", b"LATER\0")
    later = _object((later_mod,), version=2, new_id=b"S002")
    payload = struct.pack("<iii", 2, 0, 2) + obj + later

    report = parse_object_data_report(payload, "w3t")

    assert [obj.new_id for obj in report.objects] == ["S001", "S002"]
    assert [obj.mods[0].raw_bytes for obj in report.objects] == [first, later_mod]
    assert any("unknown field type 99" in issue for issue in report.issues)
    assert any("resumed w3t table 1" in issue for issue in report.issues)


@pytest.mark.parametrize("count", (-1, 2147483647))
def test_invalid_v3_extra_count_diagnoses_encoded_boundary(count: int) -> None:
    payload = _custom_file(b"ratcS001" + struct.pack("<ii", count, 0))

    report = parse_object_data_report(payload, "w3t")

    assert report.objects == ()
    assert any(
        f"invalid extra-int count {count} at 20" in issue for issue in report.issues
    )


def test_v3_extra_array_cannot_consume_missing_modification_count() -> None:
    payload = _custom_file(b"ratcS001" + struct.pack("<iii", 2, 0, 1))

    report = parse_object_data_report(payload, "w3t")

    assert report.objects == ()
    assert any("invalid extra-int count 2" in issue for issue in report.issues)


def test_inflated_modification_count_keeps_all_complete_records() -> None:
    encoded = _mod(b"unam", b"CONFIRMED\0")
    payload = _custom_file(
        b"ratcS001" + struct.pack("<i", 2147483647) + encoded, version=2
    )

    report = parse_object_data_report(payload, "w3t")

    assert len(report.objects) == 1
    assert [m.raw_bytes for m in report.objects[0].mods] == [encoded]
    assert any(
        "invalid modification count 2147483647" in issue for issue in report.issues
    )
    assert any("retained 1 confirmed modifications" in issue for issue in report.issues)


def test_unterminated_string_is_never_a_confirmed_modification() -> None:
    payload = _custom_file(
        b"ratcS001"
        + struct.pack("<i", 1)
        + b"unam"
        + struct.pack("<i", 3)
        + b"unfinished",
        version=2,
    )

    report = parse_object_data_report(payload, "w3t")

    assert report.objects == ()
    assert any("unterminated string" in issue for issue in report.issues)

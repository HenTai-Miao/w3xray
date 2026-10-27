"""Typed snapshot evidence never promotes missing bytes or profile claims."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import replace

import pytest

from gametool.live_field_evidence import (
    LiveFieldEvidence,
    LiveFieldLayout,
    extract_item_fields,
    extract_layout_fields,
    extract_resource_fields,
    extract_unit_fields,
    observed_field,
    reconcile_field_evidence,
)

BASE = 0x100000


class Reader:
    def __init__(self, regions: dict[int, bytes]) -> None:
        self.regions = regions
        self.calls: list[tuple[int, int]] = []

    def read(self, addr: int, size: int) -> bytes | None:
        self.calls.append((addr, size))
        for base, blob in self.regions.items():
            offset = addr - base
            if 0 <= offset and offset + size <= len(blob):
                return blob[offset : offset + size]
        return None


def layout(
    key: str = "health",
    value_type: str = "f32",
    offset: int | None = 0,
    *,
    pointers: tuple[int, ...] = (),
    source: str = "independently measured fixture",
    evidence: str = "confirmed",
) -> LiveFieldLayout:
    return LiveFieldLayout(
        "unit", key, value_type, source, evidence, offset, pointers, "fixture field"
    )


def extract(
    reader: Reader,
    fields: list[LiveFieldLayout],
    *,
    pointer_size: int = 4,
    qualification: str = "confirmed",
) -> list[LiveFieldEvidence]:
    return extract_layout_fields(
        reader,
        BASE,
        fields,
        scope="unit",
        build="1.27.0.52240",
        profile="fixture-profile-r1",
        pointer_size=pointer_size,
        qualification=qualification,
    )


@pytest.mark.parametrize(
    ("value_type", "fmt", "value"),
    [
        ("u8", "<B", 0),
        ("u16", "<H", 65535),
        ("u32", "<I", 0xFFFFFFFF),
        ("u64", "<Q", 0xFFFFFFFFFFFFFFFF),
        ("i8", "<b", -128),
        ("i16", "<h", -32768),
        ("i32", "<i", -(1 << 31)),
        ("i64", "<q", -(1 << 63)),
        ("f32", "<f", -0.0),
        ("f64", "<d", 1.1234567890123457),
        ("pointer", "<I", 0),
    ],
)
def test_all_encoded_types_keep_exact_values_bytes_and_provenance(
    value_type: str, fmt: str, value: int | float
) -> None:
    raw = struct.pack(fmt, value)
    reader = Reader({BASE: raw})
    field = extract(reader, [layout(value_type=value_type)])[0]
    assert field.value == value
    assert field.state == "confirmed" and field.complete
    assert field.address == BASE
    assert field.raw_bytes == raw.hex()
    assert field.scope == "unit"
    assert field.build == "1.27.0.52240"
    assert field.profile == "fixture-profile-r1"
    assert field.source == "independently measured fixture"
    assert field.to_dict()["diagnostics"] == []
    assert reader.calls == [(BASE, len(raw))]
    if isinstance(value, float) and value == 0:
        assert isinstance(field.value, float)
        assert math.copysign(1, field.value) == -1


def test_fourcc_preserves_punctuation_case_and_every_latin1_byte() -> None:
    code = " a.ÿ"
    raw = int.from_bytes(code.encode("latin-1"), "big").to_bytes(4, "little")
    result = extract(Reader({BASE: raw}), [layout(value_type="fourcc")])[0]
    assert result.value == code
    assert result.raw_bytes == raw.hex()


def test_zero_is_confirmed_but_missing_is_unavailable_and_never_zero() -> None:
    reader = Reader({BASE: struct.pack("<f", 0.0)})
    result = extract(reader, [layout("zero"), layout("missing", offset=4)])
    assert result[0].value == 0.0 and result[0].state == "confirmed"
    assert result[1].value is None and result[1].state == "unavailable"
    assert result[1].address == BASE + 4
    assert not result[1].complete
    assert "快照未覆盖" in result[1].diagnostics[0]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_values_keep_raw_evidence_and_invalid_state(value: float) -> None:
    raw = struct.pack("<f", value)
    result = extract(Reader({BASE: raw}), [layout()])[0]
    assert result.value is None
    assert result.state == "invalid"
    assert result.raw_bytes == raw.hex()
    assert result.address == BASE
    assert "NaN" in result.diagnostics[0]
    json.dumps(result.to_dict(), allow_nan=False)


def test_claimed_confirmation_requires_independent_runtime_qualification() -> None:
    reader = Reader({BASE: struct.pack("<f", 10.5)})
    result = extract_layout_fields(
        reader,
        BASE,
        [layout(evidence="confirmed")],
        scope="unit",
        build="3.0.0.24268",
        profile="unverified-build",
        pointer_size=4,
    )[0]
    assert result.value == 10.5
    assert result.state == "declared-layout-only"
    assert not result.complete
    assert result.diagnostics
    result2 = extract(reader, [layout(evidence="declared-layout-only")])[0]
    assert result2.state == "declared-layout-only"


def test_pointer_chains_read_every_declared_hop_and_exact_value_bytes() -> None:
    reader = Reader(
        {
            BASE - 4: struct.pack("<I", BASE + 0x100),
            BASE + 0x108: struct.pack("<I", BASE + 0x200),
            BASE + 0x1F0: struct.pack("<d", 1.23456789012345),
        }
    )
    result = extract(
        reader,
        [layout(value_type="f64", offset=None, pointers=(-4, 8, -16))],
    )[0]
    assert result.value == 1.23456789012345
    assert result.address == BASE + 0x1F0
    assert result.pointer_addresses == (BASE - 4, BASE + 0x108)
    assert reader.calls == [(BASE - 4, 4), (BASE + 0x108, 4), (BASE + 0x1F0, 8)]


def test_x64_pointer_chains_use_declared_width_and_preserve_large_addresses() -> None:
    high_address = (1 << 40) + 0x1234
    reader = Reader(
        {BASE: struct.pack("<Q", high_address), high_address + 8: struct.pack("<Q", 0)}
    )
    result = extract(
        reader,
        [layout(value_type="pointer", offset=None, pointers=(0, 8))],
        pointer_size=8,
    )[0]
    assert result.value == 0
    assert result.address == high_address + 8
    assert reader.calls == [(BASE, 8), (high_address + 8, 8)]


def test_unreadable_null_and_overflowing_pointer_hops_never_continue() -> None:
    recipe = layout(offset=None, pointers=(0, 8))
    unreadable = Reader({})
    result = extract(unreadable, [recipe])[0]
    assert result.state == "unavailable" and result.value is None
    assert unreadable.calls == [(BASE, 4)]
    null_reader = Reader({BASE: bytes(4)})
    result = extract(null_reader, [recipe])[0]
    assert result.state == "unavailable" and "NULL" in result.diagnostics[0]
    assert null_reader.calls == [(BASE, 4)]
    high_reader = Reader({BASE: struct.pack("<I", 0xFFFFFFFF)})
    result = extract(high_reader, [recipe])[0]
    assert result.state == "invalid" and result.value is None
    assert high_reader.calls == [(BASE, 4)]
    assert result.pointer_addresses == (BASE,)


def test_exact_address_end_is_readable_but_crossing_and_null_roots_are_not() -> None:
    reader = Reader({0xFFFFFFFF: b"\x00"})
    good = extract_layout_fields(
        reader,
        0xFFFFFFFF,
        [layout(value_type="u8")],
        scope="unit",
        build="fixture",
        profile="fixture",
        pointer_size=4,
        qualification="confirmed",
    )[0]
    assert good.value == 0
    bad = extract_layout_fields(
        reader,
        0xFFFFFFFF,
        [layout(value_type="u16")],
        scope="unit",
        build="fixture",
        profile="fixture",
        pointer_size=4,
    )[0]
    assert bad.state == "invalid" and bad.value is None
    assert reader.calls == [(0xFFFFFFFF, 1)]
    for address in (0, -1, True, 1 << 32):
        result = extract_layout_fields(
            reader,
            address,
            [layout()],
            scope="unit",
            build="fixture",
            profile="fixture",
            pointer_size=4,
        )[0]
        assert result.state == "invalid" and result.value is None
    assert reader.calls == [(0xFFFFFFFF, 1)]


def test_short_reads_and_exceptions_retain_complete_diagnostics() -> None:
    class ShortReader(Reader):
        def read(self, addr: int, size: int) -> bytes:
            return b"\x00\x00"

    result = extract(ShortReader({}), [layout()])[0]
    assert result.state == "unavailable" and result.value is None
    assert result.raw_bytes == "0000"
    assert "2/4" in result.diagnostics[0]

    class FailedReader(Reader):
        def read(self, addr: int, size: int) -> bytes:
            raise OSError("fixture unreadable")

    failed = extract(FailedReader({}), [layout()])[0]
    assert failed.state == "unavailable"
    assert "OSError: fixture unreadable" in failed.diagnostics[0]


def test_manual_malformed_recipes_fail_before_any_memory_read() -> None:
    reader = Reader({BASE: bytes(8)})
    bad = replace(layout(), value_type="python")
    with pytest.raises(ValueError, match="type"):
        extract(reader, [bad])
    bad = replace(layout(), offset=None, pointer_offsets=())
    with pytest.raises(ValueError, match="pointer_offsets"):
        extract(reader, [bad])
    bad = replace(layout(), pointer_offsets=(0, 8))
    with pytest.raises(ValueError, match="pointer_offsets"):
        extract(reader, [bad])
    assert reader.calls == []


def test_unknown_scope_is_a_diagnostic_boundary_before_reads() -> None:
    reader = Reader({BASE: bytes(8)})
    with pytest.raises(ValueError, match="scope"):
        extract_layout_fields(
            reader,
            BASE,
            [layout()],
            scope="unknown semantic scope",
            build="fixture",
            profile="fixture",
            pointer_size=4,
        )
    assert reader.calls == []


def test_duplicate_same_key_keeps_all_sources_and_marks_conflicting_values() -> None:
    reader = Reader({BASE: struct.pack("<fff", 0.0, 1.0, 0.0)})
    results = extract(
        reader,
        [
            layout(offset=0, source="zero evidence"),
            layout(offset=4, source="one evidence"),
            layout(offset=8, source="independent zero evidence"),
        ],
    )
    assert [row.value for row in results] == [0.0, 1.0, 0.0]
    assert [row.source for row in results] == [
        "zero evidence",
        "one evidence",
        "independent zero evidence",
    ]
    assert all(row.state == "conflict" for row in results)
    assert all("冲突" in row.diagnostics[-1] for row in results)
    equal = extract(reader, [layout(offset=0), layout(offset=8)])[0]
    assert equal.state == "confirmed"


def test_pointer_chain_has_no_recursive_depth_quota() -> None:
    count = 1500
    blob = bytearray((count + 1) * 4)
    for index in range(count):
        struct.pack_into("<I", blob, index * 4, BASE + (index + 1) * 4)
    struct.pack_into("<f", blob, count * 4, 12.25)
    reader = Reader({BASE: bytes(blob)})
    result = extract(reader, [layout(offset=None, pointers=(0,) * (count + 1))])[0]
    assert result.value == 12.25
    assert len(result.pointer_addresses) == count
    assert len(reader.calls) == count + 1


def test_unit_evidence_keeps_each_axis_missing_owner_and_zero_distinct() -> None:
    raw_code = int.from_bytes(b"h00A", "big").to_bytes(4, "little")
    reader = Reader({BASE: raw_code + b"\x00", BASE + 8: struct.pack("<f", 0.0)})
    rows = extract_unit_fields(
        reader,
        BASE,
        offsets={"code": 0, "owner": 4, "x": 8, "y": 12},
        build="fixture",
        profile="fixture",
        source="fixture declared layout",
    )
    fields = {row.key: row for row in rows}
    assert fields["code"].value == "h00A"
    assert fields["owner"].value == 0 and fields["owner"].state == "confirmed"
    assert fields["x"].value == 0 and fields["x"].state == "confirmed"
    assert fields["y"].value is None and fields["y"].state == "unavailable"
    assert fields["address"].value == BASE
    no_layout = extract_unit_fields(
        reader,
        BASE,
        offsets={},
        build="fixture",
        profile="fixture",
        source="no offsets provided",
    )
    assert len(no_layout) == 5
    assert all(row.value is None for row in no_layout[1:])


def test_owner_outside_proved_classic_slot_domain_stays_invalid_raw_evidence() -> None:
    rows = extract_unit_fields(
        Reader({BASE: b"\xff"}),
        BASE,
        offsets={"owner": 0},
        build="fixture",
        profile="fixture",
        source="classic slot layout",
    )
    owner = next(row for row in rows if row.key == "owner")
    assert owner.state == "invalid"
    assert owner.value == 255 and owner.raw_bytes == "ff"


def test_item_slot_zero_and_item_address_are_attributable() -> None:
    raw = int.from_bytes(b"I001", "big").to_bytes(4, "little")
    rows = extract_item_fields(
        Reader({BASE: raw}),
        BASE,
        code_offset=0,
        slot=0,
        slot_address=BASE + 100,
        build="fixture",
        profile="fixture",
        source="resolved slot handle pair",
    )
    fields = {row.key: row for row in rows}
    assert fields["slot"].value == 0 and fields["slot"].state == "confirmed"
    assert fields["slot"].address == BASE + 100
    assert fields["code"].value == "I001"
    assert fields["address"].value == BASE


def test_calibrated_resources_keep_precision_and_never_guess_food() -> None:
    rows = extract_resource_fields(
        Reader({BASE: struct.pack("<ff", 0.0, 123.125)}),
        BASE,
        gold_offset=0,
        lumber_offset=4,
        build="fixture",
        profile="fixture",
        source="calibrated resource anchor",
    )
    fields = {row.key: row for row in rows}
    assert fields["gold"].value == 0.0 and fields["gold"].state == "confirmed"
    assert fields["lumber"].value == 123.125
    assert fields["food"].value is None
    assert fields["food"].state == "unavailable"
    assert fields["lumber"].address == BASE + 4


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("u32", True),
        ("u32", 1.0),
        ("u32", -1),
        ("u32", 1 << 32),
        ("f32", math.nan),
        ("f64", math.inf),
        ("fourcc", "too long"),
        ("fourcc", "你123"),
        ("pointer", "0x1000"),
        ("unknown-provider", 42),
    ],
)
def test_observed_values_enforce_types_without_coercion(
    value_type: str, value: int | float | str | None
) -> None:
    result = observed_field(
        key="test",
        label="test",
        value=value,
        value_type=value_type,
        source="independent observation",
    )
    assert result.value is None
    assert result.state == "invalid"
    assert result.diagnostics


def test_observed_missing_value_retains_existing_diagnostics_and_unknown_state() -> (
    None
):
    result = observed_field(
        key="gold",
        label="gold",
        value=None,
        value_type="f32",
        state="unknown",
        diagnostics=("calibration unavailable", "profile unverified"),
        source="snapshot",
    )
    assert result.value is None and result.state == "unknown"
    assert result.diagnostics == ("calibration unavailable", "profile unverified")


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("f32", 1e300),
        ("f32", -1e300),
        ("f32", 2**1024),
        ("f64", 2**1024),
        ("f64", -(2**1024)),
    ],
)
def test_observed_float_overflow_is_invalid_without_raising(
    value_type: str, value: int | float
) -> None:
    evidence = observed_field(
        key="amount",
        label="amount",
        value=value,
        value_type=value_type,
        source="independent observation",
    )
    assert evidence.state == "invalid"
    assert evidence.value is None
    assert any("浮点编码范围" in note for note in evidence.diagnostics)


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("f32", struct.unpack("<f", bytes.fromhex("ffff7f7f"))[0]),
        ("f64", float.fromhex("0x1.fffffffffffffp+1023")),
        ("f32", 0.0),
        ("f32", -0.0),
        ("f64", 0.0),
        ("f64", -0.0),
        ("f32", 1.1234567890123457),
    ],
)
def test_observed_finite_float_boundaries_preserve_unrounded_value(
    value_type: str, value: float
) -> None:
    evidence = observed_field(
        key="amount",
        label="amount",
        value=value,
        value_type=value_type,
        source="independent observation",
    )
    assert evidence.state == "confirmed"
    assert evidence.value == value
    assert isinstance(evidence.value, float)
    assert math.copysign(1, evidence.value) == math.copysign(1, value)


@pytest.mark.parametrize("pointer_size", [4, 8])
def test_item_slot_address_respects_declared_architecture_without_extra_read(
    pointer_size: int,
) -> None:
    reader = Reader({BASE: bytes(4)})

    def item_at_slot(slot_address: int) -> list[LiveFieldEvidence]:
        return extract_item_fields(
            reader,
            BASE,
            slot_address=slot_address,
            code_offset=0,
            slot=0,
            build="fixture",
            profile="fixture",
            source="independently traversed slot",
            pointer_size=pointer_size,
        )

    invalid_address = 1 << (pointer_size * 8)
    rows = item_at_slot(invalid_address)
    slot = next(row for row in rows if row.key == "slot")
    assert slot.value == 0 and slot.state == "invalid"
    assert slot.address == invalid_address
    assert any("地址空间" in note for note in slot.diagnostics)
    assert reader.calls == [(BASE, 4)]
    rows = item_at_slot(invalid_address - 1)
    slot = next(row for row in rows if row.key == "slot")
    assert slot.value == 0 and slot.state == "confirmed"
    assert slot.address == invalid_address - 1
    assert reader.calls == [(BASE, 4), (BASE, 4)]


def test_public_reconciliation_preserves_both_channels_and_is_idempotent() -> None:
    builtin = extract(Reader({BASE: struct.pack("<f", 0.0)}), [layout("x")])[0]
    declared = extract(
        Reader({BASE + 4: struct.pack("<f", 100.25)}),
        [
            layout(
                "x",
                offset=4,
                source="declared fixture",
                evidence="declared-layout-only",
            )
        ],
    )[0]
    missing = observed_field(
        key="x",
        label="unreadable x mirror",
        value=None,
        value_type="f32",
        state="unavailable",
        diagnostics=("original unreadable mirror diagnostic",),
        source="third source",
        scope="unit",
    )
    originals = (builtin, declared, missing)
    rows = reconcile_field_evidence(originals)
    assert [row.state for row in originals] == [
        "confirmed",
        "declared-layout-only",
        "unavailable",
    ]
    assert [row.state for row in rows] == ["conflict"] * 3
    for original, row in zip(originals, rows, strict=True):
        assert row.value == original.value
        assert row.source == original.source
        assert row.address == original.address
        assert row.raw_bytes == original.raw_bytes
        assert row.diagnostics[: len(original.diagnostics)] == original.diagnostics
    assert reconcile_field_evidence(rows) == rows
    assert reconcile_field_evidence((declared, missing)) == [declared, missing]

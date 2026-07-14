"""Regression coverage for fixed preplaced-unit random flags."""

from __future__ import annotations

import struct

from w3xtool.doo import parse_units


def test_parse_units_keeps_fixed_units_with_negative_one_random_flag() -> None:
    # Given: two version-8 fixed units whose random-unit flag is -1.
    first = _fixed_unit("sloc", serial=1)
    second = _fixed_unit("ndrp", serial=2)
    payload = b"W3do" + _i32(8) + _i32(11) + _i32(2) + first + second

    # When: the classic placement layout is parsed.
    units = parse_units(payload)

    # Then: the no-payload flag preserves both record boundaries.
    assert [(unit.type_id, unit.serial) for unit in units] == [
        ("sloc", 1),
        ("ndrp", 2),
    ]


def _fixed_unit(type_id: str, *, serial: int) -> bytes:
    return b"".join(
        (
            type_id.encode("latin-1"),
            _i32(0),
            _f32(1280.0),
            _f32(-6848.0),
            _f32(0.0),
            _f32(0.0),
            _f32(1.0),
            _f32(1.0),
            _f32(1.0),
            b"\x02",
            _i32(0),
            b"\x00\x00",
            _i32(0),
            _i32(0),
            _i32(-1),
            _i32(0),
            _i32(0),
            _f32(0.0),
            _i32(0),
            _i32(0),
            _i32(0),
            _i32(0),
            _i32(0),
            _i32(0),
            _i32(-1),
            _i32(-1),
            _i32(-1),
            _i32(serial),
        )
    )


def _i32(value: int) -> bytes:
    return struct.pack("<i", value)


def _f32(value: float) -> bytes:
    return struct.pack("<f", value)

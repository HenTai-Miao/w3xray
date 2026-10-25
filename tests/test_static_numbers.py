"""Numeric completeness without interpreter recursion or display rounding."""

from __future__ import annotations

import math
import pickle
from pathlib import Path

import pytest

from gametool.object_candidate_values import resolved_source_value
from gametool.object_detail_presentation import back_reference_note
from gametool.pack_query_placements import script_placements
from gametool.static_numbers import format_number, static_number
from gametool.w3world import Camera, Region
from gametool.world_exports import format_cameras_tsv, format_regions_tsv


@pytest.mark.parametrize(
    ("expression", "value"),
    [
        ("-2**2", -4),
        ("2**-2", 0.25),
        ("2**3**2", 512),
        ("(-2)**2", 4),
        ("--2", 2),
        ("-(1+2)*3", -9),
        ("0x10+$20", 48),
        ("5//2+5%2", 3),
        ("1e-3*1000", 1),
    ],
)
def test_static_number_precedence(expression: str, value: float) -> None:
    assert static_number(expression) == value


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "1+",
        "()",
        "1 2",
        "(1",
        "1)",
        "true",
        "NaN",
        "1e5000",
        "1/0",
        "(-1)**.5",
        "object.x",
        "GetUnitX(u)",
        "__import__('os')",
        "2^3",
    ],
)
def test_dynamic_invalid_and_nonfinite_coordinates_are_not_executed(
    expression: str,
) -> None:
    assert static_number(expression) is None


def test_numeric_nesting_unary_and_operator_chains_have_no_recursion_limit() -> None:
    assert static_number("(" * 20_000 + "- 5" + ")" * 20_000) == -5
    assert static_number("- " * 20_001 + "1") == -1
    assert static_number("+".join(["1"] * 20_000)) == 20_000
    assert static_number("-2^2+8//3", lua=True) == -2


def test_integer_fourcc_keeps_non_ascii_bytes() -> None:
    assert script_placements("call CreateItem($80303031,0,0)") == [
        ("\x80001", 0.0, 0.0, "item")
    ]


@pytest.mark.parametrize(
    "value", [0.0, -0.0, 0.12345678901234568, 12345.6787109375, 1e308, -1e-308]
)
def test_number_text_and_object_fields_round_trip(value: float) -> None:
    text = format_number(value)
    assert float(text) == value
    assert math.copysign(1, float(text)) == math.copysign(1, value)
    assert float(resolved_source_value(value, {})) == value


def test_world_exports_and_back_references_preserve_coordinates() -> None:
    x, y = 12345.6787109375, -9876.5439453125
    region = Region(x, y, x + 1, y + 1, "区域", 1, "", "", (0, 0, 0), 255)
    row = format_regions_tsv([region]).splitlines()[1].split("\t")
    assert tuple(float(value) for value in row[2:6]) == (x, y, x + 1, y + 1)
    camera = Camera(x, y, 0.123456789, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "镜头")
    row = format_cameras_tsv([camera]).splitlines()[1].split("\t")
    assert tuple(float(value) for value in row[1:4]) == (x, y, 0.123456789)
    assert f"{x}, {y}" in back_reference_note("单位", ((0, x, y),))


def test_client_snapshot_cache_invalidates_pre_precision_fields(tmp_path: Path) -> None:
    from gametool import client_object_data as client

    value = 0.12345678901234568
    snapshot = client.ClientObjectSnapshot(
        (
            client.ClientBaseObject(
                "n001", "单位", (("数值", format_number(value)),), ()
            ),
        ),
        True,
    )
    path = tmp_path / "client.pkl"
    path.write_bytes(b"gamexray-client-snapshot-v1\n" + pickle.dumps(snapshot))
    assert client._load_snapshot_cache(path) is None
    client._store_snapshot_cache(path, snapshot)
    restored = client._load_snapshot_cache(path)
    assert restored is not None
    assert float(restored.objects[0].fields[0][1]) == value

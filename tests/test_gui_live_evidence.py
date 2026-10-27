"""Complete synthetic live reports and direct, category-correct handoffs."""

from __future__ import annotations

from decimal import Decimal

import pytest

from gametool.gui_live_evidence import (
    display_value,
    format_live_details,
    item_records,
    object_query,
    parse_live_output,
    preferred_selection,
    selected_records,
    selection_status,
    unit_near_query,
)
from gametool.live_report_json import ExactJsonNumber
from gametool.object_codes import encode_object_id_query


def test_tail_decoder_keeps_the_whole_root_and_every_exact_number() -> None:
    raw = '{"selected_units":[{"code":"hfoo","x":1.234567890123456789,"y":-2e-100}],"selection_complete":true}'
    parsed = parse_live_output("完整文字摘要\n" + raw + "\n")
    assert parsed.json_text == raw
    assert parsed.report is not None
    unit = selected_records(parsed.report)[0]
    assert str(unit["x"]) == "1.234567890123456789"
    assert unit_near_query(unit, "100") == "near 1.234567890123456789 -2e-100 100"


@pytest.mark.parametrize(
    "raw",
    (
        '{"selected_units":[\n{"code":"hfoo"}\n',
        '{"selected_units":[],"selected_units":[{"code":"hfoo"}]}',
        '{"selected_units":[]}\n{"selected_units":[{"code":"hfoo"}]}',
        '{"selected_units":[],"x":NaN}',
        '{"selected_units":[]}\nnot JSON',
    ),
)
def test_malformed_or_ambiguous_tail_never_becomes_a_nested_report(raw: str) -> None:
    parsed = parse_live_output(raw)
    assert parsed.report is None
    assert parsed.diagnostic


def test_explicit_empty_and_partial_selections_never_fall_back() -> None:
    legacy = {"unit": "旧单位", "code": "hfoo", "addr": 4000}
    complete = {
        "selected_units": [],
        "selected_unit": legacy,
        "selection_complete": True,
    }
    assert selected_records(complete) == ()
    assert "没有选中" in selection_status(complete)
    incomplete = {
        **complete,
        "selection_complete": False,
        "selection_diagnostics": ["unreadable second node"],
    }
    assert "不完整" in selection_status(incomplete)
    assert "unreadable second node" in format_live_details(incomplete, None)
    assert selected_records({"selected_unit": legacy}) == (legacy,)
    assert "范围未知" in selection_status({"selected_unit": legacy})
    malformed = {**complete, "selected_units": ["invalid node"]}
    assert "没有选中" not in selection_status(malformed)
    assert "无效" in selection_status(malformed)


def test_choice_preserves_unique_instance_only_in_matching_identity() -> None:
    first = {"code": "hfoo", "addr": 4096}
    second = {"code": "hfoo", "addr": 8192}
    identity = {
        "pid": 71,
        "exe_path": "fixture-war3.exe",
        "opened_process": "fixture-A",
    }
    old = {"process_identity": identity, "selected_units": [first, second]}
    new = {"process_identity": dict(identity), "selected_units": [second, first]}
    assert preferred_selection(old, first, new) == 1
    assert (
        preferred_selection(old, first, {**new, "process_identity": {"pid": 72}}) == 0
    )
    assert preferred_selection(old, first, {**new, "selected_units": []}) is None
    assert (
        preferred_selection(old, first, {**new, "selected_units": [first, first]}) == 0
    )


def test_details_keep_zero_unknown_typed_provenance_extensions_and_all_items() -> None:
    evidence = [
        {
            "key": "health",
            "label": "生命",
            "value": 0,
            "value_type": "f32",
            "state": "declared-layout-only",
            "source": "fixture profile",
            "address": 4500,
            "diagnostics": ["layout unverified"],
            "offset": 24,
        }
    ]
    unit = {
        "unit": "同名单元",
        "code": "hfoo",
        "addr": 4096,
        "owner": 0,
        "x": None,
        "y": 0,
        "evidence": evidence,
        "items": [
            {"slot": i, "name": f"物品{i}", "code": "I001", "addr": 5000 + i}
            for i in range(101)
        ],
    }
    report = {
        "selected_units": [unit],
        "selection_complete": False,
        "selection_diagnostics": ["cycle @ 0x99"],
        "notes": ["unsupported field"],
    }
    text = format_live_details(report, unit, item_records(unit)[-1])
    for expected in (
        "declared-layout-only",
        "fixture profile",
        "0x1194",
        "layout unverified",
        "offset: 24",
        "所属玩家: 0",
        "值: 0",
        "X: 未知",
        "物品100",
        "cycle @ 0x99",
        "unsupported field",
    ):
        assert expected in text
    assert text.count("槽 ") == 101


@pytest.mark.parametrize("code", ("I001", "1!._", " a| "))
def test_actions_use_exact_id_and_known_category(code: str) -> None:
    record = {"code": code, "unit": "名字不能充当身份"}
    assert object_query(record, "detail") == "units " + encode_object_id_query(code)
    assert object_query(record, "where") == "drop " + encode_object_id_query(code)
    assert object_query(
        record, "detail", item=True
    ) == "item " + encode_object_id_query(code)
    assert object_query(
        record, "where", item=True
    ) == "where " + encode_object_id_query(code)
    assert object_query(record, "drop", item=True) == "drop " + encode_object_id_query(
        code
    )
    assert object_query({"code": "invalid"}, "detail") is None


@pytest.mark.parametrize("x", (True, None, "1.0", float("nan"), float("inf")))
def test_near_requires_actual_finite_axes(x: object) -> None:
    assert unit_near_query({"x": x, "y": 0, "code": "1234", "owner": 5}) is None


def test_deep_complete_report_and_big_numeric_values_have_no_python_quotas() -> None:
    nested = "[" * 1500 + "0" + "]" * 1500
    parsed = parse_live_output('{"selected_units":[],"extension":' + nested + "}")
    assert parsed.report is not None
    assert display_value(parsed.report["extension"]) == nested
    assert (
        unit_near_query(
            {"x": Decimal("-0.0000000000000000001"), "y": ExactJsonNumber("9e100000")},
            "100",
        )
        == "near -1E-19 9e100000 100"
    )


def test_resource_details_keep_exact_candidates_separate_from_player_chain_evidence() -> (
    None
):
    candidate = {
        "addr": 0x1010,
        "gold": 1,
        "gold_exact": Decimal("1.234567890123456789"),
        "source": "scan-candidate",
        "evidence": [
            {
                "key": "gold",
                "value": Decimal("1.234567890123456789"),
                "value_type": "f32",
                "state": "confirmed",
                "source": "scan-candidate",
                "address": 0x1020,
                "raw_bytes": "52069e3f",
                "diagnostics": ["owner unassigned"],
            }
        ],
    }
    players = [
        {
            "owner": index,
            "gold": 0,
            "gold_exact": 0,
            "source": f"player-chain-{index}",
            "evidence": [
                {
                    "key": "gold",
                    "value": 0,
                    "value_type": "i32",
                    "state": "declared-layout-only",
                    "source": "chain-source",
                    "address": 0x2000 + index,
                    "scale_denominator": 10,
                    "raw_bytes": "00000000",
                    "diagnostics": [f"unverified-owner-{index}"],
                }
            ],
        }
        for index in range(103)
    ]
    text = format_live_details(
        {
            "selected_units": [],
            "selection_complete": True,
            "resources": [candidate],
            "resources_complete": False,
            "player_resources": players,
            "player_resources_complete": False,
        },
        None,
    )
    assert "【资源扫描候选（未归属玩家）】" in text
    assert "【按玩家槽的资源链证据】" in text
    for expected in (
        "1.234567890123456789",
        "owner unassigned",
        "f32",
        "i32",
        "scale_denominator: 10",
        "00000000",
        "declared-layout-only",
        "player-chain-102",
        "unverified-owner-102",
        "owner: 102",
        "值: 0",
    ):
        assert expected in text
    assert text.count("unverified-owner-") == 103

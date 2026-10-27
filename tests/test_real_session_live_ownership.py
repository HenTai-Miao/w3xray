"""Unit ownership and resource attribution are independent read-only channels."""

from __future__ import annotations

from collections import Counter

import pytest


_UNIT = {
    "owner": 2,
    "unit": "fixture unit",
    "code": "H004",
    "addr": 4096,
    "x": 1,
    "y": 2,
}


@pytest.mark.parametrize("owned", (None, [], [_UNIT]))
@pytest.mark.parametrize("resource_rows", (None, [], ["玩家3(fixture): 金169 木808"]))
@pytest.mark.parametrize("want_resources", (False, True))
def test_unit_listing_and_resource_attribution_remain_independent(
    monkeypatch, capsys, owned, resource_rows, want_resources
):
    from gametool import live_inventory

    report = {
        "strategy_used": None,
        "slots": [],
        "owned_units": owned,
        "owner_counts": None
        if owned is None
        else dict(Counter(u["owner"] for u in owned)),
        "resources": [] if want_resources and resource_rows is not None else None,
        "player_rows": resource_rows,
    }
    monkeypatch.setattr(live_inventory, "read_live", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(live_inventory, "append_live_journal", lambda _report: None)
    args = ["--pack", "unused", "--players"]
    if want_resources:
        args += ["--resources", "auto"]

    code = live_inventory.main(args)
    output = capsys.readouterr().out

    if owned is None:
        assert "== 单位归属不可读 ==" in output
        assert "== 玩家单位" not in output
    else:
        assert "== 单位归属不可读 ==" not in output
        assert "== 归属不可读 ==" not in output
        assert f"== 玩家单位 (全槽位, 共{len(owned)}个) ==" in output
        if owned:
            assert "P2 fixture unit [H004] @ (1, 2)" in output
    assert ("== 资源归属不可读 ==" in output) is (
        want_resources and resource_rows is None
    )
    assert "你+队友" not in output
    assert "<-- 你" not in output
    confirmed_request = owned is not None or (
        want_resources and resource_rows is not None
    )
    assert code == (0 if confirmed_request else 2)


def test_resource_rows_never_claim_the_selected_units_owner(monkeypatch, capsys):
    from gametool import live_inventory

    report = {
        "strategy_used": "handle",
        "slots": [],
        "selected_unit": {**_UNIT, "items": []},
        "owned_units": None,
        "owner_counts": None,
        "resources": [],
        "player_rows": ["玩家3(fixture): 金169 木808"],
    }
    monkeypatch.setattr(live_inventory, "read_live", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(live_inventory, "append_live_journal", lambda _report: None)

    assert live_inventory.main(["--pack", "unused", "--resources", "auto"]) == 0
    assert "当前选中(归属未知): fixture unit [H004]" in capsys.readouterr().out


def test_large_confirmed_owner_distribution_is_not_declared_garbage(
    monkeypatch, capsys
):
    from gametool import live_inventory

    report = {
        "strategy_used": None,
        "slots": [],
        "owned_units": [{**_UNIT, "addr": 4096 + index * 4} for index in range(1201)],
        "owner_counts": {2: 1201},
        "resources": None,
        "player_rows": None,
    }
    monkeypatch.setattr(live_inventory, "read_live", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(live_inventory, "append_live_journal", lambda _report: None)

    assert live_inventory.main(["--pack", "unused", "--players"]) == 0
    output = capsys.readouterr().out
    assert "疑似垃圾读数" not in output
    assert "P2 fixture unit [H004]" in output

"""Direct resource API requests use the same verified snapshot orchestration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def resource_api(monkeypatch, tmp_path):
    from gametool import live_handle_chain as hc, live_inventory as live
    from tests.test_live_handle_chain import DLL_BASE, _build_memory

    regions, hero, _other, _offsets = _build_memory()
    profile = hc.resolve_profile("1.27.0.52240", "classic", "x86")
    resource_rows = [hc.PlayerResources(4096, 169.0, 808.0, 4, 12)]
    monkeypatch.setattr(live, "mem_setup", Mock())
    monkeypatch.setattr(live, "find_war3_pids", Mock(return_value=[42]))
    monkeypatch.setattr(live, "open_process", Mock(return_value=123))
    monkeypatch.setattr(live, "_process_identity", lambda _handle: "war3.exe")
    monkeypatch.setattr(live, "_integrity_rid", lambda _handle: None)
    monkeypatch.setattr(live, "k32", SimpleNamespace(CloseHandle=Mock()))
    monkeypatch.setattr(live, "snapshot", Mock(return_value=(regions, 0)))
    monkeypatch.setattr(live, "save_snapshot", Mock(return_value=tmp_path / "snapshot"))
    monkeypatch.setattr(live, "load_names", lambda *_args: {})
    monkeypatch.setattr(
        live, "load_profile_override", Mock(return_value=(profile, "fixture profile"))
    )
    monkeypatch.setattr(
        live, "verify_opened_process", Mock(return_value="fixture identity warning")
    )
    monkeypatch.setattr(
        live,
        "detect_version",
        Mock(
            return_value={
                "engine": "classic",
                "arch": "x86",
                "version": "1.27.0.52240",
                "game_dll": {"base": DLL_BASE},
            }
        ),
    )
    monkeypatch.setattr(hc, "verify_profile", Mock(return_value=(True, [], [])))
    monkeypatch.setattr(hc, "derive_offsets", Mock(return_value=None))
    monkeypatch.setattr(
        hc, "read_player_resources_chain", Mock(return_value=resource_rows)
    )
    monkeypatch.setattr(hc, "find_resource_layout", Mock(return_value=resource_rows))
    monkeypatch.setattr(hc, "cached_resource_hit", lambda: False)
    monkeypatch.setattr(
        hc,
        "walk_owned_units",
        Mock(
            return_value=[
                SimpleNamespace(owner=2, code="H004", addr=hero, x=1, y=2),
            ]
        ),
    )
    return live, hc, regions


@pytest.mark.parametrize("strategy", ("auto", "handle"))
def test_direct_resource_api_snapshots_verifies_and_normalizes(resource_api, strategy):
    live, hc, _regions = resource_api

    report = live.read_live(
        "unused", strategy=strategy, resources=(169, 808), pid=42, verbose=False
    )

    live.snapshot.assert_called_once()
    hc.verify_profile.assert_called_once()
    live.verify_opened_process.assert_called_once_with(123, "war3.exe")
    assert "fixture identity warning" in report["notes"]
    rows = report["resources"]
    assert rows is not None and len(rows) == 1
    row = rows[0]
    assert {key: row[key] for key in ("addr", "gold", "lumber", "food")} == {
        "addr": "0x1000",
        "gold": 169,
        "lumber": 808,
        "food": 4,
    }
    assert row["gold_exact"] == 169.0
    assert row["lumber_exact"] == 808.0
    fields = {field["key"]: field for field in row["evidence"]}
    assert fields["gold"]["value"] == 169.0
    assert fields["lumber"]["value"] == 808.0
    # This synthetic legacy row supplies no real field addresses. Preserve its
    # values without manufacturing confirmed address evidence for the extension.
    assert fields["gold"]["state"] == "unknown"
    assert fields["gold"]["address"] is None
    assert report["strategy_used"] == "handle"
    live.k32.CloseHandle.assert_called_once_with(123)


@pytest.mark.parametrize("verified", (True, False))
def test_combined_resource_api_honors_all_units_profile_and_snapshot_requests(
    resource_api, tmp_path, verified
):
    live, hc, regions = resource_api
    hc.verify_profile.return_value = (
        verified,
        [] if verified else ["fixture mismatch"],
        [],
    )
    profile_path = str(tmp_path / "input-profile.json")
    export_path = tmp_path / "export-profile.json"
    snapshot_path = str(tmp_path / "saved-snapshot")

    report = live.read_live(
        "unused",
        strategy="handle",
        resources=(169, 808),
        all_units=True,
        profile_json=profile_path,
        export_profile=str(export_path),
        save_snapshot_dir=snapshot_path,
        pid=42,
        verbose=False,
    )

    live.snapshot.assert_called_once()
    live.save_snapshot.assert_called_once_with(regions, snapshot_path)
    live.load_profile_override.assert_called_once_with(profile_path)
    hc.verify_profile.assert_called_once()
    live.verify_opened_process.assert_called_once_with(123, "war3.exe")
    assert "fixture identity warning" in report["notes"]
    assert all(isinstance(row, dict) for row in report["resources"])
    if verified:
        assert report["all_units"][0]["code"] == "H004"
        assert export_path.is_file()
    else:
        assert report["all_units"] is None
        assert not export_path.exists()
        assert any(
            "档案自校验失败" in note and "fixture mismatch" in note
            for note in report["notes"]
        )
        hc.derive_offsets.assert_called_once()
    live.k32.CloseHandle.assert_called_once_with(123)

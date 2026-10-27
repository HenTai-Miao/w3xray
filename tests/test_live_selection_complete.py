"""Synthetic selection traversal and report integration; never open a real game."""

from __future__ import annotations

import ctypes
import json
import struct
import sys
from dataclasses import asdict, replace
from types import SimpleNamespace
from typing import Any

import pytest

from gametool import live_handle_chain as hc
from tests.test_live_handle_chain import DLL_BASE, _build_memory


def _selection_memory(handles: list[tuple[int, int]], *, cycle: bool = False):
    regions, hero, other, offsets = _build_memory()
    data = dict(regions)
    first = 0x1B700000
    manager_address = 0x1B600000
    header = manager_address + 0x1F0
    terminal = (~header) & 0xFFFFFFFF
    encoded_units = []
    for index, (lo, hi) in enumerate(handles):
        handle_index = lo & 0x7FFFFFFF
        unit = {7: hero, 8: other, 9: 0x20002000}.get(
            handle_index, 0x21000000 + (handle_index - 7) * 0x1000
        )
        encoded_units.append(unit)
        if unit in data:
            body = bytearray(data[unit])
            struct.pack_into("<II", body, offsets.entry_pair_off, lo, hi)
            data[unit] = bytes(body)
        following = (
            first + (index + 1) * 0x100 if index + 1 < len(handles) else terminal
        )
        if cycle and index + 1 == len(handles):
            following = first
        previous = first + (index - 1) * 0x100 if index else header
        data[first + index * 0x100] = struct.pack("<III", previous, following, unit)
    manager = bytearray(data[manager_address])
    struct.pack_into(
        "<I", manager, offsets.sel_entry_off, encoded_units[0] if encoded_units else 0
    )
    struct.pack_into(
        "<III",
        manager,
        0x1F0,
        first + (len(handles) - 1) * 0x100 if handles else header,
        first if handles else terminal,
        len(handles),
    )
    data[manager_address] = bytes(manager)
    reader = hc.MemoryReader(list(data.items()))
    return (
        data,
        reader,
        hc.HandleSystem(reader, DLL_BASE, offsets),
        hero,
        other,
        offsets,
    )


def test_selection_keeps_all_distinct_instances_and_encoded_duplicate_evidence():
    handles = [(0x80000007, 0x5001), (0x80000008, 0x5002)] * 150
    _data, reader, system, hero, other, offsets = _selection_memory(handles)
    result = hc.selected_units(reader, system, offsets, DLL_BASE)

    assert [unit.unit_addr for unit in result.units] == [hero, other]
    assert len(result.entries) == 300
    assert not result.complete
    duplicate_entries = [
        entry
        for entry in result.entries
        if any("重复 UNIT" in issue for issue in entry.diagnostics)
    ]
    assert len(duplicate_entries) == 298
    assert duplicate_entries[0].entry_address == 0x1B700200
    assert "节点 1 @0x1B700000" in " ".join(duplicate_entries[0].diagnostics)
    assert duplicate_entries[-1].raw_node_bytes is not None
    assert result.entries[-1].ordinal == 299
    assert result.entries[0].resolution["generation"] == 0x5001
    assert result.context["local_player"] == 1
    assert hc.selected_unit(reader, system, offsets, DLL_BASE) == result.units[0]


def test_selection_has_no_empirical_distinct_unit_count_ceiling():
    count = 300
    handles = [(0x80000000 | (7 + index), 0x6000 + index) for index in range(count)]
    data, _reader, _system, _hero, _other, offsets = _selection_memory(handles)
    table = bytearray(data[0x40010000])
    table.extend(bytes((count + 7) * 8 - len(table)))
    manager_body = bytearray(data[0x1B3A0000])
    struct.pack_into("<I", manager_body, offsets.hm_tableB_bound_off, len(table) // 8)
    data[0x1B3A0000] = bytes(manager_body)
    for index, (_lo, generation) in enumerate(handles):
        unit_address = 0x21000000 + index * 0x1000
        wrapper_address = 0x31000000 + index * 0x100
        unit = bytearray(0x200)
        struct.pack_into("<II", unit, offsets.entry_pair_off, _lo, generation)
        code = f"h{index:03d}".encode("ascii")
        struct.pack_into("<I", unit, offsets.unit_type_off, int.from_bytes(code, "big"))
        data[unit_address] = bytes(unit)
        wrapper = bytearray(0x60)
        struct.pack_into("<I", wrapper, 0xC, 0x2B61676C)
        struct.pack_into("<I", wrapper, offsets.wrapper_gen_off, generation)
        struct.pack_into("<I", wrapper, offsets.wrapper_obj_off, unit_address)
        data[wrapper_address] = bytes(wrapper)
        struct.pack_into("<II", table, (7 + index) * 8, 0xFFFFFFFE, wrapper_address)
        node = bytearray(data[0x1B700000 + index * 0x100])
        struct.pack_into("<I", node, 8, unit_address)
        data[0x1B700000 + index * 0x100] = bytes(node)
    data[0x40010000] = bytes(table)
    manager = bytearray(data[0x1B600000])
    struct.pack_into("<I", manager, offsets.sel_entry_off, 0x21000000)
    data[0x1B600000] = bytes(manager)
    reader = hc.MemoryReader(list(data.items()))
    result = hc.selected_units(
        reader, hc.HandleSystem(reader, DLL_BASE, offsets), offsets, DLL_BASE
    )
    assert result.complete and not result.diagnostics
    assert [unit.code for unit in result.units] == [
        f"h{index:03d}" for index in range(count)
    ]
    assert len(result.entries) == count


def test_bad_handle_does_not_erase_later_valid_nodes_and_cycle_is_diagnostic():
    _data, reader, system, _hero, other, offsets = _selection_memory(
        [(0x80000007, 0x9999), (0x80000008, 0x5002)], cycle=True
    )
    result = hc.selected_units(reader, system, offsets, DLL_BASE)

    assert [unit.unit_addr for unit in result.units] == [other]
    assert not result.complete
    assert any("世代" in issue for issue in result.diagnostics)
    assert any("循环" in issue for issue in result.diagnostics)
    assert len(result.entries) == 2


def test_confirmed_empty_selection_differs_from_unreadable_head():
    data, reader, system, _hero, _other, offsets = _selection_memory([])
    empty = hc.selected_units(reader, system, offsets, DLL_BASE)
    assert empty.complete and empty.units == () and empty.diagnostics == ()

    del data[0x1B600000]
    unreadable = hc.MemoryReader(list(data.items()))
    unknown = hc.selected_units(unreadable, system, offsets, DLL_BASE)
    assert not unknown.complete and unknown.units == ()
    assert "不可读" in " ".join(unknown.diagnostics)


def test_unreadable_node_pair_retains_readable_next_node():
    data, _reader, _system, _hero, other, offsets = _selection_memory(
        [(0x80000007, 0x5001), (0x80000008, 0x5002)]
    )
    data[0x1B700000] = struct.pack("<II", 0x1B6001F0, 0x1B700100)
    reader = hc.MemoryReader(list(data.items()))
    result = hc.selected_units(
        reader, hc.HandleSystem(reader, DLL_BASE, offsets), offsets, DLL_BASE
    )
    assert [unit.unit_addr for unit in result.units] == [other]
    assert not result.complete
    assert result.entries[0].handle_lo is None
    assert "单位指针不可读" in " ".join(result.diagnostics)


def test_unreadable_wrapper_alive_is_not_a_zero_alive_flag():
    data, _reader, _system, _hero, _other, offsets = _selection_memory(
        [(0x80000007, 0x5001)]
    )
    wrapper = data.pop(0x30000000)
    data[0x30000000] = wrapper[:0x20]
    data[0x30000024] = wrapper[0x24:]
    reader = hc.MemoryReader(list(data.items()))
    system = hc.HandleSystem(reader, DLL_BASE, offsets)
    assert system.resolve(0x80000007, 0x5001) is None
    result = hc.selected_units(reader, system, offsets, DLL_BASE)
    assert not result.complete and not result.units
    assert "alive 不可读" in " ".join(result.diagnostics)


def test_inventory_partial_bytes_are_not_a_confirmed_empty_inventory():
    data, _reader, _system, hero, _other, offsets = _selection_memory(
        [(0x80000007, 0x5001)]
    )
    data[0x10010000] = data[0x10010000][:0x70]
    reader = hc.MemoryReader(list(data.items()))
    result = hc.read_inventory(
        reader, hc.HandleSystem(reader, DLL_BASE, offsets), offsets, hero
    )
    assert result.code == "H004" and result.items == ()
    assert not result.complete and len(result.diagnostics) == 6


@pytest.fixture
def fake_live(monkeypatch: pytest.MonkeyPatch):
    if sys.platform != "win32":
        pytest.skip("Windows module API is mocked on Windows")
    from gametool import hero_chain, live_inventory as live

    data, _reader, _system, _hero, _other, offsets = _selection_memory(
        [(0x80000007, 0x5001), (0x80000008, 0x5002)]
    )
    for address, x, y, owner in (
        (0x20000000, 0.0, 2.25, 1),
        (0x20001000, -4.5, 0.0, 2),
    ):
        body = bytearray(data[address])
        body.extend(bytes(0x28C - len(body)))
        body[hc.UNIT_OWNER_OFF] = owner
        struct.pack_into("<ff", body, hc.UNIT_POS_X_OFF, x, y)
        data[address] = bytes(body)
    profile = replace(hc.resolve_profile("1.27.0.52240"), checks=(), fingerprint=None)
    monkeypatch.setattr(hc, "resolve_profile", lambda *_args: profile)
    monkeypatch.setattr(live, "mem_setup", lambda: None)
    monkeypatch.setattr(live, "find_war3_pids", lambda: [42])
    monkeypatch.setattr(live, "open_process", lambda _pid: 123)
    monkeypatch.setattr(
        live, "_process_identity", lambda _handle: "C:\\fixture\\war3.exe"
    )
    monkeypatch.setattr(
        live, "_process_creation_time", lambda _handle: 133700000000000000
    )
    monkeypatch.setattr(live, "_integrity_rid", lambda _handle: None)
    monkeypatch.setattr(live, "snapshot", lambda *_args: (list(data.items()), 0))
    monkeypatch.setattr(live, "k32", SimpleNamespace(CloseHandle=lambda _handle: None))
    monkeypatch.setattr(
        live,
        "detect_version",
        lambda _handle: {
            "version": "1.27.0.52240",
            "arch": "x86",
            "engine": "classic",
            "game_dll": {"base": DLL_BASE},
        },
    )
    monkeypatch.setattr(
        live,
        "load_names",
        lambda _pack, kind="物品": {
            b"H004": "英雄",
            b"N02A": "同伴",
            b"I021": "装备",
            b"I01F": "药品",
            b"I07F": "材料",
        },
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "a confirmed selection must not use heuristic/icon inventory"
        )

    monkeypatch.setattr(hero_chain, "read_inventory", forbidden)
    monkeypatch.setattr(live, "_read_icon_slots", forbidden)
    return live, data, offsets


def test_live_report_keeps_every_selection_and_actual_opened_process_metadata(
    fake_live,
):
    live, _data, _offsets = fake_live
    report = live.read_live("fixture", verbose=False)
    selected = report["selected_units"]
    assert [unit["code"] for unit in selected] == ["H004", "N02A"]
    assert report["selected_unit"] is selected[0]
    assert report["selection_complete"] and not report["selection_diagnostics"]
    assert selected[0]["owner"] == 1 and selected[0]["x"] == 0.0
    assert selected[1]["owner"] == 2 and selected[1]["y"] == 0.0
    assert selected[0]["items_complete"]
    assert selected[0]["evidence"][0]["state"] == "confirmed"
    assert selected[0]["items"][0]["evidence"]
    assert selected[0]["selection_evidence"][0]["entry_address"] == 0x1B700000
    assert report["captured_at"].endswith("+00:00")
    assert report["capture_finished_at"] >= report["captured_at"]
    identity = report["process_identity"]
    assert identity["pid"] == 42 and identity["state"] == "confirmed"
    assert (
        identity["creation_time"]
        == identity["verified_creation_time"]
        == 133700000000000000
    )
    assert "map_epoch" not in identity


def test_live_empty_selection_never_falls_back_to_another_units_inventory(fake_live):
    live, data, offsets = fake_live
    manager = bytearray(data[0x1B600000])
    struct.pack_into("<I", manager, offsets.sel_entry_off, 0)
    header = 0x1B6001F0
    struct.pack_into("<III", manager, 0x1F0, header, (~header) & 0xFFFFFFFF, 0)
    data[0x1B600000] = bytes(manager)
    report = live.read_live("fixture", verbose=False)
    assert report["strategy_used"] == "handle"
    assert report["selected_units"] == [] and report["selected_unit"] is None
    assert report["selection_complete"] and report["slots"] == []
    assert report["units"]  # Another unit really has items in this snapshot.


def test_process_birth_mismatch_remains_visible_before_handle_close(
    fake_live, monkeypatch
):
    live, _data, _offsets = fake_live
    values = iter((100, 200))
    monkeypatch.setattr(live, "_process_creation_time", lambda _handle: next(values))
    report = live.read_live("fixture", verbose=False)
    assert report["process_identity"]["state"] == "conflict"
    assert any("创建时间已变" in note for note in report["notes"])


def test_get_process_times_preserves_exact_filetime(fake_live, monkeypatch):
    live, _data, _offsets = fake_live
    monkeypatch.undo()
    # Restore only the pure function, then give it a wholly synthetic Win32 API.
    from gametool.live_inventory import _process_creation_time

    def times(_handle, creation, _exit, _kernel, _user):
        creation._obj.dwHighDateTime = 0x12345678
        creation._obj.dwLowDateTime = 0x90ABCDEF
        return True

    monkeypatch.setattr(live, "k32", SimpleNamespace(GetProcessTimes=times))
    assert _process_creation_time(ctypes.c_void_p(123)) == 0x1234567890ABCDEF


def test_cli_report_argument_survives_forwarding_and_elevation_hint(
    tmp_path, monkeypatch
):
    from gametool import live_cli as cli

    path = str(tmp_path / "capture report.json")
    options = cli.parse_live_cli_options(["--pack", str(tmp_path), "--report", path])
    assert options.report == path
    assert cli._request_arguments(options)[-2:] == ["--report", path]
    assert "--report" in cli._elevated_hint_command(options)
    calls: list[list[str]] = []
    module = SimpleNamespace(main=lambda args: calls.append(args) or 0)
    monkeypatch.setitem(sys.modules, "gametool.live_inventory", module)
    assert cli.run_live_cli(options) == 0
    assert calls[0][-2:] == ["--report", path]


def test_report_preflight_rejects_existing_asset_before_probe(
    fake_live, tmp_path, monkeypatch
):
    live, _data, _offsets = fake_live
    path = tmp_path / "existing.json"
    path.write_bytes(b"keep me exactly")
    monkeypatch.setattr(
        live, "read_live", lambda *_args, **_kwargs: pytest.fail("probe started")
    )
    with pytest.raises(SystemExit) as error:
        live.main(["--pack", "fixture", "--report", str(path)])
    assert error.value.code == 2
    assert path.read_bytes() == b"keep me exactly"


def test_cli_renders_all_selected_instances_and_empty_selection(
    fake_live, monkeypatch, capsys
):
    live, data, offsets = fake_live
    report = live.read_live("fixture", verbose=False)
    monkeypatch.setattr(live, "read_live", lambda *_args, **_kwargs: report)
    assert live.main(["--pack", "fixture"]) == 0
    output = capsys.readouterr().out
    assert "当前选中 1:" in output and "当前选中 2:" in output
    assert "near 0 2.25" in output and "near -4.5 0" in output
    report["selected_units"] = []
    report["selected_unit"] = None
    report["slots"] = []
    assert live.main(["--pack", "fixture"]) == 0
    assert "当前没有选中单位" in capsys.readouterr().out


def test_missing_coordinates_remain_unknown_instead_of_an_invented_origin(fake_live):
    live, data, _offsets = fake_live
    data[0x20000000] = data[0x20000000][:0x200]
    report = live.read_live("fixture", verbose=False)
    selected = report["selected_units"][0]
    assert selected["x"] is None and selected["y"] is None
    assert all(
        item["value"] is None and item["state"] == "unavailable"
        for item in selected["evidence"]
        if item["key"] in {"x", "y"}
    )


def test_full_profile_import_roundtrip_keeps_declared_field_provenance():
    data: dict[str, Any] = {
        "schema_version": 1,
        "game_version": "1.27.0.52240",
        "id": "fixture-profile",
        "status": "unverified",
        "pointer_size": 4,
        "field_layouts": [
            {
                "scope": "unit",
                "key": "fixture_scalar",
                "type": "u32",
                "offset": 12,
                "source": "synthetic declared layout",
                "evidence": "declared-layout-only",
            }
        ],
    }
    profile = hc.profile_from_dict(data)
    result = hc.profile_to_dict(profile)
    assert result["id"] == "fixture-profile" and result["status"] == "unverified"
    assert (
        result["pointer_size"] == 4 and result["field_layouts"] == data["field_layouts"]
    )
    assert hc.profile_from_dict(result).field_layouts == profile.field_layouts


def test_cli_report_saves_complete_capture_and_reopens_without_a_game(
    fake_live, tmp_path, monkeypatch, capsys
):
    from gametool.live_report import read_live_report

    live, _data, _offsets = fake_live
    report = live.read_live("fixture", verbose=False)
    monkeypatch.setattr(live, "read_live", lambda *_args, **_kwargs: report)
    path = tmp_path / "capture.json"
    assert live.main(["--pack", "fixture", "--report", str(path)]) == 0
    loaded = read_live_report(path)
    assert json.loads(loaded.to_json()) == report
    assert len(loaded["selected_units"]) == 2
    assert loaded["process_identity"]["creation_time"] == 133700000000000000
    assert "实时报告已保存" in capsys.readouterr().out


def test_cli_report_saves_a_useful_no_process_diagnostic(
    fake_live, tmp_path, monkeypatch
):
    from gametool.live_report import read_live_report

    live, _data, _offsets = fake_live
    monkeypatch.setattr(live, "find_war3_pids", lambda: [])
    report = live.read_live("fixture", verbose=False)
    monkeypatch.setattr(live, "read_live", lambda *_args, **_kwargs: report)
    path = tmp_path / "diagnostic.json"
    assert live.main(["--pack", "fixture", "--report", str(path)]) == 2
    loaded = read_live_report(path)
    assert loaded["pid"] is None and loaded["process_identity"] is None
    assert loaded["selection_complete"] is False
    assert "war3 未运行" in loaded["notes"]


def test_cli_report_write_error_keeps_the_live_json_and_returns_failure(
    fake_live, tmp_path, monkeypatch, capsys
):
    from gametool import live_report

    live, _data, _offsets = fake_live
    report = live.read_live("fixture", verbose=False)
    monkeypatch.setattr(live, "read_live", lambda *_args, **_kwargs: report)

    def failed_write(*_args):
        raise live_report.LiveReportError("synthetic destination race")

    monkeypatch.setattr(live_report, "write_live_report", failed_write)
    assert (
        live.main(["--pack", "fixture", "--report", str(tmp_path / "race.json")]) == 2
    )
    output = capsys.readouterr()
    assert '"selected_units"' in output.out and '"H004"' in output.out
    assert "synthetic destination race" in output.err
    assert not (tmp_path / "race.json").exists()


def test_invalid_top_level_report_destination_stops_before_map_and_pack_access(
    tmp_path, monkeypatch, capsys
):
    from gametool import live_cli

    report = tmp_path / "existing.json"
    report.write_bytes(b"original asset")
    monkeypatch.setattr(
        live_cli, "_resolve_auto_map", lambda *_args: pytest.fail("map probe started")
    )
    monkeypatch.setattr(
        live_cli,
        "_ensure_pack_dir",
        lambda *_args: pytest.fail("pack preparation started"),
    )
    options = live_cli.LiveCliOptions(report=str(report))
    assert live_cli.run_live_cli(options) == 2
    assert report.read_bytes() == b"original asset"
    assert "already exists" in capsys.readouterr().err


def test_unknown_inventory_does_not_exit_as_a_confirmed_empty_success(
    fake_live, monkeypatch
):
    live, data, _offsets = fake_live
    data[0x10010000] = data[0x10010000][:0x70]
    report = live.read_live("fixture", verbose=False)
    assert report["selected_unit"]["items_complete"] is False
    report["selected_units"] = [report["selected_unit"]]
    monkeypatch.setattr(live, "read_live", lambda *_args, **_kwargs: report)
    assert live.main(["--pack", "fixture"]) == 2


def test_locate_hint_uses_every_selected_unit_and_its_items(fake_live):
    live, _data, _offsets = fake_live
    report = live.read_live("fixture", verbose=False)
    assert live.campaign_locate_hint(report) == "H004;I021;I01F;N02A;I07F"


def test_invalid_owner_stays_raw_evidence_without_a_confirmed_player(fake_live):
    live, data, _offsets = fake_live
    body = bytearray(data[0x20000000])
    body[hc.UNIT_OWNER_OFF] = 255
    data[0x20000000] = bytes(body)
    report = live.read_live("fixture", verbose=False)
    selected = report["selected_units"][0]
    assert selected["owner"] is None
    owner = next(item for item in selected["evidence"] if item["key"] == "owner")
    assert owner["value"] == 255 and owner["state"] == "invalid"


@pytest.mark.parametrize(
    "unit_code,item_code", [(b"1234", b"!@#$"), (b"h(01", b"\xe9- A")]
)
def test_native_selection_and_inventory_pairs_preserve_full_latin1_codes(
    fake_live, unit_code, item_code
):
    live, data, offsets = fake_live
    for address, code in ((0x20000000, unit_code), (0x10000000, item_code)):
        body = bytearray(data[address])
        struct.pack_into("<I", body, offsets.unit_type_off, int.from_bytes(code, "big"))
        data[address] = bytes(body)
    report = live.read_live("fixture", verbose=False)
    selected = report["selected_units"][0]
    assert selected["code"] == unit_code.decode("latin-1")
    assert selected["items"][0]["code"] == item_code.decode("latin-1")
    assert selected["items"][0]["handle_pair"] == {
        "address": 0x10010070,
        "lo": 0x11,
        "hi": 0xAA,
    }
    assert (
        selected["inventory_evidence"][0]["item_type_raw_bytes"]
        == item_code[::-1].hex()
    )
    assert selected["items_complete"] and report["selection_complete"]


def test_all_item_inventory_views_preserve_punctuation_without_a_second_filter(
    fake_live,
):
    live, data, offsets = fake_live
    body = bytearray(data[0x10000000])
    struct.pack_into("<I", body, offsets.item_type_off, int.from_bytes(b";123", "big"))
    data[0x10000000] = bytes(body)
    report = live.read_live("fixture", verbose=False)
    unit = next(item for item in report["units"] if item["code"] == "H004")
    assert unit["items"][0]["code"] == ";123"


def test_null_native_type_retains_pointer_diagnostics_without_a_false_unit(fake_live):
    live, data, offsets = fake_live
    body = bytearray(data[0x20000000])
    struct.pack_into("<I", body, offsets.unit_type_off, 0)
    data[0x20000000] = bytes(body)
    report = live.read_live("fixture", verbose=False)
    assert [unit["code"] for unit in report["selected_units"]] == ["N02A"]
    assert not report["selection_complete"]
    assert report["selection_evidence"]["entries"][0]["unit_address"] == 0x20000000
    assert any(
        "空值" in issue and "20000030" in issue
        for issue in report["selection_diagnostics"]
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_axis_cannot_become_a_coordinate_handoff(fake_live, bad):
    live, data, _offsets = fake_live
    body = bytearray(data[0x20000000])
    struct.pack_into("<f", body, hc.UNIT_POS_X_OFF, bad)
    data[0x20000000] = bytes(body)
    report = live.read_live("fixture", verbose=False)
    selected = report["selected_units"][0]
    assert selected["x"] is None and selected["y"] == 2.25
    evidence = next(item for item in selected["evidence"] if item["key"] == "x")
    assert evidence["state"] == "invalid" and evidence["raw_bytes"]


def test_readable_imported_127_offsets_do_not_promote_external_fields_or_coordinates(
    fake_live, tmp_path, monkeypatch, capsys
):
    live, data, offsets = fake_live
    profile = hc.profile_to_dict(hc.resolve_profile("1.27.0.52240"))
    profile["id"] = "synthetic-untrusted-import"
    profile["source"] = "synthetic arbitrary but readable offsets"
    profile["handle_chain"]["unit_type_off"] = 0x34
    profile["handle_chain"]["item_type_off"] = 0x34
    for address, code in (
        (0x20000000, b"u123"),
        (0x20001000, b"u124"),
        (0x10000000, b"i123"),
        (0x10000100, b"i124"),
        (0x10000200, b"i125"),
    ):
        body = bytearray(data[address])
        body.extend(bytes(max(0, 0x38 - len(body))))
        struct.pack_into("<I", body, 0x34, int.from_bytes(code, "big"))
        data[address] = bytes(body)
    path = tmp_path / "declared-profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    report = live.read_live(
        "fixture", profile_json=str(path), players=True, all_units=True, verbose=False
    )
    selected = report["selected_units"][0]
    assert selected["code"] == "u123" and selected["items"][0]["code"] == "i123"
    assert selected["x"] is None and selected["y"] is None and selected["owner"] is None
    assert selected["items_complete"] is False and report["selection_complete"] is False
    assert all(item["state"] == "declared-layout-only" for item in selected["evidence"])
    assert all(
        item["state"] == "declared-layout-only"
        for item in selected["items"][0]["evidence"]
    )
    assert all(
        "synthetic-untrusted-import" in item["profile"] for item in selected["evidence"]
    )
    assert all(
        "synthetic arbitrary but readable offsets" in item["source"]
        for item in selected["evidence"]
    )
    assert report["offset_profile"]["data"]["handle_chain"]["unit_type_off"] == 0x34
    assert report["offset_profile"]["origin"] == "external"
    assert report["selection_evidence"]["state"] == "declared-layout-only"
    assert report["owner_counts"] is None
    for unit in [*report["all_units"], *report["owned_units"]]:
        assert unit["owner"] is None and unit["x"] is None and unit["y"] is None
    monkeypatch.setattr(live, "read_live", lambda *_args, **_kwargs: report)
    assert live.main(["--pack", "fixture", "--all-units", "--players"]) == 0
    assert "坐标反查模板" not in capsys.readouterr().out


def test_combined_builtin_and_declared_coordinate_conflict_blocks_handoff(
    fake_live, monkeypatch
):
    from gametool.live_profile_validation import parse_field_layouts

    live, data, _offsets = fake_live
    body = bytearray(data[0x20000000])
    body.extend(bytes(4))
    struct.pack_into("<f", body, 0x28C, 9.75)
    data[0x20000000] = bytes(body)
    profile = replace(
        hc.resolve_profile("1.27.0.52240"),
        field_layouts=parse_field_layouts(
            [
                {
                    "scope": "unit",
                    "key": "x",
                    "type": "f32",
                    "offset": 0x28C,
                    "source": "conflicting declared x",
                    "evidence": "declared-layout-only",
                }
            ]
        ),
    )
    monkeypatch.setattr(hc, "resolve_profile", lambda *_args: profile)
    report = live.read_live("fixture", verbose=False)
    selected = report["selected_units"][0]
    values = [item for item in selected["evidence"] if item["key"] == "x"]
    assert [item["value"] for item in values] == [0.0, 9.75]
    assert all(item["state"] == "conflict" for item in values)
    assert selected["x"] is None and selected["y"] == 2.25
    assert values[0]["raw_bytes"] and values[1]["raw_bytes"]


def test_all_declared_scopes_are_applied_or_have_typed_unavailable_roots(
    fake_live, monkeypatch
):
    from gametool.live_profile_validation import parse_field_layouts

    live, _data, offsets = fake_live
    declarations = [
        {
            "scope": scope,
            "key": f"{scope}_value",
            "type": "u32",
            "offset": offset,
            "source": f"synthetic {scope} recipe",
            "evidence": "declared-layout-only",
        }
        for scope, offset in (
            ("module", offsets.handle_mgr_global_rva),
            ("player", 0),
            ("resource", 0),
        )
    ]
    profile = replace(
        hc.resolve_profile("1.27.0.52240"),
        field_layouts=parse_field_layouts(declarations),
    )
    monkeypatch.setattr(hc, "resolve_profile", lambda *_args: profile)
    report = live.read_live("fixture", verbose=False)
    fields = {item["scope"]: item for item in report["evidence"]}
    assert fields["module"]["value"] == 0x1B3A0000
    assert fields["module"]["address"] == DLL_BASE + offsets.handle_mgr_global_rva
    assert fields["module"]["state"] == "declared-layout-only"
    assert fields["player"]["value"] == 0 and fields["player"]["address"] == 0x1B500000
    assert fields["player"]["state"] == "declared-layout-only"
    assert (
        fields["resource"]["state"] == "unavailable"
        and fields["resource"]["value"] is None
    )
    assert fields["resource"]["address"] is None and fields["resource"]["diagnostics"]
    assert fields["resource"]["layout"] == declarations[2]


def test_failed_builtin_verification_cannot_promote_a_derived_candidate(
    fake_live, monkeypatch
):
    live, data, offsets = fake_live
    profile = replace(
        hc.resolve_profile("1.27.0.52240"), checks=(hc.ProfileCheck(0, b"\x90"),)
    )
    monkeypatch.setattr(hc, "resolve_profile", lambda *_args: profile)
    monkeypatch.setattr(
        hc, "verify_profile", lambda *_args: (False, ["synthetic mismatch"], [])
    )
    candidate = replace(
        offsets, unit_type_off=0x34, source="synthetic derived fallback"
    )
    monkeypatch.setattr(hc, "derive_offsets", lambda *_args, **_kwargs: candidate)
    for address, code in ((0x20000000, b"u123"), (0x20001000, b"u124")):
        body = bytearray(data[address])
        struct.pack_into("<I", body, 0x34, int.from_bytes(code, "big"))
        data[address] = bytes(body)
    report = live.read_live("fixture", verbose=False)
    selected = report["selected_units"][0]
    assert selected["code"] == "u123"
    assert all(
        field["state"] == "declared-layout-only" for field in selected["evidence"]
    )
    assert selected["x"] is None and selected["y"] is None and selected["owner"] is None
    assert report["selection_complete"] is False
    assert report["offset_profile"]["state"] == "declared-layout-only"
    assert any("synthetic mismatch" in note for note in report["notes"])


def _resource_blob(gold: float, lumber: float, food: float, *, auto: bool = False):
    body = bytearray(0x300)
    struct.pack_into("<f", body, 0x40, gold)
    struct.pack_into("<f", body, 0x44 if auto else 0x58, lumber)
    struct.pack_into("<f", body, 0x48 if auto else 0x5C, food)
    return bytes(body)


def _pending_resource_profile(monkeypatch, live):
    pending = hc.LiveBuildProfile(
        version="3.0.0.24268",
        engine="reforged",
        arch="x64",
        game_struct_rva=None,
        unit_list_rva=None,
        handle_chain=None,
        tier="reforged-pending",
        source="synthetic unsupported build",
    )
    monkeypatch.setattr(hc, "resolve_profile", lambda *_args: pending)
    monkeypatch.setattr(
        live,
        "detect_version",
        lambda _handle: {
            "version": pending.version,
            "engine": pending.engine,
            "arch": pending.arch,
            "game_dll": {"base": DLL_BASE},
        },
    )


@pytest.mark.parametrize("fallback", [False, True])
def test_calibrated_resource_report_retains_exact_values_addresses_and_source(
    fake_live, monkeypatch, fallback
):
    live, data, _offsets = fake_live
    if fallback:
        _pending_resource_profile(monkeypatch, live)
    monkeypatch.setattr(hc, "_resource_anchors", None)
    data[0x60000000] = _resource_blob(7774.63, 113.28, 3.75)
    expected_gold = struct.unpack("<f", struct.pack("<f", 7774.63))[0]
    expected_lumber = struct.unpack("<f", struct.pack("<f", 113.28))[0]
    report = live.read_live(
        "fixture", strategy="handle", resources=(7775, 113), verbose=False
    )
    row = report["resources"][0]
    assert row["gold"] == 7775 and row["lumber"] == 113 and row["food"] == 4
    assert row["gold_exact"] == expected_gold and row["lumber_exact"] == expected_lumber
    assert row["food_exact"] == 3.75
    fields = {field["key"]: field for field in row["evidence"]}
    assert (
        fields["gold"]["value"] == expected_gold
        and fields["gold"]["value_type"] == "f32"
    )
    assert (
        fields["lumber"]["value"] == expected_lumber
        and fields["lumber"]["address"] == 0x60000058
    )
    assert fields["gold"]["address"] == 0x60000040
    assert fields["gold"]["raw_bytes"] == struct.pack("<f", 7774.63).hex()
    assert (
        "HUD" in fields["gold"]["source"]
        and fields["gold"]["state"] == "declared-layout-only"
    )
    assert report["resources_complete"] is False


@pytest.mark.parametrize("fallback", [False, True])
def test_auto_resource_evidence_uses_the_actual_final_sample_not_initial_snapshot(
    fake_live, monkeypatch, fallback
):
    import time

    live, data, _offsets = fake_live
    if fallback:
        _pending_resource_profile(monkeypatch, live)
    snapshots = iter(
        [
            [*data.items(), (0x60000000, _resource_blob(gold, 13.25, 2.75, auto=True))]
            for gold in (1000.25, 1001.5, 1002.75)
        ]
    )
    monkeypatch.setattr(live, "snapshot", lambda *_args: (next(snapshots), 0))
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    report = live.read_live(
        "fixture", strategy="handle", resources="auto", verbose=False
    )
    row = report["resources"][0]
    assert row["gold_exact"] == 1002.75 and row["lumber_exact"] == 13.25
    assert row["food_exact"] == 2.75
    fields = {field["key"]: field for field in row["evidence"]}
    assert fields["gold"]["value"] == 1002.75
    assert fields["gold"]["raw_bytes"] == struct.pack("<f", 1002.75).hex()
    assert fields["lumber"]["address"] == 0x60000044
    assert "多快照" in fields["gold"]["source"]


def test_fixed_resource_chain_keeps_zero_and_full_scaled_integer_evidence(
    fake_live, monkeypatch
):
    live, data, _offsets = fake_live
    monkeypatch.setattr(hc, "_resource_anchors", None)
    data[0x60000000] = _resource_blob(7774.63, 113.28, 3.75)
    table = bytearray(data[0x40000000])
    struct.pack_into("<I", table, 0xC, 0x61000098)
    data[0x40000000] = bytes(table)
    resource_memory = bytearray(0x10000)
    struct.pack_into("<i", resource_memory, 0x190, 0)
    struct.pack_into("<i", resource_memory, 0x190 + 0x80, 8005)
    struct.pack_into("<i", resource_memory, 0x190 + 0x200, 0)
    struct.pack_into("<i", resource_memory, 0x190 + 0x180, 10)
    data[0x61000000] = bytes(resource_memory)
    report = live.read_live(
        "fixture", strategy="handle", resources=(7775, 113), verbose=False
    )
    row = report["player_resources"][0]
    assert row["gold_exact"] == 0 and row["lumber_exact"] == 800.5
    fields = {field["key"]: field for field in row["evidence"]}
    assert fields["gold"]["value"] == 0 and fields["gold"]["state"] == "confirmed"
    assert (
        fields["gold"]["value_type"] == "i32"
        and fields["gold"]["scale_denominator"] == 10
    )
    assert (
        fields["lumber"]["value"] == 8005 and fields["lumber"]["address"] == 0x61000210
    )
    assert fields["lumber"]["raw_bytes"] == struct.pack("<i", 8005).hex()


@pytest.mark.parametrize(
    "gold,lumber,food,cap",
    [
        (2**31 - 1, -(2**31), 2**31 - 1, -1),
        (-17, 40_000_001, -999, 2**31 - 1),
        (0, 0, 0, 0),
    ],
)
def test_authoritative_resources_preserve_full_signed_i32_without_magnitude_ceilings(
    fake_live, gold, lumber, food, cap
):
    live, _data, _offsets = fake_live
    root = 0x61000190
    memory = {
        DLL_BASE + 0xBE40A8: 0x22000000,
        0x2200000C: 0x23000000,
        0x2300000C: 0x61000098,
        root: gold & 0xFFFFFFFF,
        root + 0x80: lumber & 0xFFFFFFFF,
        root + 0x200: food & 0xFFFFFFFF,
        root + 0x180: cap & 0xFFFFFFFF,
    }
    rows = hc.read_player_resources_chain(memory.get, DLL_BASE, "1.27.0.52240")
    assert rows is not None
    assert rows[0].gold == gold / 10 and rows[0].lumber == lumber / 10
    assert rows[0].food == food and rows[0].food_cap == cap
    reader = hc.MemoryReader(
        [(address, struct.pack("<I", value)) for address, value in memory.items()]
    )
    report_row = live._resource_report_entry(
        rows[0],
        reader,
        build="1.27.0.52240",
        profile="synthetic trusted chain",
        pointer_size=4,
        qualification="confirmed",
    )
    fields = {field["key"]: field for field in report_row["evidence"]}
    assert [fields[key]["value"] for key in ("gold", "lumber", "food", "food_cap")] == [
        gold,
        lumber,
        food,
        cap,
    ]
    assert all(field["state"] == "confirmed" for field in fields.values())
    assert (
        fields["gold"]["scale_denominator"]
        == fields["lumber"]["scale_denominator"]
        == 10
    )
    assert fields["gold"]["raw_bytes"] == struct.pack("<i", gold).hex()
    assert report_row["food"] == food and report_row["food_cap"] == cap


def test_neighbor_food_remains_semantically_unknown_even_when_bytes_are_readable(
    fake_live, monkeypatch
):
    live, _data, _offsets = fake_live
    monkeypatch.setattr(hc, "_resource_anchors", None)
    reader = hc.MemoryReader([(0x60000000, _resource_blob(7774.63, 113.28, 3.75))])
    row = hc.find_resource_layout(reader, 7775, 113, use_cache=False)[0]
    result = live._resource_report_entry(
        row,
        reader,
        build="1.27.0.52240",
        profile="synthetic readable candidate",
        pointer_size=4,
        qualification="confirmed",
    )
    food = next(field for field in result["evidence"] if field["key"] == "food")
    assert food["value"] == result["food_exact"] == 3.75
    assert food["state"] == "unknown"
    assert (
        food["address"] == 0x6000005C
        and food["raw_bytes"] == struct.pack("<f", 3.75).hex()
    )
    assert any("启发式" in diagnostic for diagnostic in food["diagnostics"])


@pytest.mark.parametrize(
    "mode", ["unreadable", "sparse_y", "zero", "finite_offmap", "nonfinite"]
)
def test_owned_and_all_unit_coordinates_use_real_field_evidence_not_legacy_origin(
    fake_live, monkeypatch, capsys, mode
):
    from gametool.static_numbers import format_number

    live, data, _offsets = fake_live
    address = 0x20000000
    body = bytearray(data[address])
    if mode == "unreadable":
        body = body[:0x200]
        expected = (None, None)
        states = ("unavailable", "unavailable")
    elif mode == "sparse_y":
        struct.pack_into("<f", body, hc.UNIT_POS_X_OFF, 0.0)
        body = body[: hc.UNIT_POS_Y_OFF]
        expected = (0.0, None)
        states = ("confirmed", "unavailable")
    elif mode == "nonfinite":
        struct.pack_into("<ff", body, hc.UNIT_POS_X_OFF, float("nan"), 2.25)
        expected = (None, 2.25)
        states = ("invalid", "confirmed")
    else:
        values = (0.0, 0.0) if mode == "zero" else (1e30, -1e30)
        raw = struct.pack("<ff", *values)
        body[hc.UNIT_POS_X_OFF : hc.UNIT_POS_X_OFF + 8] = raw
        expected = struct.unpack("<ff", raw)
        states = ("confirmed", "confirmed")
    data[address] = bytes(body)
    if mode in {"unreadable", "sparse_y", "nonfinite"}:
        # The old tuple API intentionally retains its compatibility fallback.
        assert hc.read_unit_pos(hc.MemoryReader(list(data.items())), address) == (
            0.0,
            0.0,
        )
    report = live.read_live("fixture", players=True, all_units=True, verbose=False)
    for collection in ("owned_units", "all_units"):
        row = next(unit for unit in report[collection] if unit["addr"] == address)
        assert (row["x"], row["y"]) == expected
        fields = {field["key"]: field for field in row["evidence"]}
        for key, expected_state, offset in zip(
            ("x", "y"), states, (hc.UNIT_POS_X_OFF, hc.UNIT_POS_Y_OFF), strict=True
        ):
            assert fields[key]["state"] == expected_state
            assert fields[key]["address"] == address + offset
            if expected_state != "confirmed":
                assert fields[key]["diagnostics"]
        assert report[collection + "_complete"] is False
    monkeypatch.setattr(live, "read_live", lambda *_args, **_kwargs: report)
    assert live.main(["--pack", "fixture", "--players", "--all-units"]) == 0
    output = capsys.readouterr().out
    if mode in {"unreadable", "sparse_y", "nonfinite"}:
        assert "P1 英雄 [H004] @" not in output
        assert "坐标反查模板：near 0 0" not in output
    else:
        assert expected[0] is not None and expected[1] is not None
        assert (
            f"P1 英雄 [H004] @ ({format_number(expected[0])}, {format_number(expected[1])})"
            in output
        )


def test_resource_logical_equality_preserves_fresh_cached_and_full_provenance(
    monkeypatch,
):
    monkeypatch.setattr(hc, "_resource_anchors", None)
    monkeypatch.setattr(hc, "_resource_cache_hit", False)
    reader = hc.MemoryReader([(0x60000000, _resource_blob(7774.63, 113.28, 3.75))])
    fresh = hc.find_resource_layout(reader, 7775, 113)[0]
    assert not hc.cached_resource_hit()
    cached = hc.find_resource_layout(reader, 7775, 113)[0]
    assert hc.cached_resource_hit()
    assert fresh.source != cached.source
    assert fresh.gold is not None
    assert fresh == cached
    legacy = hc.PlayerResources(
        fresh.addr, fresh.gold, fresh.lumber, fresh.food, fresh.food_cap
    )
    assert fresh == cached == legacy
    assert hash(fresh) == hash(cached) == hash(legacy)
    changed_provenance = replace(
        fresh,
        gold_address=0x61000000,
        lumber_address=0x61000004,
        food_address=0x61000008,
        food_cap_address=0x6100000C,
        storage_type="i32",
        source="independent alternate source witness",
    )
    assert changed_provenance == fresh
    assert changed_provenance.gold_address == 0x61000000
    metadata = asdict(changed_provenance)
    assert metadata["gold_address"] == 0x61000000
    assert metadata["lumber_address"] == 0x61000004
    assert metadata["food_address"] == 0x61000008
    assert metadata["food_cap_address"] == 0x6100000C
    assert metadata["storage_type"] == "i32"
    assert metadata["source"] == "independent alternate source witness"
    assert replace(fresh, gold=fresh.gold + 1) != fresh


def test_primary_unit_vtable_is_never_read_as_a_selection_successor():
    data, _reader, _system, hero, other, offsets = _selection_memory(
        [(0x80000007, 0x5001), (0x80000008, 0x5002)]
    )
    vtable = DLL_BASE + 0x970764
    data[vtable] = struct.pack(
        "<III", DLL_BASE + 0x272380, DLL_BASE + 0x275D90, DLL_BASE + 0x26FF80
    )

    class TracedReader(hc.MemoryReader):
        def __init__(self, regions):
            super().__init__(regions)
            self.addresses = []

        def read(self, addr: int, size: int) -> bytes | None:
            self.addresses.append((addr, size))
            return super().read(addr, size)

    reader = TracedReader(list(data.items()))
    system = hc.HandleSystem(reader, DLL_BASE, offsets)
    primary = hc.selected_unit(reader, system, offsets, DLL_BASE)
    result = hc.selected_units(reader, system, offsets, DLL_BASE)
    assert primary is not None and primary.unit_addr == hero
    assert result.complete and [unit.unit_addr for unit in result.units] == [
        hero,
        other,
    ]
    assert [entry.entry_address for entry in result.entries] == [0x1B700000, 0x1B700100]
    assert all(
        address not in (hero, other, vtable) for address, _size in reader.addresses
    )
    assert (
        result.primary_evidence is not None
        and result.primary_evidence.next_address is None
    )
    assert result.context["local_count"] == result.context["observed_node_count"] == 2
    assert result.context["terminal_word"] == ((~0x1B6001F0) & 0xFFFFFFFF)


def test_legacy_primary_is_independent_of_encoded_local_selection_order(fake_live):
    live, data, offsets = fake_live
    manager = bytearray(data[0x1B600000])
    struct.pack_into("<I", manager, offsets.sel_entry_off, 0x20001000)
    data[0x1B600000] = bytes(manager)
    report = live.read_live("fixture", verbose=False)
    assert [unit["code"] for unit in report["selected_units"]] == ["H004", "N02A"]
    assert report["selected_unit"] is report["selected_units"][1]
    assert report["selected_unit"]["selection_membership_state"] == "confirmed"
    assert report["slots"] == report["selected_units"][1]["items"]
    assert len(report["slots"]) == 3 and report["selection_complete"]


@pytest.mark.parametrize(
    "damage", ["count", "tail", "previous", "wrong_negative_end", "null_end"]
)
def test_local_selection_count_tail_and_exact_sentinel_are_completeness_boundaries(
    damage,
):
    data, _reader, _system, hero, other, offsets = _selection_memory(
        [(0x80000007, 0x5001), (0x80000008, 0x5002)]
    )
    manager = bytearray(data[0x1B600000])
    last_node = bytearray(data[0x1B700100])
    if damage == "count":
        struct.pack_into("<I", manager, 0x1F8, 0xFFFFFFFF)
    elif damage == "tail":
        struct.pack_into("<I", manager, 0x1F0, 0x1B700000)
    elif damage == "previous":
        struct.pack_into("<I", last_node, 0, 0x1B6001F0)
    else:
        struct.pack_into(
            "<I", last_node, 4, 0xFFFFFFFF if damage == "wrong_negative_end" else 0
        )
    data[0x1B600000] = bytes(manager)
    data[0x1B700100] = bytes(last_node)
    reader = hc.MemoryReader(list(data.items()))
    result = hc.selected_units(
        reader, hc.HandleSystem(reader, DLL_BASE, offsets), offsets, DLL_BASE
    )
    assert [unit.unit_addr for unit in result.units] == [hero, other]
    assert not result.complete and result.diagnostics
    assert len(result.entries) == 2
    if damage == "count":
        assert "4294967295" in " ".join(result.diagnostics)


def test_unproved_offset_recipe_retains_primary_without_borrowing_local_layout():
    _data, reader, system, hero, _other, offsets = _selection_memory(
        [(0x80000007, 0x5001), (0x80000008, 0x5002)]
    )
    imported = replace(offsets, source="independent unproved classic recipe")
    result = hc.selected_units(reader, system, imported, DLL_BASE)
    assert result.primary_unit is not None and result.primary_unit.unit_addr == hero
    assert [unit.unit_addr for unit in result.units] == [hero]
    assert result.layout is None and result.entries == () and not result.complete
    assert "没有独立验证" in " ".join(result.diagnostics)


def test_synced_group_is_not_unioned_into_the_local_ui_selection():
    data, _reader, _system, hero, other, offsets = _selection_memory(
        [(0x80000007, 0x5001)]
    )
    manager = bytearray(data[0x1B600000])
    synced_header = 0x1B600008
    struct.pack_into("<III", manager, 8, 0x1B800000, 0x1B800000, 1)
    data[0x1B600000] = bytes(manager)
    data[0x1B800000] = struct.pack(
        "<III", synced_header, (~synced_header) & 0xFFFFFFFF, other
    )
    reader = hc.MemoryReader(list(data.items()))
    result = hc.selected_units(
        reader, hc.HandleSystem(reader, DLL_BASE, offsets), offsets, DLL_BASE
    )
    assert result.complete and [unit.unit_addr for unit in result.units] == [hero]
    assert result.context["local_count"] == 1


def test_stale_primary_is_conflict_evidence_not_a_local_member_or_inventory_fallback(
    fake_live,
):
    live, data, _offsets = fake_live
    manager = bytearray(data[0x1B600000])
    header = 0x1B6001F0
    struct.pack_into("<III", manager, 0x1F0, header, (~header) & 0xFFFFFFFF, 0)
    data[0x1B600000] = bytes(manager)
    report = live.read_live("fixture", verbose=False)
    assert report["selected_units"] == []
    assert report["selected_unit"]["code"] == "H004"
    assert report["selected_unit"]["selection_membership_state"] == "conflict"
    assert report["slots"] == [] and report["strategy_used"] == "handle"
    assert any(
        "不并入本地集合" in message for message in report["selection_diagnostics"]
    )


def test_legacy_builtin_primary_rejects_a_self_resolving_item_without_enumerating():
    data, _reader, _system, _hero, _other, offsets = _selection_memory(
        [(0x80000007, 0x5001), (0x80000008, 0x5002)]
    )
    manager = bytearray(data[0x1B600000])
    struct.pack_into("<I", manager, offsets.sel_entry_off, 0x10000000)
    data[0x1B600000] = bytes(manager)
    item = bytearray(data[0x10000000])
    struct.pack_into("<II", item, offsets.entry_pair_off, 0x11, 0xAA)
    data[0x10000000] = bytes(item)

    class TracedReader(hc.MemoryReader):
        def __init__(self, regions):
            super().__init__(regions)
            self.addresses = []

        def read(self, addr: int, size: int) -> bytes | None:
            self.addresses.append(addr)
            return super().read(addr, size)

    reader = TracedReader(list(data.items()))
    system = hc.HandleSystem(reader, DLL_BASE, offsets)
    assert system.resolve(0x11, 0xAA) == 0x10000000
    assert hc.selected_unit(reader, system, offsets, DLL_BASE) is None
    assert 0x3001000C in reader.addresses  # Proved UNIT role is checked.
    assert not {0x1B6001F0, 0x1B6001F4, 0x1B6001F8, 0x1B700000} & set(reader.addresses)


def test_legacy_builtin_primary_checks_role_but_does_not_need_collection_bytes():
    data, _reader, _system, _hero, other, offsets = _selection_memory(
        [(0x80000007, 0x5001), (0x80000008, 0x5002)]
    )
    manager = bytearray(data[0x1B600000])
    struct.pack_into("<I", manager, offsets.sel_entry_off, other)
    data[0x1B600000] = bytes(manager[:0x1E4])
    reader = hc.MemoryReader(list(data.items()))
    system = hc.HandleSystem(reader, DLL_BASE, offsets)
    primary = hc.selected_unit(reader, system, offsets, DLL_BASE)
    assert primary is not None and primary.unit_addr == other and primary.code == "N02A"
    collection = hc.selected_units(reader, system, offsets, DLL_BASE)
    assert not collection.complete and collection.primary_unit == primary
    assert any("local_head 不可读" in issue for issue in collection.diagnostics)

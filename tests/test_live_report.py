"""Structured reports retain exact evidence without accessing a game/cache."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json
import importlib
import os
from pathlib import Path
from typing import Any

import pytest

from gametool.live_report import (
    LiveReportError,
    compare_live_reports,
    format_live_report_diff,
    read_live_report,
    validate_report_destination,
    write_live_report,
)
from gametool.live_report_json import (
    ExactJsonNumber,
    format_report_json,
    parse_report_json,
    values_equal,
)


def _unit(addr: int, **extra: Any) -> dict[str, Any]:
    return {
        "addr": addr,
        "code": "H001",
        "unit": "英雄",
        "owner": 0,
        "x": 0,
        "y": 2,
        "items": [],
        "items_complete": True,
        **extra,
    }


def _report(**extra: Any) -> dict[str, Any]:
    return {
        "pid": 777,
        "captured_at": "2026-10-27T10:00:00Z",
        "version": {"version": "1.27.0.52240", "engine": "classic", "arch": "x86"},
        "process_identity": {
            "pid": 777,
            "creation_time": 123456789012345678,
            "executable_path": "C:/Games/war3.exe",
            "state": "confirmed",
        },
        "map_epoch": "synthetic-match-1",
        "selected_units": [_unit(1000)],
        "selection_complete": True,
        "selection_diagnostics": [],
        "notes": [],
        **extra,
    }


def test_report_round_trip_preserves_full_nested_evidence_and_file_identity(tmp_path):
    report = _report(
        selected_units=[
            _unit(
                1000,
                items=[
                    {
                        "slot": 6,
                        "addr": 2000,
                        "code": "I001",
                        "name": "物品\n第二行",
                        "charges": 0,
                        "extra": ["\ufeff", {"native": "完整"}],
                    }
                ],
            )
        ],
        notes=["未知偏移\n完整原因", {"future": [None, False, "extra"]}],
        extension={
            "precise": Decimal("123456789.0000000000000000001"),
            "nested": [[], {}, None],
        },
        owner_counts={0: 0, 12: 257},
    )
    target = tmp_path / "report.json"
    write_live_report(target, report)
    before = target.stat()
    raw = target.read_bytes()
    loaded = read_live_report(target)
    after = target.stat()
    assert loaded.original_bytes == raw == target.read_bytes()
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    assert loaded.metadata["schema"] == "gamexray-live-report"
    assert loaded.source["size"] == len(raw)
    assert loaded["selected_units"][0]["items"][0]["extra"][1]["native"] == "完整"
    assert loaded["owner_counts"] == {"0": 0, "12": 257}
    assert "123456789.0000000000000000001" in loaded.to_json()
    assert (
        json.loads(loaded.to_json(), parse_float=Decimal)["extension"]["precise"]
        == report["extension"]["precise"]
    )
    assert json.loads(json.dumps(loaded.to_dict()))["extension"]["precise"] == {
        "value_type": "exact-json-number",
        "value": "123456789.0000000000000000001",
    }
    assert report["owner_counts"] == {0: 0, 12: 257}


def test_legacy_read_and_resave_retains_original_and_import_provenance(tmp_path):
    original = b'{"selected_unit":{"addr":123,"items":[]},"notes":["old"],"future":{"x":1e9999}}'
    old = tmp_path / "legacy.json"
    old.write_bytes(original)
    loaded = read_live_report(old)
    assert loaded.metadata["schema"] == "legacy-live-json"
    assert loaded.original_bytes == original
    new = write_live_report(tmp_path / "new.json", loaded)
    saved = read_live_report(new)
    assert values_equal(loaded, saved)
    assert (
        saved.metadata["provenance"]["imported_source"]["sha256"]
        == loaded.source["sha256"]
    )
    assert "1e9999" in saved.to_json()
    assert old.read_bytes() == original


def test_schema_rejects_unsupported_and_ambiguous_documents(tmp_path):
    target = tmp_path / "invalid.json"
    for text in (
        '{"schema":"other","report":{}}',
        '{"schema":"gamexray-live-report","schema_version":true,"report":{"slots":[]}}',
        '{"schema":"gamexray-live-report","schema_version":2,"report":{"slots":[]}}',
        '{"arbitrary":[]}',
    ):
        target.write_text(text, encoding="utf-8")
        with pytest.raises(LiveReportError):
            read_live_report(target)


def test_fresh_file_only_preserves_existing_bytes_and_metadata(tmp_path):
    target = tmp_path / "asset.txt"
    target.write_bytes(b"user-owned\x00asset")
    before = target.stat()
    for action in (
        lambda: validate_report_destination(target),
        lambda: write_live_report(target, _report()),
    ):
        with pytest.raises(LiveReportError, match="exists"):
            action()
    after = target.stat()
    assert target.read_bytes() == b"user-owned\x00asset"
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    assert list(tmp_path.iterdir()) == [target]


def test_serialization_is_strict_and_leaves_no_partial_output(tmp_path):
    cycle = []
    cycle.append(cycle)
    for value in (
        float("nan"),
        float("inf"),
        Decimal("NaN"),
        object(),
        (1, 2),
        cycle,
        {1: "first", "1": "collision"},
    ):
        with pytest.raises(LiveReportError):
            write_live_report(tmp_path / "bad.json", _report(extra=value))
        assert list(tmp_path.iterdir()) == []


def test_read_checks_identity_again_after_complete_json_validation(
    tmp_path, monkeypatch
):
    import gametool.live_report as module

    target = write_live_report(tmp_path / "report.json", _report())
    original_parse = module.parse_report_json

    def mutating_parse(text):
        result = original_parse(text)
        replacement = tmp_path / "replacement.json"
        replacement.write_bytes(target.read_bytes())
        os.replace(replacement, target)
        return result

    monkeypatch.setattr(module, "parse_report_json", mutating_parse)
    with pytest.raises(LiveReportError, match="changed"):
        read_live_report(target)


def test_publication_race_cannot_overwrite_concurrent_asset(tmp_path, monkeypatch):
    import gametool.live_report_io as module

    target = tmp_path / "report.json"
    original_link = module.os.link

    def concurrent_writer(source, destination, **kwargs):
        Path(destination).write_bytes(b"concurrent-user-file")
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(module.os, "link", concurrent_writer)
    with pytest.raises(LiveReportError, match="publish"):
        write_live_report(target, _report())
    assert target.read_bytes() == b"concurrent-user-file"
    assert list(tmp_path.iterdir()) == [target]


def test_symlink_source_and_parent_are_rejected(tmp_path):
    source = tmp_path / "real.json"
    source.write_text('{"slots":[]}', encoding="utf-8")
    link = tmp_path / "linked.json"
    folder = tmp_path / "linked-folder"
    try:
        link.symlink_to(source)
        folder.symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Host cannot create symlinks: {exc}")
    with pytest.raises(LiveReportError):
        read_live_report(link)
    with pytest.raises(LiveReportError):
        write_live_report(folder / "output.json", _report())


@pytest.mark.skipif(os.name != "nt", reason="Windows junction boundary")
def test_windows_junction_parent_is_rejected_without_symlink_privileges(tmp_path):
    target = tmp_path / "directory"
    target.mkdir()
    linked = tmp_path / "junction"
    junction = getattr(importlib.import_module("_winapi"), "CreateJunction")
    junction(str(target), str(linked))
    with pytest.raises(LiveReportError, match="ordinary directory"):
        write_live_report(linked / "output.json", _report())
    assert list(target.iterdir()) == []


def test_full_selection_reordering_uses_instance_identity_and_compares_every_field():
    old = _report(selected_units=[_unit(1000), _unit(2000, x=9)])
    new = deepcopy(old)
    new["captured_at"] = "2026-10-27T10:05:00Z"
    new["selected_units"].reverse()
    result = compare_live_reports(old, new)
    assert result["comparison_complete"] is True
    assert result["has_changes"] is False
    new["selected_units"][0]["x"] = 0
    result = compare_live_reports(old, new)
    assert len(result["changes"]) == 1
    assert result["changes"][0]["old"] == 9
    assert result["changes"][0]["new"] == 0
    assert result["changes"][0]["identity"]["old"]["addr"] == 2000


def test_same_rawcode_different_units_never_merge_and_removal_requires_full_identity():
    old = _report(all_units=[_unit(1000), _unit(2000)], all_units_complete=True)
    new = deepcopy(old)
    new["all_units"] = [_unit(2000)]
    result = compare_live_reports(old, new)
    removed = [
        change for change in result["changes"] if change["kind"] == "record_removed"
    ]
    assert len(removed) == 1 and removed[0]["old"]["addr"] == 1000
    assert result["comparison_complete"] is True
    del new["map_epoch"]
    result = compare_live_reports(old, new)
    assert result["comparison_complete"] is False
    assert not any(change["kind"] == "record_removed" for change in result["changes"])
    assert any(change["kind"] == "observed_only_old" for change in result["changes"])


def test_partial_coverage_does_not_erase_old_items_or_convert_unknown_to_empty():
    old = _report(
        selected_units=[_unit(1000, items=[{"slot": 1, "addr": 3000, "code": "I001"}])]
    )
    new = deepcopy(old)
    new["selected_units"][0]["items"] = []
    new["selected_units"][0]["items_complete"] = False
    result = compare_live_reports(old, new)
    assert result["comparison_complete"] is False
    assert any(change["kind"] == "observed_only_old" for change in result["changes"])
    assert not any(change["kind"] == "record_removed" for change in result["changes"])
    new["selected_units"][0]["items"] = None
    result = compare_live_reports(old, new)
    assert any(change["kind"] == "availability_changed" for change in result["changes"])


def test_slot_item_replacement_retains_both_complete_records():
    before = {
        "slot": 6,
        "addr": 3000,
        "code": "I001",
        "name": "旧物品",
        "charges": 0,
        "extension": {"all": [1, 2, 3]},
    }
    after = {
        "slot": 6,
        "addr": 4000,
        "code": "I001",
        "name": "同码新物品",
        "charges": 99,
        "extension": {"all": [4, 5, 6]},
    }
    old = _report(selected_units=[_unit(1000, items=[before])])
    new = _report(selected_units=[_unit(1000, items=[after])])
    result = compare_live_reports(old, new)
    replacements = [row for row in result["changes"] if row["kind"] == "item_replaced"]
    assert len(replacements) == 1
    assert replacements[0]["old"] == before
    assert replacements[0]["new"] == after
    assert "同码新物品" in format_live_report_diff(result)
    assert json.loads(result.to_json())["changes"][0]["new"] == after


@pytest.mark.parametrize("missing", ["addr", "code"])
@pytest.mark.parametrize("omit", [False, True])
def test_sparse_item_identity_becoming_known_never_confirms_a_replacement(
    missing, omit
):
    before: dict[str, Any] = {
        "slot": 0,
        "addr": 3000,
        "code": "I001",
        "diagnostics": ["identity unreadable"],
    }
    if omit:
        del before[missing]
    else:
        before[missing] = None
    old = _report(selected_units=[_unit(1000, items=[before], items_complete=False)])
    new = _report(
        selected_units=[_unit(1000, items=[{"slot": 0, "addr": 4000, "code": "I002"}])]
    )
    result = compare_live_reports(old, new)
    assert result["comparison_complete"] is False
    assert not any(change["kind"] == "item_replaced" for change in result["changes"])
    assert any(
        change["kind"] in {"availability_changed", "field_missing"}
        for change in result["changes"]
    )


@pytest.mark.parametrize(
    "boundary",
    [
        "pid-reuse",
        "different-process",
        "different-build",
        "different-match",
        "missing-build",
    ],
)
def test_identity_boundaries_preserve_observations_without_definite_absence(boundary):
    old = _report(all_units=[_unit(1000)], all_units_complete=True)
    new = deepcopy(old)
    new["all_units"] = []
    if boundary == "pid-reuse":
        del old["process_identity"]["creation_time"]
        del new["process_identity"]["creation_time"]
    elif boundary == "different-process":
        new["process_identity"]["creation_time"] += 1
    elif boundary == "different-build":
        new["version"]["version"] = "3.0.0.24268"
    elif boundary == "different-match":
        new["map_epoch"] = "another-match"
    else:
        del new["version"]
    result = compare_live_reports(old, new)
    assert result["comparison_complete"] is False
    assert result["has_changes"] is True
    assert not any(
        change["kind"] in {"record_removed", "record_added"}
        for change in result["changes"]
    )
    assert result["diagnostics"]


def test_architecture_only_does_not_prove_build_and_time_units_cannot_be_merged():
    old = _report(version={"arch": "x86"})
    new = deepcopy(old)
    assert compare_live_reports(old, new)["identity"]["same_build"] is None
    old, new = _report(), _report()
    old["process_identity"]["creation_time_format"] = "windows-filetime"
    new["process_identity"]["creation_time_format"] = "unix-nanoseconds"
    result = compare_live_reports(old, new)
    assert result["identity"]["same_process"] is False
    assert result["comparison_complete"] is False


def test_invalid_declared_instance_and_evidence_states_are_diagnostic():
    report = _report(
        selected_units=[_unit(1000, instance_id=True, generation={"invalid": "full"})],
        extension={"state": ["bad", "shape"], "value": 0},
    )
    result = compare_live_reports(report, deepcopy(report))
    assert result["comparison_complete"] is False
    assert any(
        row["kind"] == "physical_identity_missing" for row in result["diagnostics"]
    )
    assert any(
        row["kind"] == "invalid_evidence_state"
        and row["record"]["state"] == ["bad", "shape"]
        for row in result["diagnostics"]
    )


def test_legacy_selection_matches_new_list_and_keeps_conflicting_legacy_evidence():
    old = _report()
    old["selected_unit"] = old.pop("selected_units")[0]
    new = _report()
    assert compare_live_reports(old, new)["has_changes"] is False
    new["selected_unit"] = _unit(9000, custom_extra="do not discard")
    result = compare_live_reports(old, new)
    assert result["comparison_complete"] is False
    assert any(
        row["kind"] == "legacy_selection_conflict"
        and row["selected_unit"]["custom_extra"] == "do not discard"
        for row in result["diagnostics"]
    )


def test_duplicate_and_missing_physical_identities_retain_every_record():
    old = _report(
        selected_units=[
            _unit(1000),
            _unit(1000, custom="second"),
            {"code": "H001", "items": []},
        ]
    )
    result = compare_live_reports(old, deepcopy(old))
    assert result["comparison_complete"] is False
    duplicate = [
        row
        for row in result["diagnostics"]
        if row["kind"] == "duplicate_physical_identity"
    ]
    assert len(duplicate) == 2
    assert duplicate[0]["records"][1]["custom"] == "second"
    assert result["has_changes"] is False
    assert (
        len(
            [
                row
                for row in result["diagnostics"]
                if row["kind"] == "physical_identity_missing"
            ]
        )
        == 2
    )


def test_exact_numbers_unknown_and_zero_keep_their_distinct_meanings():
    old = _report(custom=Decimal("0.100000000000000000000001"), known=0, unknown=None)
    new = _report(custom=Decimal("0.100000000000000000000002"), known=False, unknown=0)
    result = compare_live_reports(old, new)
    by_path = {change["path"]: change for change in result["changes"]}
    assert by_path["/custom"]["old"].text.endswith("1")
    assert by_path["/custom"]["new"].text.endswith("2")
    assert by_path["/known"]["kind"] == "value_changed"
    assert by_path["/unknown"]["kind"] == "availability_changed"
    assert "0.100000000000000000000002" in result.to_json()
    assert json.dumps(result.to_dict())
    assert (
        compare_live_reports(_report(number=1), _report(number=Decimal("1.000")))[
            "has_changes"
        ]
        is False
    )


def test_unknown_reading_states_apply_to_every_nested_value_without_confirmation():
    old = _report(
        reading={"state": "declared-layout-only", "value": {"nested": [0, {"mana": 1}]}}
    )
    new = deepcopy(old)
    new["reading"]["value"]["nested"][1]["mana"] = 2
    result = compare_live_reports(old, new)
    assert result["comparison_complete"] is False
    assert len(result["changes"]) == 1
    assert result["changes"][0]["state"] == "uncertain"
    assert result["changes"][0]["new"] == 2
    unknown = _report(selected_units=[_unit(1000, state="invalid")])
    result = compare_live_reports(unknown, _report(selected_units=[]))
    assert not any(change["kind"] == "record_removed" for change in result["changes"])


def test_matching_null_readings_and_unavailable_selection_still_disclose_unknown():
    unknown = _report(selected_units=[_unit(1000, x=None)])
    assert (
        compare_live_reports(unknown, deepcopy(unknown))["comparison_complete"] is False
    )
    legacy = _report(selected_units=None, selected_unit=_unit(1000))
    result = compare_live_reports(legacy, deepcopy(legacy))
    assert result["comparison_complete"] is False
    assert any(row["kind"] == "selection_unavailable" for row in result["diagnostics"])


def test_full_notes_extensions_and_late_records_are_compared_without_count_limits():
    old = _report(
        selected_units=[_unit(index + 1000) for index in range(257)],
        notes=[f"unknown {index}" for index in range(257)],
    )
    new = deepcopy(old)
    new["selected_units"][-1]["extension"] = {"late": ["full", {"evidence": "last"}]}
    new["notes"][-1] += " changed"
    result = compare_live_reports(old, new)
    assert any(
        change["path"] == "/selected_units/256/extension"
        and change["new"]["late"][1]["evidence"] == "last"
        for change in result["changes"]
    )
    assert any(change["path"] == "/notes/256" for change in result["changes"])
    assert "unknown 256 changed" in format_live_report_diff(result)


@pytest.mark.parametrize(
    "name",
    [
        "selected_units",
        "units",
        "all_units",
        "owned_units",
        "unit_matches",
        "items",
        "slots",
        "resources",
        "evidence",
    ],
)
def test_nested_extension_role_names_remain_ordered_raw_values(name):
    old = _report(extension={name: ["H001", "I001", {"nested": [1, 2, 3]}]})
    old["selected_units"][0]["extension"] = {name: ["unchanged", 0]}
    result = compare_live_reports(old, deepcopy(old))
    assert result["comparison_complete"] is True
    assert result["has_changes"] is False
    changed = deepcopy(old)
    changed["extension"][name][-1]["nested"][-1] = 4
    result = compare_live_reports(old, changed)
    assert len(result["changes"]) == 1
    assert result["changes"][0]["path"] == f"/extension/{name}/2/nested/2"
    assert result["changes"][0]["old"] == 3
    assert result["changes"][0]["new"] == 4


@pytest.mark.parametrize(
    "role",
    [
        "selected_units",
        "units",
        "owned_units",
        "all_units",
        "unit_matches",
        "slots",
        "resources",
        "evidence",
    ],
)
def test_reflexive_comparison_invariant_across_collection_coverage_and_identity(role):
    """Unknown/duplicate records add diagnostics, never invented self changes."""
    unit = _unit(1000)
    row = (
        {"slot": 0, "addr": 2000, "code": "I001"}
        if role == "slots"
        else {"addr": 2000, "gold": 0}
        if role == "resources"
        else {"key": "code", "value": "H001", "state": "confirmed"}
        if role == "evidence"
        else unit
    )
    sparse = (
        {"key": "code", "value": None, "state": "unknown"}
        if role == "evidence"
        else {"code": "H001", "x": None}
    )
    for collection_state in ("absent", "null", "empty", "sparse", "duplicate"):
        for complete in (False, True):
            for process_known in (False, True):
                report = _report()
                flag = (
                    "selection_complete"
                    if role == "selected_units"
                    else role + "_complete"
                )
                report[flag] = complete
                if not process_known:
                    del report["process_identity"]["creation_time"]
                if collection_state == "absent":
                    report.pop(role, None)
                else:
                    report[role] = (
                        None
                        if collection_state == "null"
                        else []
                        if collection_state == "empty"
                        else [deepcopy(sparse)]
                        if collection_state == "sparse"
                        else [deepcopy(row), deepcopy(row)]
                    )
                if role == "selected_units" and collection_state == "null":
                    report["selected_unit"] = None
                result = compare_live_reports(report, deepcopy(report))
                assert result["has_changes"] is False, (
                    role,
                    collection_state,
                    complete,
                    process_known,
                )
                assert result["changes"] == []
                if collection_state == "null":
                    assert result["comparison_complete"] is False
                    assert result["diagnostics"]


@pytest.mark.parametrize(
    "role",
    [
        "selected_units",
        "units",
        "owned_units",
        "all_units",
        "unit_matches",
        "slots",
        "resources",
        "evidence",
    ],
)
def test_explicit_null_collections_never_equal_confirmed_empty_collections(role):
    old = _report()
    flag = "selection_complete" if role == "selected_units" else role + "_complete"
    old[flag] = True
    old[role] = None
    if role == "selected_units":
        old["selected_unit"] = None
    new = deepcopy(old)
    new[role] = []
    result = compare_live_reports(old, new)
    assert result["comparison_complete"] is False
    assert result["has_changes"] is True
    assert any(
        change["path"] == "/" + role
        and change["kind"] == "availability_changed"
        and change["old"] is None
        and change["new"] == []
        for change in result["changes"]
    )
    assert not any(
        change["kind"] in {"record_added", "record_removed"}
        for change in result["changes"]
    )


def test_only_absent_new_selection_key_uses_legacy_empty_compatibility():
    legacy = _report(selected_unit=None)
    del legacy["selected_units"]
    known_empty = _report(selected_units=[], selected_unit=None)
    assert compare_live_reports(legacy, known_empty)["has_changes"] is False
    explicit_unknown = _report(selected_units=None, selected_unit=None)
    result = compare_live_reports(explicit_unknown, known_empty)
    assert result["comparison_complete"] is False and result["has_changes"] is True


@pytest.mark.parametrize("identity_field", ["code", "address", "slot"])
def test_nested_identity_qualification_and_partial_inventory_invariants(identity_field):
    states = (
        "unknown",
        "unavailable",
        "invalid",
        "conflict",
        "declared-layout-only",
        "missing-state",
        "incomplete",
    )
    for state in states:
        for complete in (False, True):
            old = _report()
            item: dict[str, Any] = {
                "slot": 0,
                "addr": 2000,
                "code": "I001",
                "charges": 3,
                "evidence": [
                    {
                        "key": identity_field,
                        "value": "I001"
                        if identity_field == "code"
                        else 2000
                        if identity_field == "address"
                        else 0,
                        "source": "unverified profile",
                    },
                    {"key": "charges", "value": 3, "state": "confirmed"},
                ],
            }
            if state != "missing-state":
                item["evidence"][0]["state"] = (
                    "confirmed" if state == "incomplete" else state
                )
            if state == "incomplete":
                item["evidence"][0]["complete"] = False
            old["selected_units"][0].update(items=[item], items_complete=complete)
            new = deepcopy(old)
            replacement = new["selected_units"][0]["items"][0]
            replacement["addr"] = 3000
            replacement["charges"] = 4
            replacement["evidence"][1]["value"] = 4
            if identity_field == "address":
                replacement["evidence"][0]["value"] = 3000
            result = compare_live_reports(old, new)
            assert result["comparison_complete"] is False
            assert not any(
                change["kind"] == "item_replaced" and change["state"] == "confirmed"
                for change in result["changes"]
            ), (identity_field, state, complete)
            assert any(
                row["kind"] in {"unconfirmed_evidence", "physical_identity_missing"}
                for row in result["diagnostics"]
            )
            changes = [
                change
                for change in result["changes"]
                if change["path"].endswith("/charges")
            ]
            assert changes and changes[0]["old"] == 3 and changes[0]["new"] == 4
            if identity_field != "slot":
                assert changes[0]["state"] == "confirmed"
            assert compare_live_reports(old, deepcopy(old))["has_changes"] is False


def test_complete_item_replacement_traverses_nonidentity_unknown_evidence():
    old = _report(
        selected_units=[
            _unit(
                1000,
                items=[
                    {
                        "slot": 0,
                        "addr": 2000,
                        "code": "I001",
                        "evidence": [
                            {
                                "key": "charges",
                                "value": None,
                                "state": "unavailable",
                                "diagnostics": ["complete unknown note"],
                            }
                        ],
                    }
                ],
            )
        ]
    )
    new = deepcopy(old)
    new["selected_units"][0]["items"][0]["addr"] = 3000
    result = compare_live_reports(old, new)
    assert any(
        change["kind"] == "item_replaced" and change["state"] == "confirmed"
        for change in result["changes"]
    )
    assert any(
        row["kind"] == "unconfirmed_evidence"
        and row["record"].get("diagnostics") == ["complete unknown note"]
        for row in result["diagnostics"]
    )
    assert result["comparison_complete"] is False


def test_unidentified_record_changes_keep_complete_raw_evidence_without_lifecycle_claims():
    old = _report(
        selected_units=[{"code": "H001", "items": [], "future": {"full": [1, 2, 3]}}]
    )
    new = deepcopy(old)
    new["selected_units"][0]["future"]["full"][-1] = 4
    result = compare_live_reports(old, new)
    assert result["has_changes"] is True and result["comparison_complete"] is False
    assert any(
        change["old"] == 3 and change["new"] == 4 for change in result["changes"]
    )
    assert not any(
        change["kind"] in {"record_added", "record_removed"}
        for change in result["changes"]
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[1,]",
        '{"a":1,}',
        '{"a":1,"a":2}',
        '{"a":NaN}',
        '{"a":Infinity}',
        '{"a":1} {}',
        '{"a":01}',
        '{"a":"\\ud800"}',
        '{"a":[1,2}',
    ],
)
def test_complete_json_validation_rejects_malformed_documents(text):
    with pytest.raises(LiveReportError):
        parse_report_json(text)


def test_codec_handles_deep_documents_and_large_exact_numbers_without_global_quotas(
    tmp_path,
):
    depth = 1500
    integer = "9" * 5001
    exponent = "9" * 5001
    raw = (
        '{"selected_units":[],"selection_complete":true,"deep":'
        + "[" * depth
        + integer
        + "]" * depth
        + ',"precise":1.2345678901234567890123456789,"vast":1e'
        + exponent
        + "}"
    )
    parsed = parse_report_json(raw)
    assert format_report_json(parsed) == raw
    assert values_equal(parsed, parse_report_json(raw))
    saved = write_live_report(tmp_path / "deep.json", parsed)
    assert read_live_report(saved).to_json() == raw
    invalid = raw[:-1] + ',"late":[0,]}'
    with pytest.raises(LiveReportError):
        parse_report_json(invalid)
    assert isinstance(parsed["precise"], ExactJsonNumber)

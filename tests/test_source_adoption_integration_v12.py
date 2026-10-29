"""Independent source-to-query/export contracts for the v0.12 Windows release."""

from __future__ import annotations

import base64
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from gametool.api import load_map
from gametool.dev_test import create_test_environment
from gametool.gui_offline_acceptance_support import _identity
from gametool.gui_offline_acceptance_v12_evidence import (
    read_loadout_export,
    validate_call_evidence,
    validate_campaign_metadata,
    validate_loadout_evidence,
)
from gametool.gui_offline_acceptance_v12_fixtures import (
    CALL_SOURCES,
    CAMPAIGN_WTS_TEXT,
    CHILD_MEMBER,
    MAP_DESCRIPTION,
    MAP_NAME,
    WTS_TEXT,
    source_adoption_fixture_payloads,
)
from gametool.loadout_report import (
    read_loadout_report,
    select_loadout_report,
    write_loadout_export,
)
from gametool.knowledge_pack import write_knowledge_pack_report
from gametool.map_metadata_exports import (
    format_map_metadata_evidence,
    format_map_string_evidence,
)
from gametool.mpq import MPQArchive
from gametool.pack_query_script_calls import query_script_calls
from gametool.pack_query_script_snapshot import ScriptPackSnapshot
from gametool.w3f import parse_w3f_evidence, w3f_info_to_dict
from gametool.wts import parse_wts_evidence


@pytest.fixture
def authored(tmp_path: Path):
    payloads = source_adoption_fixture_payloads()
    for relative, data in payloads.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    before = {name: _identity(tmp_path / name) for name in payloads}
    yield tmp_path, payloads
    for relative, payload in payloads.items():
        assert (tmp_path / relative).read_bytes() == payload
        assert _identity(tmp_path / relative) == before[relative]


def test_source_calls_exact_complete_record_filters_and_provenance(authored) -> None:
    root, _payloads = authored
    result = query_script_calls(root / "v12/calls-pack", "")
    assert result.source_stable and not result.input_error
    assert (result.total, result.omitted, len(result.calls)) == (10, 0, 10)
    validate_call_evidence(
        [asdict(row.call) for row in result.calls if row.call is not None]
    )
    for row in result.calls:
        assert row.origin == "source"
        assert (
            row.source_file_fingerprint
            == hashlib.sha256(CALL_SOURCES[row.source].encode("utf-8")).hexdigest()
        )
    selected = query_script_calls(root / "v12/calls-pack", "h001 && CreateUnit")
    assert selected.total == 1 and selected.calls[0].callee == "CreateUnit"
    assert selected.calls[0].arguments == (
        "Player(0)",
        "'h001'",
        "12.5",
        "-8.25",
        "90.",
    )
    limited = query_script_calls(root / "v12/calls-pack", "", 1)
    assert (limited.total, limited.omitted, len(limited.calls)) == (10, 9, 1)
    assert "9" in "\n".join(limited.lines)
    assert limited.diagnostics == result.diagnostics


def test_call_empty_sources_and_broken_sources_remain_distinct(authored) -> None:
    root, _payloads = authored
    empty = query_script_calls(root / "v12/calls-empty", "")
    assert empty.total == 0 and empty.calls == () and not empty.input_error
    assert "空词" in "\n".join(empty.lines)
    broken = query_script_calls(root / "v12/calls-broken", "")
    assert broken.diagnostics
    assert not broken.script_coverage.complete
    assert any("CreateItem(" in note.raw for note in broken.diagnostics)
    invalid = query_script_calls(root / "v12/calls-pack", "&&")
    assert invalid.input_error and not invalid.has_matches


@pytest.mark.parametrize("name", ("six", "nine", "partial", "empty"))
@pytest.mark.parametrize("format", ("json", "md", "tsv"))
def test_loadout_complete_source_and_exact_slots_survive_every_export(
    authored, name: str, format: str
) -> None:
    root, payloads = authored
    relative = f"v12/plans/{name}.json"
    report = read_loadout_report(root / relative)
    destination = root / f"{name}-evidence.{format}"
    write_loadout_export(destination, select_loadout_report(report), format)
    validate_loadout_evidence(
        read_loadout_export(destination), payloads[relative], name
    )


def test_loadout_filtered_selection_keeps_every_original_record_and_zero_recovery(
    authored,
) -> None:
    root, payloads = authored
    report = read_loadout_report(root / "v12/plans/nine.json")
    selected = select_loadout_report(report, "远征甲 && I001")
    validate_loadout_evidence(
        selected.to_dict(), payloads["v12/plans/nine.json"], "nine", selected=(1,)
    )
    unmatched = select_loadout_report(report, "不存在的方案")
    validate_loadout_evidence(
        unmatched.to_dict(), payloads["v12/plans/nine.json"], "nine", selected=()
    )


def _assert_wts_partition(raw: bytes, report) -> None:
    pieces = sorted((*report.records, *report.regions), key=lambda row: row.byte_start)
    offset = 0
    for row in pieces:
        assert row.byte_start == offset
        assert row.raw_bytes == raw[row.byte_start : row.byte_end]
        offset = row.byte_end
    assert offset == len(raw)


def test_utf16_wts_standalone_base_inheritance_reaches_map_and_json(authored) -> None:
    root, _payloads = authored
    path = root / "v12/unicode-inheritance.w3x"
    md = load_map(str(path))
    try:
        child = md.obj_identity_index[("物品", "yV12")]
        assert child.name == MAP_NAME and child.base_id == "yV11"
        assert child.field_values["ides"] == MAP_DESCRIPTION
        assert child.field_values["igol"] == "7"
        assert any(
            row.key == "igol" and row.value == "91" and row.state == "overridden"
            for row in child.field_evidence
        )
        assert not [
            note for note in md.diagnostics if note.component == "object-inheritance"
        ]
        report = md.wts_reports["war3map.wts"]
        raw = b"\xff\xfe" + WTS_TEXT.encode("utf-16-le")
        assert dict(report.table) == {1: MAP_NAME, 2: MAP_DESCRIPTION}
        assert report.complete and report.raw_bytes == raw
        _assert_wts_partition(raw, report)
        evidence = json.loads(format_map_string_evidence(md))
        tables = evidence["sources"]
        assert len(tables) == 1
        assert base64.b64decode(tables[0]["raw_bytes_base64"]) == raw
    finally:
        md.close()


@pytest.mark.parametrize("trailing", (False, True))
def test_w3f_v3_explicit_layout_and_full_trailing_evidence(
    authored, trailing: bool
) -> None:
    root, _payloads = authored
    wts = parse_wts_evidence(b"\xfe\xff" + CAMPAIGN_WTS_TEXT.encode("utf-16-be"))
    raw = (
        root / ("v12/campaign-v3-trailing.w3f" if trailing else "v12/campaign-v3.w3f")
    ).read_bytes()
    info = parse_w3f_evidence(raw, wts.table)
    validate_campaign_metadata(w3f_info_to_dict(info), trailing=trailing)
    assert (
        b"".join(field.raw_bytes for field in info.byte_fields)
        == raw[: info.consumed_bytes]
    )
    for field in info.byte_fields:
        assert field.raw_bytes == raw[field.offset : field.end_offset]
    assert info.map_order == [("reserved-retained", CHILD_MEMBER)]


def test_unicode_campaign_member_identity_and_wts_export_remain_independent(
    authored,
) -> None:
    root, _payloads = authored
    with MPQArchive(str(root / "v12/unicode-campaign.w3n")) as archive:
        assert not archive.has_file("(listfile)")
        assert CHILD_MEMBER not in archive.list_files()
    md = load_map(str(root / "v12/unicode-campaign.w3n"))
    try:
        assert md.w3f is not None
        validate_campaign_metadata(json.loads(format_map_metadata_evidence(md))["w3f"])
        assert len(md.sub_maps) == 1
        child = md.sub_maps[0]
        assert child.path.endswith(CHILD_MEMBER)
        assert child.obj_identity_index[("物品", "yV12")].name == MAP_NAME
        assert md.w3f.maps[0].path == CHILD_MEMBER
        raw = b"\xfe\xff" + CAMPAIGN_WTS_TEXT.encode("utf-16-be")
        report = md.wts_reports["war3campaign.wts"]
        assert report.raw_bytes == raw and report.complete
        _assert_wts_partition(raw, report)
        exported = json.loads(format_map_string_evidence(md))
        assert base64.b64decode(exported["sources"][0]["raw_bytes_base64"]) == raw
        destination = root / "campaign-knowledge-pack"
        publication = write_knowledge_pack_report(md, str(destination))
        assert publication.failed_count == 0
        validate_campaign_metadata(
            json.loads((destination / "地图信息证据.json").read_text("utf-8"))["w3f"]
        )
        written_strings = json.loads(
            (destination / "地图字符串证据.json").read_text("utf-8")
        )
        assert (
            base64.b64decode(written_strings["sources"][0]["raw_bytes_base64"]) == raw
        )
    finally:
        md.close()


def _cli(arguments: tuple[str, ...], environment: dict[str, str]):
    repository = Path(__file__).resolve().parents[1]
    return subprocess.run(
        (sys.executable, "-X", "utf8", str(repository / "main.py"), *arguments),
        cwd=repository,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=60,
        check=False,
    )


def test_public_calls_cli_empty_listing_json_and_again_keep_exact_snapshot(
    authored,
) -> None:
    root, _payloads = authored
    environment = create_test_environment()
    pack = str(root / "v12/calls-pack")
    first = _cli(("pack-query", pack, "calls", "--json"), environment)
    assert first.returncode == 0, first.stdout + first.stderr
    full = json.loads(first.stdout)
    assert full["calls_total"] == 10 and full["calls_omitted"] == 0
    validate_call_evidence([row["call"] for row in full["calls"]])
    assert full["source_stable"] is True and full["input_error"] is False
    invalid = _cli(("pack-query", pack, "calls", "&&", "--json"), environment)
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["input_error"] is True
    replay = _cli(("pack-query", pack, "again", "--json"), environment)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    result = json.loads(replay.stdout)
    assert result["command"] == "calls" and result["query"] == ""
    assert result["calls"] == full["calls"]
    assert (
        result["calls_total"] == 10
        and result["call_diagnostics"] == full["call_diagnostics"]
    )


@pytest.mark.parametrize(
    ("name", "expected_code"), (("six", 0), ("partial", 2), ("empty", 0))
)
def test_public_loadout_cli_exports_complete_source_without_modifying_plan(
    authored, name: str, expected_code: int
) -> None:
    root, payloads = authored
    output = root / f"cli-{name}.json"
    relative = f"v12/plans/{name}.json"
    result = _cli(
        ("loadout", str(root / relative), "--json", "--export", str(output)),
        create_test_environment(),
    )
    assert result.returncode == expected_code, result.stdout + result.stderr
    value = json.loads(result.stdout)
    assert json.loads(output.read_text("utf-8")) == value
    validate_loadout_evidence(value, payloads[relative], name)


@pytest.mark.parametrize("mutation", ("same-size", "new-source", "new-index"))
def test_source_delivery_revalidates_bytes_and_missing_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    pack = tmp_path / "pack"
    source = pack / "脚本原始文本/war3map.j"
    source.parent.mkdir(parents=True)
    raw = b"function Read takes nothing returns nothing\ncall CreateItem('I001', 1, 2)\nendfunction\n"
    source.write_bytes(raw)
    before = source.stat()
    verify = ScriptPackSnapshot.verify

    def mutate_then_verify(snapshot: ScriptPackSnapshot):
        if mutation == "same-size":
            source.write_bytes(raw.replace(b"I001", b"I009"))
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        elif mutation == "new-source":
            (source.parent / "added.lua").write_text(
                "CreateItem(FourCC('I009'),3,4)", "utf-8"
            )
        else:
            (pack / "脚本调用参数索引.tsv").write_text(
                "来源\t函数\t参数序号\t参数值\n", "utf-8"
            )
        return verify(snapshot)

    monkeypatch.setattr(ScriptPackSnapshot, "verify", mutate_then_verify)
    result = query_script_calls(pack, "")
    assert not result.source_stable
    assert any(note.code == "snapshot.changed" for note in result.diagnostics)
    assert len(result.calls) == 1 and result.calls[0].arguments == ("'I001'", "1", "2")
    assert result.calls[0].source_file_fingerprint == hashlib.sha256(raw).hexdigest()


def test_loadout_export_rejects_changed_complete_source_with_restored_mtime(
    tmp_path: Path,
) -> None:
    source = tmp_path / "six.json"
    raw = source_adoption_fixture_payloads()["v12/plans/six.json"]
    source.write_bytes(raw)
    report = read_loadout_report(source)
    before = source.stat()
    changed = raw.replace("I006".encode("utf-16-le"), "I009".encode("utf-16-le"))
    assert len(changed) == len(raw) and changed != raw
    source.write_bytes(changed)
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    destination = tmp_path / "must-not-publish.json"
    with pytest.raises(ValueError, match="变化"):
        write_loadout_export(destination, select_loadout_report(report))
    assert not destination.exists()
    assert source.read_bytes() == changed

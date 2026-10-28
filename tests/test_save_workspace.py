"""Independent save evidence, whole-file queries and read-only export boundaries."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

import pytest

import gametool.real_save_files as save_files
from gametool.real_save_cli import run_real_save_cli
from gametool.save_report_query import (
    format_save_report_markdown,
    save_output_error,
    save_report_payload,
    select_save_report,
    verify_save_report_sources,
    write_save_report,
)
from gametool.safe_output_models import SafeWriteStatus
from tests.save_structure_fixture import cache_bytes, container_bytes, hero_bytes


def test_offline_preload_keeps_full_text_carrier_bytes_without_loading_map(
    tmp_path: Path,
) -> None:
    source = tmp_path / "profile.pld"
    raw = b'\xef\xbb\xbfPreload("-load CODE123"); hero.level=7; unit=H001\r\n'
    source.write_bytes(raw)
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    report = save_files.analyze_real_save_path(source)
    record = report.files[0]
    assert report.complete and report.inventory_complete
    assert report.expected_keys == () and not report.map_associated
    assert report.map_path == report.map_name == ""
    assert record.matched_keys == record.object_matches == ()
    assert record.raw_text == raw[3:].decode("utf-8")
    assert record.codes[0].source_sha256 == hashlib.sha256(raw).hexdigest()
    carrier = record.text_carriers[0]
    assert raw[carrier.byte_offset : carrier.byte_end] == carrier.raw.encode()
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert report.to_dict()["map_association"] == "not_performed"


def test_offline_gamecache_keeps_every_saved_field_and_offset(tmp_path: Path) -> None:
    raw = cache_bytes(
        ((), (), (), (("hero", hero_bytes("classic")),), (("name", b"saved\0"),))
    )
    source = tmp_path / "Campaigns.w3v"
    source.write_bytes(container_bytes(raw, chunks=128))
    report = save_files.analyze_real_save_path(source)
    record = report.files[0]
    assert report.complete
    assert record.object_matches == ()
    fields = record.caches[0].fields
    assert len(fields) == 2
    assert fields[0].value_type == "unit"
    unit = fields[0].value
    assert isinstance(unit, dict)
    assert unit["unit_id"] == "H001"
    assert all(field.offset < field.end for field in fields)
    exported = json.loads(json.dumps(select_save_report(report).to_dict()))
    assert exported["files"][0]["caches"][0]["fields"][0]["fields"]


def test_directory_query_selects_whole_files_and_keeps_filtered_diagnostics(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "a.txt").write_text('Preload("-load CODE1")\n' * 20, encoding="utf-8")
    (root / "b.txt").write_text('Preload("-load CODE2")', encoding="utf-8")
    (root / "opaque.bin").write_bytes(b"\0\x01\xff\0")
    report = save_files.analyze_real_save_path(root)
    assert not report.complete and report.inventory_complete
    selected = select_save_report(report, kind="text", limit=1)
    assert selected.total_files == 3 and selected.matched_files == 2
    assert selected.omitted_files == 1
    assert len(selected.files[0].codes) == 20
    assert any(
        "opaque.bin" in note and "unknown" in note for note in selected.diagnostics
    )
    for format in ("json", "tsv", "md"):
        payload = save_report_payload(selected, format)
        assert "opaque.bin" in payload
        assert "CODE1" in payload and "CODE2" not in payload
    assert not selected.to_dict()["complete"]


def test_boolean_terms_keep_field_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "ALPHAX.txt"
    source.write_text("BETAY", encoding="utf-8")
    report = save_files.analyze_real_save_path(source)
    assert select_save_report(report, "ALPHAX && BETAY").matched_files == 1
    assert select_save_report(report, "ALPHAX%BETAY").matched_files == 0
    assert select_save_report(report, '="BETAY"').matched_files == 1


@pytest.mark.parametrize("limit", (-1, True, 1.5, "1"))
def test_invalid_limit_rejected_before_materializing_record(limit: object) -> None:
    with pytest.raises(ValueError, match="非负整数"):
        select_save_report(save_files.RealSaveReport("", (), ()), limit=limit)  # pyright: ignore[reportArgumentType] - invalid API input is the assertion boundary.


def test_empty_missing_and_unknown_sources_are_structurally_incomplete(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    for source in (empty, tmp_path / "missing"):
        report = save_files.analyze_real_save_path(source)
        assert not report.complete and not report.inventory_complete
        assert report.warnings and not report.files
    source = tmp_path / "unknown.sav"
    source.write_bytes(b"\0\x01\xff\0")
    report = save_files.analyze_real_save_path(source)
    record = report.files[0]
    assert not report.complete and report.inventory_complete
    assert record.unknown_ranges[0]["offset"] == 0
    assert record.unknown_ranges[0]["end"] == 4
    assert record.unknown_ranges[0]["state"] == "unknown"


def test_invalid_json_preserves_full_source_and_explicit_format_diagnostic(
    tmp_path: Path,
) -> None:
    source = tmp_path / "profile.json"
    source.write_text('{"unfinished": 7', encoding="utf-8")
    report = save_files.analyze_real_save_path(source)
    assert not report.complete
    assert report.files[0].raw_text == '{"unfinished": 7'
    assert "JSON 结构无效" in report.files[0].diagnostics[0]


def test_corrupt_container_keeps_source_hash_and_full_diagnostics(
    tmp_path: Path,
) -> None:
    source = tmp_path / "broken.w3z"
    raw = bytearray(container_bytes(b"\0\xff\0", chunks=128))
    raw[-1] ^= 0xFF
    source.write_bytes(raw)
    report = save_files.analyze_real_save_path(source)
    record = report.files[0]
    assert not report.complete and record.container is not None
    assert record.sha256 == hashlib.sha256(raw).hexdigest()
    assert record.container["diagnostics"]
    assert select_save_report(report, "no-such-value").diagnostics


def test_changed_input_snapshot_is_retained_separately_from_current_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "profile.pld"
    source.write_text('Preload("-load BEFORE123")', encoding="utf-8")
    original = save_files._analyze_file

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        source.write_text('Preload("-load AFTER12345")', encoding="utf-8")
        return result

    monkeypatch.setattr(save_files, "_analyze_file", mutate)
    report = save_files.analyze_real_save_path(source)
    assert not report.complete and not report.inventory_complete
    assert report.files == ()
    assert len(report.unverified_files) == 1
    assert report.unverified_files[0].codes[0].code == "-load BEFORE123"
    assert not report.unverified_files[0].source_stable
    assert select_save_report(report).to_dict()["unverified_files"]


def test_source_set_change_retains_other_confirmed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("one", encoding="utf-8")
    original = save_files._analyze_file

    def append(*args, **kwargs):
        result = original(*args, **kwargs)
        (source / "new.txt").write_text("two", encoding="utf-8")
        return result

    monkeypatch.setattr(save_files, "_analyze_file", append)
    report = save_files.analyze_real_save_path(source)
    assert len(report.files) == 1
    assert not report.complete and not report.inventory_complete
    assert any("清单" in note for note in report.warnings)


def test_full_source_hash_is_reverified_before_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("original", encoding="utf-8")
    original = save_files.sha256_regular_file
    called: list[Path] = []

    def mismatch(path: Path):
        called.append(path)
        _digest, identity = original(path)
        return "changed-full-hash", identity

    monkeypatch.setattr(save_files, "sha256_regular_file", mismatch)
    report = save_files.analyze_real_save_path(source)
    assert called == [source]
    assert report.files == () and report.unverified_files
    assert any("SHA256" in note for note in report.warnings)


def test_export_rechecks_sources_and_never_restores_old_input(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    report = save_files.analyze_real_save_path(source)
    source.write_text("after", encoding="utf-8")
    verified = verify_save_report_sources(report)
    assert verified.files == () and verified.unverified_files[0].raw_text == "before"
    assert not verified.complete and not verified.inventory_complete
    assert source.read_text(encoding="utf-8") == "after"
    assert "导出前" in format_save_report_markdown(select_save_report(verified))


def test_export_rejects_sources_directory_members_and_hardlink_aliases(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    root.mkdir()
    source = root / "profile.txt"
    source.write_text("complete evidence", encoding="utf-8")
    report = save_files.analyze_real_save_path(root)
    assert save_output_error(report, source)
    assert save_output_error(report, root / "report.json")
    alias = tmp_path / "alias.txt"
    os.link(source, alias)
    assert "物理别名" in save_output_error(report, alias)
    with pytest.raises(ValueError):
        write_save_report(select_save_report(report), alias)
    assert source.read_text(encoding="utf-8") == "complete evidence"
    output = tmp_path / "report.json"
    assert (
        write_save_report(select_save_report(report), output).status
        is SafeWriteStatus.WRITTEN
    )
    assert (
        json.loads(output.read_text(encoding="utf-8"))["files"][0]["raw_text"]
        == "complete evidence"
    )


def test_cli_without_map_writes_query_metadata_and_preserves_unknown_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import gametool.real_save_cli as cli

    def forbidden(*_args, **_kwargs):
        pytest.fail("offline save must not load a map")

    monkeypatch.setattr(cli, "load_map", forbidden)
    source = tmp_path / "source"
    source.mkdir()
    (source / "known.txt").write_text('Preload("-load CODE123")', encoding="utf-8")
    (source / "unknown.bin").write_bytes(b"\0\xff\0")
    output = tmp_path / "report.json"
    assert (
        run_real_save_cli(
            (
                "--save",
                str(source),
                "--output",
                str(output),
                "--format",
                "json",
                "--query",
                "CODE123",
                "--limit",
                "全部",
            )
        )
        == 2
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["map_association"] == "not_performed"
    assert len(value["files"]) == 1
    assert value["selection"]["matched_files"] == 1
    assert any("unknown.bin" in note for note in value["diagnostics"])
    assert "未完成" in capsys.readouterr().out


def test_source_identity_verification_uses_named_fields_not_dictionary_order(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("original", encoding="utf-8")
    report = save_files.analyze_real_save_path(source)
    identity = report.files[0].source_identity
    assert identity is not None
    shuffled = dict(reversed(tuple(identity.items())))
    record = replace(report.files[0], source_identity=shuffled)
    verified = verify_save_report_sources(replace(report, files=(record,)))
    assert verified.complete


def test_direct_export_catches_source_change_during_report_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gametool.save_report_query as reports

    source = tmp_path / "source.txt"
    source.write_text("snapshot before", encoding="utf-8")
    selected = select_save_report(save_files.analyze_real_save_path(source))
    original = reports.save_report_payload
    rendered = 0

    def mutate(selection, format="json"):
        nonlocal rendered
        payload = original(selection, format)
        rendered += 1
        if rendered == 1:
            source.write_text("source changed after rendering", encoding="utf-8")
        return payload

    monkeypatch.setattr(reports, "save_report_payload", mutate)
    output = tmp_path / "report.json"
    result = reports.write_save_report(selected, output)
    assert result.status is SafeWriteStatus.WRITTEN
    assert not result.selection.report.complete
    value = json.loads(output.read_text(encoding="utf-8"))
    assert not value["complete"] and value["files"] == []
    assert value["unverified_files"][0]["raw_text"] == "snapshot before"
    assert source.read_text(encoding="utf-8") == "source changed after rendering"

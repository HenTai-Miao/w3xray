"""The offline public workflow preserves sources and complete records."""

import csv
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from gametool.batch_tsv import decode_tsv_cell
from gametool.loadout_cli import run_loadout_cli
from gametool import loadout_cli
from gametool import loadout_report
from gametool.loadout_report import (
    read_loadout_report,
    select_loadout_report,
    write_loadout_export,
)


def _plan():
    return {
        "schema": 1,
        "codes": ["I001", "I002", "I003", "I004", "I005", "I001"],
        "extension": "=SUM(1,2)\tline\nfull",
    }


def _source(tmp_path: Path) -> tuple[Path, bytes]:
    path = tmp_path / "six-artifacts.json"
    raw = json.dumps(_plan(), ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return path, raw


def _identity(path: Path):
    info = path.stat()
    return (
        path.read_bytes(),
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def test_cli_reads_explicit_file_and_exports_complete_json_without_touching_source(
    tmp_path, capsys
):
    source, raw = _source(tmp_path)
    before = _identity(source)
    output = tmp_path / "report.json"
    assert run_loadout_cli([str(source), "--json", "--export", str(output)]) == 0
    stdout = json.loads(capsys.readouterr().out)
    exported = json.loads(output.read_text(encoding="utf-8"))
    assert stdout == exported
    assert exported["document"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert exported["document"]["raw_text"] == raw.decode()
    assert [
        slot["code"] for slot in exported["document"]["records"][0]["slots"]
    ] == _plan()["codes"]
    assert _identity(source) == before
    assert not tuple(tmp_path.glob(".gamexray-loadout-*"))


@pytest.mark.parametrize("format", ["json", "md", "tsv"])
def test_all_export_formats_keep_unknown_extensions_and_original_json(tmp_path, format):
    source, raw = _source(tmp_path)
    selection = select_loadout_report(read_loadout_report(source))
    output = write_loadout_export(tmp_path / ("report." + format), selection, format)
    content = output.read_text(encoding="utf-8")
    if format == "tsv":
        rows = [
            [decode_tsv_cell(cell) for cell in row]
            for row in csv.reader(io.StringIO(content), delimiter="\t")
        ]
        payload = json.loads(rows[-1][-1])
        assert payload["document"]["raw_text"] == raw.decode()
        assert sum(row[0] == "slot" for row in rows) == 6
    else:
        assert "SUM(1,2)" in content
        assert "raw_base64" in content
    assert source.read_bytes() == raw


def test_query_selects_whole_record_and_keeps_diagnostics_and_full_source(tmp_path):
    def row(name, code):
        return {
            "name": name,
            "unit_type_id": 0,
            "equipment": [[int.from_bytes(code.encode(), "big"), 1]] * 9,
            "equipment_charges": [2] * 9,
            "requires_any_slot": False,
            "extension": "rare evidence",
        }

    source = tmp_path / "loadouts.json"
    value = {"schema": 1, "records": [row("one", "I001"), row("two", "I002")]}
    source.write_text(json.dumps(value), encoding="utf-8")
    selected = select_loadout_report(read_loadout_report(source), "one && evidence")
    assert len(selected.records) == 1
    assert len(selected.records[0].slots) == 9
    assert len(selected.report.document.records) == 2
    assert len(selected.report.document.diagnostics) == 2


def test_root_extension_search_keeps_whole_artifact_plan_without_cross_record_hits(
    tmp_path,
):
    source, _raw = _source(tmp_path)
    report = read_loadout_report(source)
    selected = select_loadout_report(report, "SUM")
    assert len(selected.records) == 1
    assert len(selected.records[0].slots) == 6


def test_source_and_hardlink_alias_and_existing_report_cannot_be_overwritten(tmp_path):
    source, raw = _source(tmp_path)
    selection = select_loadout_report(read_loadout_report(source))
    alias = tmp_path / "alias.json"
    os.link(source, alias)
    for destination in (source, alias):
        with pytest.raises(ValueError, match="新文件"):
            write_loadout_export(destination, selection)
        assert source.read_bytes() == alias.read_bytes() == raw


def test_changed_source_is_rejected_even_when_length_and_mtime_are_restored(tmp_path):
    source, raw = _source(tmp_path)
    selection = select_loadout_report(read_loadout_report(source))
    original = source.stat()
    source.write_bytes(raw.replace(b"I001", b"I009"))
    os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
    with pytest.raises(ValueError, match="变化"):
        write_loadout_export(tmp_path / "report.json", selection)
    assert not (tmp_path / "report.json").exists()


def test_source_changes_during_publication_roll_back_only_owned_report(
    tmp_path, monkeypatch
):
    source, raw = _source(tmp_path)
    selection = select_loadout_report(read_loadout_report(source))
    original_link = loadout_report.os.link

    def change_after_publish(stage, destination):
        original_link(stage, destination)
        source.write_bytes(raw.replace(b"I002", b"I009"))

    monkeypatch.setattr(loadout_report.os, "link", change_after_publish)
    output = tmp_path / "report.json"
    with pytest.raises(ValueError, match="变化"):
        write_loadout_export(output, selection)
    assert not output.exists()
    assert not tuple(tmp_path.glob(".gamexray-loadout-*"))
    assert source.read_bytes() == raw.replace(b"I002", b"I009")


def test_cli_partial_nonplan_and_missing_input_are_distinct_json_results(
    tmp_path, capsys
):
    source = tmp_path / "broken-plan.json"
    source.write_text('{"schema":1,"codes":["I001"]}', encoding="utf-8")
    assert run_loadout_cli([str(source), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["document"]["status"] == "partial"
    source.write_text('{"ordinary":true}', encoding="utf-8")
    assert run_loadout_cli([str(source), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["document"]["status"] == "not-plan"
    assert run_loadout_cli([str(tmp_path / "absent.json"), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["input_error"] is True


def test_cli_source_change_after_stdout_serialization_retains_typed_full_snapshot(
    tmp_path, capsys, monkeypatch
):
    source, raw = _source(tmp_path)
    original = loadout_cli._format_stdout
    calls = 0

    def change_after_format(selection, as_json, operation_error):
        nonlocal calls
        text = original(selection, as_json, operation_error)
        calls += 1
        if calls == 1:
            source.write_bytes(raw.replace(b"I002", b"I009"))
        return text

    monkeypatch.setattr(loadout_cli, "_format_stdout", change_after_format)
    assert run_loadout_cli([str(source), "--json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["source_stable"] is False
    assert report["input_error"] is False
    assert report["exit_code"] == 2
    assert report["source_diagnostics"]
    assert report["document"]["raw_text"] == raw.decode()
    assert report["document"]["records"][0]["slots"][1]["code"] == "I002"
    assert calls == 2


def test_cli_export_failure_retains_captured_records_and_original_destination(
    tmp_path, capsys
):
    source, raw = _source(tmp_path)
    assert run_loadout_cli([str(source), "--json", "--export", str(source)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["input_error"] is True
    assert report["operation_diagnostics"]
    assert report["document"]["raw_text"] == raw.decode()
    assert len(report["document"]["records"][0]["slots"]) == 6
    assert source.read_bytes() == raw

"""Offline source spelling and complete report publication on real Windows files."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from gametool import live_report_io
from gametool.live_report import (
    LiveReportError,
    compare_live_reports,
    read_live_report,
    write_live_report,
)
from gametool.local_id_tables import load_local_id_tables
from gametool.real_save_files import analyze_real_save_path
from gametool.save_source_paths import iter_save_source_files, save_source_path_error
from gametool.windows_output_paths import native_output_path


@pytest.mark.parametrize("suffix", [".", " "])
def test_live_report_rejects_raw_win32_alias_before_normalizing(tmp_path, suffix):
    source = tmp_path / "report.json"
    original = b'{"slots":[]}'
    source.write_bytes(original)
    with pytest.raises(LiveReportError, match="Invalid report path"):
        read_live_report(str(source) + suffix)
    destination = str(tmp_path / "new.json") + suffix
    with pytest.raises(LiveReportError, match="Invalid report path"):
        live_report_io.write_report_bytes(destination, b"report")
    assert source.read_bytes() == original
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("suffix", [".", " "])
def test_save_and_id_table_sources_reject_raw_directory_aliases(tmp_path, suffix):
    folder = tmp_path / "inputs"
    folder.mkdir()
    source = folder / "save.txt"
    source.write_bytes(b"-load synthetic-code")
    table = folder / "\u7269\u54c1ID.txt"
    table.write_text(
        "ID\uff1aI001\n\u540d\u5b57\uff1aSword\n\u63cf\u8ff0\uff1aFull\n",
        encoding="utf-8",
    )
    unsafe = Path(str(folder) + suffix)
    files, notes = iter_save_source_files(unsafe)
    assert not files and notes
    assert save_source_path_error(unsafe)
    report = analyze_real_save_path(unsafe)
    assert not report.files and not report.complete and report.warnings
    catalog = load_local_id_tables((unsafe,))
    assert not catalog.records and catalog.diagnostics
    assert source.read_bytes() == b"-load synthetic-code"


def test_extended_source_spelling_is_checked_before_path_construction(tmp_path, capsys):
    from gametool.real_save_cli import run_real_save_cli
    from gametool.save_code_cli import run_save_code_cli

    source = tmp_path / "source.txt"
    original = b"-load original-code"
    source.write_bytes(original)
    raw = "\\\\?\\" + str(tmp_path) + "/source.txt"
    assert save_source_path_error(raw)
    report = analyze_real_save_path(raw)
    assert not report.files and not report.complete
    assert report.source == raw
    assert load_local_id_tables((raw,)).diagnostics
    assert run_save_code_cli((raw, "--json")) == 2
    assert "original-code" not in capsys.readouterr().out
    output = tmp_path / "inspection.json"
    assert (
        run_real_save_cli(("--save", raw, "--output", str(output), "--format", "json"))
        == 2
    )
    assert "original-code" not in output.read_text(encoding="utf-8")
    assert source.read_bytes() == original


@pytest.mark.parametrize("phase", ["stage", "published", "directory-sync"])
def test_report_publication_rechecks_payload_and_removes_only_owned_failure(
    tmp_path, monkeypatch, phase
):
    target = tmp_path / "report.json"
    payload = b'{"slots":[],"notes":["complete original report"]}'
    replacement = b"X" * len(payload)
    if phase == "stage":
        real_sync = live_report_io.sync_file_descriptor

        def mutate_stage(descriptor):
            real_sync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.write(descriptor, replacement)

        monkeypatch.setattr(live_report_io, "sync_file_descriptor", mutate_stage)
    elif phase == "published":
        real_link = live_report_io.os.link

        def mutate_published(source, destination, **kwargs):
            real_link(source, destination, **kwargs)
            Path(destination).write_bytes(replacement)

        monkeypatch.setattr(live_report_io.os, "link", mutate_published)
    else:
        real_sync_directory = live_report_io.sync_directory

        def mutate_after_sync(directory):
            real_sync_directory(directory)
            target.write_bytes(replacement)

        monkeypatch.setattr(live_report_io, "sync_directory", mutate_after_sync)
    with pytest.raises(LiveReportError):
        live_report_io.write_report_bytes(target, payload)
    assert list(tmp_path.iterdir()) == []


def test_report_verification_compares_complete_bytes_not_only_metadata(
    tmp_path, monkeypatch
):
    source = tmp_path / "report.json"
    original = b'{"slots":[],"extra":"old"}'
    changed = b'{"slots":[],"extra":"new"}'
    source.write_bytes(original)
    _, expected = live_report_io.read_report_bytes(source)
    source.write_bytes(changed)
    real_read = live_report_io.read_report_bytes

    def restored_metadata(path):
        data, actual = real_read(path)
        # Model a same-file rewrite whose clocks were restored. Only complete
        # payload evidence can distinguish it from the original snapshot.
        actual.update(
            {key: value for key, value in expected.items() if key != "sha256"}
        )
        assert actual["sha256"] == hashlib.sha256(changed).hexdigest()
        return data, actual

    monkeypatch.setattr(live_report_io, "read_report_bytes", restored_metadata)
    with pytest.raises(LiveReportError, match="changed"):
        live_report_io.verify_report_source(expected)
    assert source.read_bytes() == changed


def test_report_long_paths_use_native_io_and_keep_logical_provenance(tmp_path):
    folder = tmp_path.joinpath(*("directory-" + "x" * 75 for _ in range(3)))
    Path(native_output_path(str(folder))).mkdir(parents=True)
    target = folder / "report.json"
    assert len(str(target)) > 260
    data = b'{"slots":[],"notes":["full long path"]}'
    written = live_report_io.write_report_bytes(target, data)
    assert written == target
    loaded = read_live_report(target)
    assert loaded.original_bytes == data
    assert loaded.source["path"] == str(target)
    live_report_io.verify_report_source(loaded.source)
    assert all(
        not parent["path"].startswith("\\\\?\\") for parent in loaded.source["parents"]
    )


def test_resave_rechecks_imported_source_after_publication(tmp_path, monkeypatch):
    source = tmp_path / "original.json"
    source.write_bytes(b'{"slots":[],"notes":["original"]}')
    loaded = read_live_report(source)
    destination = tmp_path / "copy.json"
    real_link = live_report_io.os.link

    def mutate_source_after_link(stage, output, **kwargs):
        real_link(stage, output, **kwargs)
        source.write_bytes(b'{"slots":[],"notes":["changed"]}')

    monkeypatch.setattr(live_report_io.os, "link", mutate_source_after_link)
    with pytest.raises(LiveReportError, match="changed"):
        write_live_report(destination, loaded)
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == [source]
    assert b"changed" in source.read_bytes()


def test_comparison_rechecks_sources_after_full_analysis(tmp_path, monkeypatch):
    from gametool import live_report_diff

    source = tmp_path / "report.json"
    source.write_bytes(b'{"slots":[],"notes":["original"]}')
    report = read_live_report(source)
    real_compare = live_report_diff.compare_report_values

    def mutate_during_compare(*args, **kwargs):
        result = real_compare(*args, **kwargs)
        source.write_bytes(b'{"slots":[],"notes":["changed"]}')
        return result

    monkeypatch.setattr(
        live_report_diff, "compare_report_values", mutate_during_compare
    )
    with pytest.raises(LiveReportError, match="changed"):
        compare_live_reports(report, report)


def test_cli_inspect_rechecks_source_after_output_formatting(
    tmp_path, monkeypatch, capsys
):
    from gametool import live_report_cli

    source = tmp_path / "report.json"
    source.write_bytes(b'{"slots":[],"notes":["original"]}')
    real_format = live_report_cli.format_report_json

    def mutate_after_format(value):
        output = real_format(value)
        source.write_bytes(b'{"slots":[],"notes":["changed"]}')
        return output

    monkeypatch.setattr(live_report_cli, "format_report_json", mutate_after_format)
    assert live_report_cli.run_live_report_cli(["inspect", str(source), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "changed" in captured.err

"""Shared publication proofs retain payload and ownership race protections."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from gametool import loadout_report, windows_output_paths
from gametool.loadout_report import (
    read_loadout_report,
    select_loadout_report,
    write_loadout_export,
)
from gametool.report_file_proof import report_metadata, require_report_payload


def _source(tmp_path):
    path = tmp_path / "source.json"
    path.write_text('{"schema":1,"records":[]}', encoding="utf-8")
    return path


def _selection(tmp_path):
    return select_loadout_report(read_loadout_report(_source(tmp_path)))


def test_new_export_keeps_complete_source_and_never_overwrites_existing_reports(
    tmp_path,
):
    source = _source(tmp_path)
    before = source.read_bytes(), report_metadata(source.stat())
    selection = select_loadout_report(read_loadout_report(source))
    report = tmp_path / "report.json"
    write_loadout_export(report, selection)
    published = report.read_bytes()
    payload = json.loads(published)
    assert payload["document"]["raw_text"] == before[0].decode()
    assert payload["document"]["sha256"] == hashlib.sha256(before[0]).hexdigest()
    for destination in (source, report):
        with pytest.raises(ValueError, match="新文件"):
            write_loadout_export(destination, selection)
    assert report.read_bytes() == published
    assert (source.read_bytes(), report_metadata(source.stat())) == before
    assert not list(tmp_path.glob(".gamexray-loadout-*.tmp"))


def test_atomic_new_publication_keeps_concurrent_destination(tmp_path, monkeypatch):
    selection = _selection(tmp_path)
    report = tmp_path / "report.json"
    original_link = os.link

    def concurrent_destination(stage, destination):
        report.write_bytes(b"CONCURRENT")
        original_link(stage, destination)

    monkeypatch.setattr(os, "link", concurrent_destination)
    with pytest.raises(FileExistsError):
        write_loadout_export(report, selection)
    assert report.read_bytes() == b"CONCURRENT"
    assert not list(tmp_path.glob(".gamexray-loadout-*.tmp"))


def test_in_place_stage_mutation_with_restored_mtime_never_publishes_success(
    tmp_path, monkeypatch
):
    selection = _selection(tmp_path)
    report = tmp_path / "report.json"
    original_link = os.link

    def mutate_payload(stage, destination):
        path = Path(stage)
        before = path.stat()
        payload = path.read_bytes()
        path.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert (path.stat().st_dev, path.stat().st_ino) == (
            before.st_dev,
            before.st_ino,
        )
        original_link(stage, destination)

    monkeypatch.setattr(os, "link", mutate_payload)
    with pytest.raises(OSError, match="payload"):
        write_loadout_export(report, selection)
    assert not report.exists()
    assert not list(tmp_path.glob(".gamexray-loadout-*.tmp"))


def test_cleanup_uses_owned_handle_and_retains_a_replaced_stage_name(
    tmp_path, monkeypatch
):
    selection = _selection(tmp_path)
    report = tmp_path / "report.json"
    original_cleanup = windows_output_paths.remove_owned_output
    replacements = []

    def replace_before_native_cleanup(path, expected):
        candidate = Path(path)
        if candidate.name.startswith(".gamexray-loadout-") and not replacements:
            assert original_cleanup(path, expected)
            candidate.write_bytes(b"CONCURRENT-REPLACEMENT\n")
            replacements.append(candidate)
        return original_cleanup(path, expected)

    monkeypatch.setattr(
        windows_output_paths, "remove_owned_output", replace_before_native_cleanup
    )
    with pytest.raises(OSError, match="保留恢复路径"):
        write_loadout_export(report, selection)
    assert len(replacements) == 1
    assert replacements[0].read_bytes() == b"CONCURRENT-REPLACEMENT\n"
    assert (
        json.loads(report.read_text(encoding="utf-8"))["report_type"]
        == "offline-loadout-inspection"
    )


def test_published_foreign_file_is_preserved_when_final_proof_fails(
    tmp_path, monkeypatch
):
    selection = _selection(tmp_path)
    report = tmp_path / "report.json"
    original_link = os.link

    def replace_published_output(stage, destination):
        original_link(stage, destination)
        report.unlink()
        report.write_bytes(b"FOREIGN-CREATOR\n")

    monkeypatch.setattr(os, "link", replace_published_output)
    with pytest.raises(OSError, match="保留恢复路径"):
        write_loadout_export(report, selection)
    assert report.read_bytes() == b"FOREIGN-CREATOR\n"
    assert not list(tmp_path.glob(".gamexray-loadout-*.tmp"))


@pytest.mark.parametrize(
    "path",
    (
        r"\\?\C:\review\folder.\source.json",
        r"\\?\C:\review\folder\..\source.json",
        r"\\?\C:\review/folder/source.json",
    ),
)
def test_ambiguous_extended_source_is_rejected_before_reading(path, monkeypatch):
    reads = []

    def unexpected_read(source):
        reads.append(source)
        raise AssertionError("An ambiguous source must not reach filesystem reads")

    monkeypatch.setattr(loadout_report, "read_report_bytes", unexpected_read)
    with pytest.raises(ValueError):
        read_loadout_report(path)
    assert reads == []


def test_long_source_and_new_output_use_native_io_without_changing_report_paths(
    tmp_path,
):
    directory = tmp_path.joinpath(*("segment" + str(i) + "x" * 55 for i in range(5)))
    Path(windows_output_paths.native_output_path(str(directory))).mkdir(parents=True)
    short_source = _source(tmp_path)
    long_source = directory / "source.json"
    Path(windows_output_paths.native_output_path(str(long_source))).write_bytes(
        short_source.read_bytes()
    )
    selection = select_loadout_report(read_loadout_report(long_source))
    assert selection.report.exit_code == 0
    report = directory / "report.json"
    write_loadout_export(report, selection)
    payload = json.loads(
        Path(windows_output_paths.native_output_path(str(report))).read_text(
            encoding="utf-8"
        )
    )
    assert payload["source_metadata"]["path"] == str(long_source)
    assert payload["document"]["source"] == str(long_source)
    assert payload["document"]["sha256"] == selection.report.document.sha256


def test_failed_link_keeps_a_concurrently_claimed_destination_even_with_same_file_id(
    tmp_path, monkeypatch
):
    selection = _selection(tmp_path)
    report = tmp_path / "report.json"
    original_link = os.link
    claimed = []

    def concurrent_name_then_our_failure(stage, destination):
        original_link(stage, destination)
        stage_stat, destination_stat = os.lstat(stage), os.lstat(destination)
        assert (stage_stat.st_dev, stage_stat.st_ino) == (
            destination_stat.st_dev,
            destination_stat.st_ino,
        )
        claimed.append(Path(destination).read_bytes())
        original_link(stage, destination)

    monkeypatch.setattr(os, "link", concurrent_name_then_our_failure)
    with pytest.raises(FileExistsError):
        write_loadout_export(report, selection)
    assert len(claimed) == 1
    assert report.read_bytes() == claimed[0]
    assert (
        json.loads(report.read_text(encoding="utf-8"))["report_type"]
        == "offline-loadout-inspection"
    )
    assert not list(tmp_path.glob(".gamexray-loadout-*.tmp"))


def test_payload_proof_checks_every_chunk_and_rejects_a_changed_final_byte(tmp_path):
    path = tmp_path / "report.bin"
    payload = b"evidence" * (256 * 1024) + b"!"
    path.write_bytes(payload)
    with path.open("r+b") as stream:
        descriptor = stream.fileno()
        metadata = report_metadata(os.fstat(descriptor))
        digest = hashlib.sha256(payload).hexdigest()
        held, named = require_report_payload(str(path), descriptor, metadata, digest)
        assert held == metadata
        assert named == report_metadata(path.lstat())
        assert held[:4] + held[5:] == named[:4] + named[5:]
        stream.seek(-1, os.SEEK_END)
        stream.write(b"?")
        stream.flush()
        os.fsync(descriptor)
        before = report_metadata(os.fstat(descriptor))
        with pytest.raises(OSError, match="payload"):
            require_report_payload(str(path), descriptor, before, digest)

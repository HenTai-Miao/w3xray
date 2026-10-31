"""Independent synthetic acceptance of offline War3Tools evidence delivery."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest

from gametool.war3tools_config import (
    inspect_war3tools_config,
    revalidate_war3tools_inspection,
)
from gametool.war3tools_config_cli import run_war3tools_cli
from gametool.war3tools_config_report import (
    format_war3tools_report,
    select_war3tools_report,
    war3tools_report_to_dict,
    write_war3tools_export,
)


def _write(path: Path, raw: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _assert_retained_files(checked, original):
    assert len(checked.files) == len(original.files)
    for current, previous in zip(checked.files, original.files, strict=True):
        assert current.records == previous.records
        assert current.settings == previous.settings
        for attribute in (
            "path",
            "relative_path",
            "sha256",
            "size",
            "identity",
            "raw_base64",
            "raw_text",
            "encoding",
            "requested_encoding",
            "bom_bytes",
        ):
            assert getattr(current.source, attribute) == getattr(
                previous.source, attribute
            )
        assert set(previous.diagnostics) <= set(current.diagnostics)


def test_recursive_same_name_ini_keeps_each_scope_and_complete_bytes(tmp_path):
    root = tmp_path / "inputs"
    payloads = {
        "first/Features.ini": b"[Features]\r\nExtendedChatInput=1\r\n",
        "second/Features.INI": b"[Features]\nExtendedChatInput=0\n",
        "second/nested/Extra.ini": b"[Extension]\nUnknown=all fields kept\n",
    }
    for name, raw in payloads.items():
        _write(root / name, raw)
    _write(root / "readme.txt", b"inventory only")
    _write(root / "unexecuted.mix", b"not an executable fixture")

    result = inspect_war3tools_config(root)

    assert result.inventory_complete
    assert result.stable
    assert len(result.files) == 3
    by_name = {
        file.source.relative_path.replace("\\", "/"): file for file in result.files
    }
    assert set(by_name) == set(payloads)
    for name, raw in payloads.items():
        source = by_name[name].source
        assert base64.b64decode(source.raw_base64) == raw
        assert source.sha256 == hashlib.sha256(raw).hexdigest()
        assert source.size == len(raw)
        assert "".join(row.raw for row in by_name[name].records).encode("utf-8") == raw
    inventory = {entry.relative_path.replace("\\", "/") for entry in result.inventory}
    assert set(payloads) <= inventory
    assert {"readme.txt", "unexecuted.mix"} <= inventory
    assert result.runtime_verified is False


@pytest.mark.parametrize(
    ("encoding", "marker"),
    (
        ("utf-8", b"\xef\xbb\xbf"),
        ("utf-16-le", b"\xff\xfe"),
        ("utf-16-be", b"\xfe\xff"),
    ),
)
def test_physical_lines_cover_bom_multibyte_duplicates_empty_values_and_endings(
    tmp_path, encoding, marker
):
    text = "[Features]\r\nExtendedChatInput=1\nExtendedChatInput=\r;说明\r\n[Features]\nUnknown=保留;不是注释"
    raw = marker + text.encode(encoding)
    path = _write(tmp_path / "Features.ini", raw)

    result = inspect_war3tools_config(path)
    file = result.files[0]

    assert base64.b64decode(file.source.raw_base64) == raw
    assert file.source.raw_text == text
    assert "".join(row.raw for row in file.records) == text
    position = len(marker)
    for row in file.records:
        assert row.byte_offset == position
        position += len(row.raw.encode(encoding))
        assert row.byte_end == position
        assert raw[row.byte_offset : row.byte_end].decode(encoding) == row.raw
    assert position == len(raw)
    keys = [row for row in file.records if row.key == "ExtendedChatInput"]
    assert [row.value for row in keys] == ["1", ""]
    unknown = [row for row in file.records if row.key == "Unknown"]
    assert unknown[0].value == "保留;不是注释"
    assert unknown[0].section_occurrence != keys[0].section_occurrence
    assert result.diagnostics


def test_legacy_text_requires_explicit_encoding_and_retains_original_bytes(tmp_path):
    raw = "[Features]\r\nUnknown=中文\r\n".encode("gb18030")
    path = _write(tmp_path / "Features.ini", raw)

    undecoded = inspect_war3tools_config(path)
    decoded = inspect_war3tools_config(path, text_encoding="gb18030")

    assert undecoded.exit_code == 2
    assert not undecoded.inspection_complete
    assert undecoded.diagnostics
    assert base64.b64decode(undecoded.files[0].source.raw_base64) == raw
    assert decoded.files[0].source.raw_text == raw.decode("gb18030")
    assert decoded.files[0].source.encoding == "gb18030"
    assert decoded.stable


def test_bom_conflict_and_bomless_utf16_are_diagnostic_not_guessed(tmp_path):
    text = "[Features]\nExtendedChatInput=1\n"
    path = _write(tmp_path / "Features.ini", text.encode("utf-16-le"))

    automatic = inspect_war3tools_config(path)
    explicit = inspect_war3tools_config(path, text_encoding="utf-16-le")

    assert automatic.exit_code == 2
    assert not automatic.inspection_complete
    assert explicit.files[0].source.raw_text == text
    _write(path, b"\xff\xfe" + text.encode("utf-16-le"))
    conflict = inspect_war3tools_config(path, text_encoding="utf-8")
    assert conflict.exit_code == 2
    assert conflict.files[0].source.raw_text is None
    assert base64.b64decode(conflict.files[0].source.raw_base64) == path.read_bytes()


def test_revalidation_rejects_same_length_restored_mtime_change_and_keeps_snapshot(
    tmp_path,
):
    raw = b"[Features]\nExtendedChatInput=1\n"
    path = _write(tmp_path / "Features.ini", raw)
    original = inspect_war3tools_config(path)
    metadata = path.stat()
    path.write_bytes(raw.replace(b"=1", b"=0"))
    os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))

    checked = revalidate_war3tools_inspection(original)

    assert checked.exit_code == 2
    assert not checked.stable
    assert checked.diagnostics
    _assert_retained_files(checked, original)
    assert base64.b64decode(checked.files[0].source.raw_base64) == raw
    assert original.stable, original.diagnostics


@pytest.mark.parametrize("mutation", ("add_ini", "add_other", "remove", "rename"))
def test_revalidation_covers_complete_recursive_inventory(tmp_path, mutation):
    root = tmp_path / "inputs"
    path = _write(
        root / "nested" / "Features.ini", b"[Features]\nExtendedChatInput=1\n"
    )
    original = inspect_war3tools_config(root)
    assert original.stable, original.diagnostics
    if mutation == "add_ini":
        _write(root / "nested" / "new.ini", b"[Extension]\nKey=value\n")
    elif mutation == "add_other":
        _write(root / "nested" / "new.bin", b"inventory only")
    elif mutation == "remove":
        path.unlink()
    else:
        path.rename(path.with_name("renamed.ini"))

    checked = revalidate_war3tools_inspection(original)

    assert checked.exit_code == 2
    assert not checked.stable
    _assert_retained_files(checked, original)
    assert checked.inventory == original.inventory
    assert checked.diagnostics


def test_binding_conflict_keeps_all_declarations_without_runtime_certainty(tmp_path):
    path = _write(
        tmp_path / "KeyMapping.ini",
        b"[Conversion]\nConversionEnabled=1\nSkillKey01=81\nSkillSlot01=0\nSkillRepeat01=0\nSkillKey02=81\nSkillSlot02=0\nSkillRepeat02=0\n",
    )

    result = inspect_war3tools_config(path)

    assert [binding.key_code for binding in result.bindings] == [81, 81]
    assert result.conflicts
    assert all(not binding.activation_proven for binding in result.bindings)
    assert result.runtime_verified is False
    assert all(conflict.state == "potential" for conflict in result.conflicts)
    assert (
        "".join(row.raw for row in result.files[0].records).encode()
        == path.read_bytes()
    )


def test_zero_match_query_keeps_complete_diagnostics_and_each_original_source(tmp_path):
    path = _write(
        tmp_path / "Features.ini",
        b"[Features]\nExtendedChatInput=1\nExtendedChatInput=0\nbroken declaration\n",
    )
    inspection = inspect_war3tools_config(path)
    selection = select_war3tools_report(inspection, "definitely absent token")

    report = war3tools_report_to_dict(selection)
    text = format_war3tools_report(selection)

    assert not selection.records
    assert inspection.diagnostics
    selected = report["selection"]
    assert isinstance(selected, dict)
    assert selected["matched_records"] == 0
    assert report["diagnostics"] == inspection.to_dict()["diagnostics"]
    assert report["files"] == inspection.to_dict()["files"]
    assert "broken declaration" in text
    assert "清空查询" in text
    for diagnostic in inspection.diagnostics:
        assert diagnostic.code in text


@pytest.mark.parametrize("format", ("json", "md", "tsv"))
def test_each_export_keeps_full_source_bytes_even_when_query_has_no_match(
    tmp_path, format
):
    raw = b"\xef\xbb\xbf[Features]\r\nExtendedChatInput=1\r\n"
    path = _write(tmp_path / "Features.ini", raw)
    before = path.stat()
    selection = select_war3tools_report(inspect_war3tools_config(path), "no such token")
    destination = tmp_path / ("report." + format)

    assert write_war3tools_export(destination, selection, format) == destination

    text = destination.read_text(encoding="utf-8")
    assert base64.b64encode(raw).decode() in text
    assert path.read_bytes() == raw
    after = path.stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


def test_export_rejects_source_existing_file_and_hardlink_without_mutating_them(
    tmp_path,
):
    raw = b"[Features]\nExtendedChatInput=1\n"
    path = _write(tmp_path / "Features.ini", raw)
    alias = tmp_path / "source-alias.json"
    os.link(path, alias)
    existing = _write(tmp_path / "existing.json", b"original report")
    selection = select_war3tools_report(inspect_war3tools_config(path))

    for destination in (path, alias, existing):
        before = destination.read_bytes()
        with pytest.raises((OSError, ValueError)):
            write_war3tools_export(destination, selection)
        assert destination.read_bytes() == before
    assert path.read_bytes() == alias.read_bytes() == raw


def test_directory_export_rejects_inside_tree_before_changing_any_inventory(tmp_path):
    root = tmp_path / "inputs"
    path = _write(
        root / "nested" / "Features.ini", b"[Features]\nExtendedChatInput=1\n"
    )
    selection = select_war3tools_report(inspect_war3tools_config(root))
    identities = {
        candidate: candidate.stat() for candidate in (root, root / "nested", path)
    }

    for destination in (root / "report.json", root / "nested" / "report.md"):
        with pytest.raises((OSError, ValueError)):
            write_war3tools_export(destination, selection)
        assert not destination.exists()
    for candidate, before in identities.items():
        after = candidate.stat()
        assert (
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) == (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
    checked = revalidate_war3tools_inspection(selection.inspection)
    assert checked.stable, checked.diagnostics


@pytest.mark.parametrize("inventory_change", (False, True))
def test_cli_final_source_proof_runs_after_serialization_even_with_zero_matches(
    tmp_path, monkeypatch, capsys, inventory_change
):
    import gametool.war3tools_config_cli as cli

    root = tmp_path / "inputs"
    raw = b"[Features]\nExtendedChatInput=1\n"
    path = _write(root / "Features.ini", raw)
    original_format = cli._format_stdout
    changed = False

    def change_after_serialization(selection, as_json, operation_error):
        nonlocal changed
        text = original_format(selection, as_json, operation_error)
        if not changed:
            changed = True
            if inventory_change:
                _write(root / "late.ini", b"[Extension]\nKey=value\n")
            else:
                path.write_bytes(raw.replace(b"=1", b"=0"))
        return text

    monkeypatch.setattr(cli, "_format_stdout", change_after_serialization)
    assert run_war3tools_cli([str(root), "--json", "--query", "absent token"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["stable"] is False
    assert result["selection"]["matched_records"] == 0
    assert result["diagnostics"]
    assert len(result["files"]) == 1
    assert base64.b64decode(result["files"][0]["source"]["raw_base64"]) == raw


def test_export_source_change_after_publication_removes_only_owned_report(
    tmp_path, monkeypatch
):
    import gametool.war3tools_config_report as reports

    raw = b"[Features]\nExtendedChatInput=1\n"
    path = _write(tmp_path / "Features.ini", raw)
    selection = select_war3tools_report(inspect_war3tools_config(path))
    destination = tmp_path / "report.json"
    original_link = reports.os.link

    def change_after_link(stage, target):
        original_link(stage, target)
        path.write_bytes(raw.replace(b"=1", b"=0"))

    monkeypatch.setattr(reports.os, "link", change_after_link)
    with pytest.raises((OSError, ValueError)):
        write_war3tools_export(destination, selection)
    assert not destination.exists()
    assert not tuple(tmp_path.glob(".gamexray-war3tools-*"))
    assert path.read_bytes() == raw.replace(b"=1", b"=0")


def test_export_destination_race_preserves_competing_file(tmp_path, monkeypatch):
    import gametool.war3tools_config_report as reports

    path = _write(tmp_path / "Features.ini", b"[Features]\nExtendedChatInput=1\n")
    selection = select_war3tools_report(inspect_war3tools_config(path))
    destination = tmp_path / "report.json"
    original_link = reports.os.link

    def concurrent_destination(stage, target):
        Path(target).write_bytes(b"unrelated concurrent report")
        original_link(stage, target)

    monkeypatch.setattr(reports.os, "link", concurrent_destination)
    with pytest.raises((OSError, ValueError)):
        write_war3tools_export(destination, selection)
    assert destination.read_bytes() == b"unrelated concurrent report"
    assert not tuple(tmp_path.glob(".gamexray-war3tools-*"))


def test_directory_without_ini_delivers_inventory_and_diagnostics_at_zero_matches(
    tmp_path, capsys
):
    root = tmp_path / "inputs"
    raw = b"a deliberately inert inventory fixture"
    source = _write(root / "plugin.mix", raw)

    assert run_war3tools_cli([str(root), "--json", "--query", "absent token"]) == 2

    report = json.loads(capsys.readouterr().out)
    assert report["input_error"] is True
    assert report["inspection_complete"] is False
    assert report["files"] == []
    assert report["selection"]["matched_records"] == 0
    assert any(row["relative_path"] == "plugin.mix" for row in report["inventory"])
    assert any(note["code"] == "no-ini-files" for note in report["diagnostics"])
    assert source.read_bytes() == raw


def test_missing_source_is_typed_failure_with_recovery_and_no_created_output(
    tmp_path, capsys
):
    source = tmp_path / "missing.ini"
    destination = tmp_path / "report.json"

    assert (
        run_war3tools_cli(
            [
                str(source),
                "--json",
                "--query",
                "absent token",
                "--export",
                str(destination),
            ]
        )
        == 2
    )

    report = json.loads(capsys.readouterr().out)
    assert report["input_error"] is True
    assert report["stable"] is False
    assert report["files"] == []
    assert report["diagnostics"] and report["operation_diagnostics"]
    assert not destination.exists()

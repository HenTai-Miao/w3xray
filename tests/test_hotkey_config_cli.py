"""CLI exports operate only on explicit synthetic input and new report paths."""

from __future__ import annotations

import json
import os

import pytest

from gametool import hotkey_config_cli, windows_output_paths
from gametool.hotkey_config import inspect_hotkey_config
from gametool.hotkey_config_cli import (
    format_hotkey_result,
    run_hotkeys_cli,
    write_hotkey_export,
)


def source(tmp_path, name="config.json"):
    path = tmp_path / name
    path.write_text(
        '{"language":"auto","active_profile":"One","profiles":{"One":{"bindings":[{"binding_id":"ability_1","source":"M","target":"M","slot_index":0,"group":"ability"}]}}}',
        encoding="utf-8",
    )
    return path


def test_cli_inspect_json_and_profile_selector(tmp_path, capsys):
    path = source(tmp_path)
    assert run_hotkeys_cli(["inspect", str(path), "--profile", "One", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["report_type"] == "hotkeys_inspection"
    assert report["report_is_configuration"] is False
    assert report["source"]["path"] == str(path)
    assert report["runtime_verified"] is False
    assert len(report["profiles"][0]["compatibility_bindings"]) == 42


def test_cli_diff_status_distinguishes_same_changed_and_unreadable(tmp_path, capsys):
    old = source(tmp_path, "old.json")
    new = source(tmp_path, "new.json")
    assert run_hotkeys_cli(["diff", str(old), str(new), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["comparison_complete"]
    new.write_text(
        new.read_text(encoding="utf-8").replace('"language":"auto"', '"language":"zh"'),
        encoding="utf-8",
    )
    assert run_hotkeys_cli(["diff", str(old), str(new), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["has_changes"]
    assert run_hotkeys_cli(["diff", str(tmp_path / "missing"), str(new), "--json"]) == 2
    assert not json.loads(capsys.readouterr().out)["comparison_complete"]


def test_report_contains_full_declarations_projection_and_source(tmp_path):
    path = source(tmp_path)
    text = format_hotkey_result(inspect_hotkey_config(path))
    assert "== 原声明 ==" in text
    assert "== 原工具兼容推导 ==" in text
    assert "shop_12" in text
    assert path.read_text(encoding="utf-8") in text
    assert "96918355fd386afb7eabae8286e0a552c7dcbc81a239bc35e165fdc75529af41" in text


def test_export_new_file_is_full_and_preserves_input_and_existing_reports(tmp_path):
    path = source(tmp_path)
    before = path.read_bytes(), path.stat().st_mtime_ns
    result = inspect_hotkey_config(path)
    report = tmp_path / "report.json"
    write_hotkey_export(report, result)
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["source"]["utf8_text"] == before[0].decode()
    assert len(payload["profiles"][0]["compatibility_bindings"]) == 42
    with pytest.raises(ValueError, match="新文件"):
        write_hotkey_export(path, result)
    report_before = report.read_bytes()
    with pytest.raises(ValueError, match="新文件"):
        write_hotkey_export(report, result)
    assert report.read_bytes() == report_before
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert not list(tmp_path.glob(".gamexray-hotkeys-*.tmp"))


def test_atomic_new_publication_keeps_concurrent_destination(tmp_path, monkeypatch):
    path = source(tmp_path)
    result = inspect_hotkey_config(path)
    report = tmp_path / "report.json"
    original_link = os.link

    def concurrent_destination(stage, destination):
        report.write_bytes(b"CONCURRENT")
        original_link(stage, destination)

    monkeypatch.setattr(os, "link", concurrent_destination)
    with pytest.raises(OSError):
        write_hotkey_export(report, result)
    assert report.read_bytes() == b"CONCURRENT"
    assert not list(tmp_path.glob(".gamexray-hotkeys-*.tmp"))


def test_source_changed_before_export_is_nonzero_and_no_report(tmp_path):
    path = source(tmp_path)
    result = inspect_hotkey_config(path)
    path.write_bytes(path.read_bytes() + b" ")
    report = tmp_path / "report.json"
    with pytest.raises(ValueError, match="源文件已变化"):
        write_hotkey_export(report, result)
    assert not report.exists()


def test_cli_cannot_overwrite_config_via_output(tmp_path, capsys):
    path = source(tmp_path)
    original = path.read_bytes()
    assert run_hotkeys_cli(["inspect", str(path), "--output", str(path)]) == 2
    assert path.read_bytes() == original
    assert "新文件" in capsys.readouterr().err


def test_export_failed_parse_keeps_raw_bytes_as_diagnostic_report(tmp_path):
    path = tmp_path / "broken.json"
    path.write_bytes(b"\xffNOTJSON")
    result = inspect_hotkey_config(path)
    report = tmp_path / "broken-report.json"
    write_hotkey_export(report, result)
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["exit_code"] == 2
    assert payload["source"]["raw_base64"]


def test_cli_export_json_suffix_and_text_stdout_are_independent(tmp_path, capsys):
    path = source(tmp_path)
    report = tmp_path / "report.json"
    assert run_hotkeys_cli(["inspect", str(path), "--output", str(report)]) == 0
    assert capsys.readouterr().out.startswith("GameXRay")
    assert (
        json.loads(report.read_text(encoding="utf-8"))["report_type"]
        == "hotkeys_inspection"
    )


def test_in_place_stage_mutation_with_restored_mtime_never_publishes_success(
    tmp_path, monkeypatch
):
    result = inspect_hotkey_config(source(tmp_path))
    report = tmp_path / "report.json"
    original_link = os.link

    def mutate_payload(stage, destination):
        path = hotkey_config_cli.Path(stage)
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
        write_hotkey_export(report, result)
    assert not report.exists()
    assert not list(tmp_path.glob(".gamexray-hotkeys-*.tmp"))


def test_cleanup_uses_owned_handle_and_retains_a_replaced_stage_name(
    tmp_path, monkeypatch
):
    result = inspect_hotkey_config(source(tmp_path))
    report = tmp_path / "report.json"
    original_cleanup = windows_output_paths.remove_owned_output
    replacements = []

    def replace_before_native_cleanup(path, expected):
        candidate = hotkey_config_cli.Path(path)
        if candidate.name.startswith(".gamexray-hotkeys-") and not replacements:
            assert original_cleanup(path, expected)
            candidate.write_bytes(b"CONCURRENT-REPLACEMENT\n")
            replacements.append(candidate)
        return original_cleanup(path, expected)

    monkeypatch.setattr(
        windows_output_paths, "remove_owned_output", replace_before_native_cleanup
    )
    with pytest.raises(OSError, match="保留恢复路径"):
        write_hotkey_export(report, result)
    assert len(replacements) == 1
    assert replacements[0].read_bytes() == b"CONCURRENT-REPLACEMENT\n"
    assert (
        json.loads(report.read_text(encoding="utf-8"))["report_type"]
        == "hotkeys_inspection"
    )


def test_published_foreign_file_is_preserved_when_final_proof_fails(
    tmp_path, monkeypatch
):
    result = inspect_hotkey_config(source(tmp_path))
    report = tmp_path / "report.json"
    original_link = os.link

    def claim_with_foreign_output(stage, destination):
        report.write_bytes(b"FOREIGN-CREATOR\n")
        original_link(stage, destination)

    monkeypatch.setattr(os, "link", claim_with_foreign_output)
    with pytest.raises(OSError, match="保留恢复路径"):
        write_hotkey_export(report, result)
    assert report.read_bytes() == b"FOREIGN-CREATOR\n"
    assert not list(tmp_path.glob(".gamexray-hotkeys-*.tmp"))


def test_long_source_and_new_output_use_native_io_without_changing_report_paths(
    tmp_path,
):
    directory = tmp_path.joinpath(*("segment" + str(i) + "x" * 55 for i in range(5)))
    directory_io = hotkey_config_cli.Path(
        windows_output_paths.native_output_path(str(directory))
    )
    directory_io.mkdir(parents=True)
    short_source = source(tmp_path)
    long_source = directory / "source.json"
    hotkey_config_cli.Path(
        windows_output_paths.native_output_path(str(long_source))
    ).write_bytes(short_source.read_bytes())
    result = inspect_hotkey_config(long_source)
    assert result.exit_code == 0
    report = directory / "report.json"
    write_hotkey_export(report, result)
    payload = json.loads(
        hotkey_config_cli.Path(
            windows_output_paths.native_output_path(str(report))
        ).read_text(encoding="utf-8")
    )
    assert payload["source"]["path"] == str(long_source)
    assert payload["source"]["sha256"] == result.source.sha256


def test_failed_link_keeps_a_concurrently_claimed_destination_even_with_same_file_id(
    tmp_path, monkeypatch
):
    result = inspect_hotkey_config(source(tmp_path))
    report = tmp_path / "report.json"
    real_link = os.link
    claimed = []

    def concurrent_name_then_our_failure(stage, destination):
        real_link(stage, destination)
        stage_stat, destination_stat = os.lstat(stage), os.lstat(destination)
        assert (stage_stat.st_dev, stage_stat.st_ino) == (
            destination_stat.st_dev,
            destination_stat.st_ino,
        )
        claimed.append(hotkey_config_cli.Path(destination).read_bytes())
        real_link(stage, destination)

    monkeypatch.setattr(os, "link", concurrent_name_then_our_failure)
    with pytest.raises(OSError, match="命名项"):
        write_hotkey_export(report, result)
    assert len(claimed) == 1
    assert report.read_bytes() == claimed[0]
    assert (
        json.loads(report.read_text(encoding="utf-8"))["report_type"]
        == "hotkeys_inspection"
    )
    assert not list(tmp_path.glob(".gamexray-hotkeys-*.tmp"))

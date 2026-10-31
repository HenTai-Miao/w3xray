"""Public configuration query/export contracts with independent input bytes."""

import base64
import csv
import io
import json
import os
from pathlib import Path

import pytest

from gametool import app, war3tools_config_cli, war3tools_config_report
from gametool.batch_tsv import decode_tsv_cell
from gametool.war3tools_config import inspect_war3tools_config
from gametool.war3tools_config_cli import run_war3tools_cli
from gametool.war3tools_config_report import (
    select_war3tools_report,
    write_war3tools_export,
)


def _input(tmp_path: Path) -> tuple[Path, bytes]:
    source = tmp_path / "Settings.ini"
    raw = b"\xef\xbb\xbf[Custom]\r\nName=alpha\r\nValue==SUM(1,2)\tfull\r\n"
    source.write_bytes(raw)
    return source, raw


def test_public_route_and_help(monkeypatch, tmp_path, capsys):
    assert "war3tools" in app.top_level_help()
    source, _ = _input(tmp_path)
    monkeypatch.setattr("sys.argv", ["gamexray", "war3tools", str(source), "--json"])
    with pytest.raises(SystemExit) as result:
        app.main()
    output = json.loads(capsys.readouterr().out)
    assert result.value.code == output["exit_code"]
    assert output["stable"] is True
    assert output["files_total"] == 1


@pytest.mark.parametrize("format", ["json", "md", "tsv"])
def test_exports_keep_original_bytes_and_safe_complete_cells(tmp_path, format):
    source, raw = _input(tmp_path)
    initial = source.stat()
    selection = select_war3tools_report(inspect_war3tools_config(source))
    destination = write_war3tools_export(
        tmp_path / ("report." + format), selection, format
    )
    payload = destination.read_bytes().decode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    assert encoded in payload
    if format == "tsv":
        rows = [
            [decode_tsv_cell(cell) for cell in row]
            for row in csv.reader(io.StringIO(payload), delimiter="\t")
        ]
        values = [row for row in rows if row[4] == "Value"]
        assert values[0][5] == "=SUM(1,2)\tfull"
        assert values[0][6] == "Value==SUM(1,2)\tfull\r\n"
        assert json.loads(rows[-1][-1])["files"][0]["source"]["raw_base64"] == encoded
    assert source.read_bytes() == raw
    current = source.stat()
    assert (
        initial.st_ino,
        initial.st_size,
        initial.st_mtime_ns,
        initial.st_ctime_ns,
    ) == (current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns)
    assert not tuple(tmp_path.glob(".gamexray-war3tools-*"))


def test_query_does_not_join_fields_from_different_records(tmp_path):
    source, _ = _input(tmp_path)
    inspection = inspect_war3tools_config(source)
    assert len(select_war3tools_report(inspection, "Name && alpha").records) == 1
    assert not select_war3tools_report(inspection, "Name && SUM").records
    assert len(select_war3tools_report(inspection).records) == inspection.records_total


def test_existing_source_and_hardlink_report_are_never_overwritten(tmp_path):
    source, raw = _input(tmp_path)
    alias = tmp_path / "alias.ini"
    os.link(source, alias)
    selection = select_war3tools_report(inspect_war3tools_config(source))
    for target in (source, alias):
        with pytest.raises(ValueError, match="新文件"):
            write_war3tools_export(target, selection)
        assert target.read_bytes() == raw


def test_chinese_category_query_finds_complete_cooldown_declaration(tmp_path):
    source = tmp_path / "Cooldown.ini"
    source.write_bytes(b"[Cooldown]\r\nEnabled=1\r\nMaximumDisplayedSeconds=777\r\n")
    selected = select_war3tools_report(inspect_war3tools_config(source), "冷却 && 777")
    assert len(selected.records) == 1
    assert selected.records[0].record.raw == "MaximumDisplayedSeconds=777\r\n"


def test_source_change_after_render_retains_snapshot_and_returns_two(
    tmp_path, monkeypatch, capsys
):
    source, raw = _input(tmp_path)
    original = war3tools_config_cli._format_stdout
    calls = 0

    def mutate(selection, as_json, operation_error):
        nonlocal calls
        text = original(selection, as_json, operation_error)
        calls += 1
        if calls == 1:
            source.write_bytes(raw.replace(b"alpha", b"omega"))
        return text

    monkeypatch.setattr(war3tools_config_cli, "_format_stdout", mutate)
    assert run_war3tools_cli([str(source), "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["stable"] is False
    assert base64.b64decode(result["files"][0]["source"]["raw_base64"]) == raw
    assert result["diagnostics"]
    assert calls == 2


def test_export_source_change_rolls_back_only_new_report(tmp_path, monkeypatch):
    source, raw = _input(tmp_path)
    selection = select_war3tools_report(inspect_war3tools_config(source))
    original = war3tools_config_report.os.link

    def mutate(stage, target):
        original(stage, target)
        source.write_bytes(raw.replace(b"alpha", b"omega"))

    monkeypatch.setattr(war3tools_config_report.os, "link", mutate)
    target = tmp_path / "report.json"
    with pytest.raises(ValueError, match="来源变化"):
        write_war3tools_export(target, selection)
    assert not target.exists()
    assert source.read_bytes() == raw.replace(b"alpha", b"omega")
    assert not tuple(tmp_path.glob(".gamexray-war3tools-*"))


def test_bad_export_keeps_source_snapshot_in_cli_json(tmp_path, capsys):
    source, raw = _input(tmp_path)
    assert run_war3tools_cli([str(source), "--json", "--export", str(source)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["operation_diagnostics"]
    assert base64.b64decode(result["files"][0]["source"]["raw_base64"]) == raw
    assert source.read_bytes() == raw

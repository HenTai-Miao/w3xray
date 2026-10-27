"""Offline inspect/diff CLI uses typed APIs and complete exact outputs."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json
from typing import Any

from gametool.live_report import write_live_report
from gametool.live_report_cli import run_live_report_cli


def _report() -> dict[str, Any]:
    return {
        "pid": 9,
        "process_identity": {"pid": 9, "creation_time": 100},
        "version": {"version": "1.27.0.52240", "arch": "x86"},
        "map_epoch": "fixture",
        "captured_at": "2026-10-27T10:00:00Z",
        "selected_units": [
            {
                "addr": 1000,
                "code": "H001",
                "x": Decimal("1.00000000000000000001"),
                "items": [],
                "items_complete": True,
            }
        ],
        "selection_complete": True,
        "notes": [],
    }


def test_inspect_complete_json_and_legacy_text_without_game(tmp_path, capsys):
    target = write_live_report(tmp_path / "report.json", _report())
    assert run_live_report_cli(["inspect", str(target), "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out, parse_float=Decimal)
    assert parsed["report"]["selected_units"][0]["x"] == Decimal(
        "1.00000000000000000001"
    )
    assert parsed["source"]["size"] == target.stat().st_size
    assert parsed["document"]["provenance"]["capture"]["pid"] == 9
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        '{"selected_unit":null,"notes":["完整未知原因"]}', encoding="utf-8"
    )
    assert run_live_report_cli(["inspect", str(legacy)]) == 0
    assert "完整未知原因" in capsys.readouterr().out


def test_diff_json_complete_changed_and_uncertain_exit_codes(tmp_path, capsys):
    old_report = _report()
    new_report = deepcopy(old_report)
    old = write_live_report(tmp_path / "old.json", old_report)
    same = write_live_report(tmp_path / "same.json", new_report)
    assert run_live_report_cli(["diff", str(old), str(same), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["has_changes"] is False
    new_report["selected_units"][0]["x"] = Decimal("1.00000000000000000002")
    changed = write_live_report(tmp_path / "changed.json", new_report)
    output = tmp_path / "diff.json"
    assert (
        run_live_report_cli(
            ["diff", str(old), str(changed), "--json", "--output", str(output)]
        )
        == 1
    )
    text = capsys.readouterr().out
    assert text == output.read_text(encoding="utf-8")
    assert "1.00000000000000000002" in text
    del new_report["map_epoch"]
    partial = write_live_report(tmp_path / "partial.json", new_report)
    assert run_live_report_cli(["diff", str(old), str(partial)]) == 2
    assert "身份或覆盖范围不确定" in capsys.readouterr().out


def test_cli_help_errors_and_existing_output_preserve_assets(tmp_path, capsys):
    assert run_live_report_cli(["--help"]) == 0
    assert "inspect" in capsys.readouterr().out
    assert run_live_report_cli(["diff", "only-one-file"]) == 2
    assert "required" in capsys.readouterr().err
    assert run_live_report_cli(["inspect", str(tmp_path / "missing.json")]) == 2
    assert "离线实时报告错误" in capsys.readouterr().err
    old = write_live_report(tmp_path / "old.json", _report())
    output = tmp_path / "user.txt"
    output.write_bytes(b"user asset")
    assert (
        run_live_report_cli(["diff", str(old), str(old), "--output", str(output)]) == 2
    )
    assert "exists" in capsys.readouterr().err
    assert output.read_bytes() == b"user asset"


def test_unsupported_large_schema_values_return_cli_errors_without_global_digit_changes(
    tmp_path, capsys
):
    import sys

    before = sys.get_int_max_str_digits()
    digits = "9" * 5001
    for field in ("schema", "schema_version"):
        schema = digits if field == "schema" else '"gamexray-live-report"'
        version = digits if field == "schema_version" else "1"
        text = (
            '{"schema":'
            + schema
            + ',"schema_version":'
            + version
            + ',"report":{"slots":[]}}'
        )
        target = tmp_path / (field + ".json")
        target.write_text(text, encoding="utf-8")
        assert run_live_report_cli(["inspect", str(target)]) == 2
        error = capsys.readouterr().err
        assert "Unsupported live report " + field in error
        assert digits in error
        assert target.read_text(encoding="utf-8") == text
    assert sys.get_int_max_str_digits() == before

"""Untrusted exported and displayed text remains inert and path-private."""

from __future__ import annotations

import ast
import errno
import unicodedata
from pathlib import Path

import pytest

from w3xtool.cli_options import CliOptionError, CliOptions, parse_cli_options, run_cli
from w3xtool.investigation_exports import format_map_object_id_index
from w3xtool.knowledge_io import KnowledgeWriteRecorder, safe_filename, tsv
from w3xtool.load_context import MapLoadContext
from w3xtool.map_data import MapData
from w3xtool.presentation_safety import format_user_exception
from w3xtool.safe_output_models import SafeWriteResult, SafeWriteStatus
from w3xtool.w3world import Region
from w3xtool.world_exports import format_regions_tsv


@pytest.mark.parametrize("marker", ("=", "+", "-", "@"))
def test_tsv_guards_first_nonwhitespace_formula_marker(marker: str) -> None:
    # Given/When: controls and whitespace precede a spreadsheet formula marker.
    cell = tsv(f"\t\x1b {marker}payload")

    # Then: controls are flattened and the first non-space token is inert.
    assert "\t" not in cell
    assert "\x1b" not in cell
    assert cell.lstrip().startswith(f"'{marker}")


def test_tsv_does_not_truncate_durable_export_cells() -> None:
    # Given: a valid long text field belongs in a durable report.
    value = "x" * 5000

    # When/Then: display limits do not alter exported data.
    assert tsv(value) == value


def test_map_identity_tsv_uses_shared_formula_protection() -> None:
    # Given: map-controlled identity fields begin with formula markers.
    md = MapData("+source.w3x", "=display")

    # When: the investigation index renders its identity row.
    row = format_map_object_id_index(md).splitlines()[1]

    # Then: both fields are inert TSV cells.
    assert row.split("\t")[:3] == ["地图", "'=display", "'+source.w3x"]


def test_no_production_module_defines_a_private_tsv_copy() -> None:
    # Given: TSV policy is centralized in knowledge_io.tsv.
    source_root = Path(__file__).resolve().parents[1] / "w3xtool"
    copies: list[str] = []

    # When: every production module is inspected structurally.
    for path in source_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(isinstance(node, ast.FunctionDef) and node.name == "_tsv" for node in ast.walk(tree)):
            copies.append(path.name)

    # Then: no delimiter-only implementation can bypass the shared policy.
    assert copies == []


def test_long_exception_path_is_redacted_before_display_limit() -> None:
    # Given: an absolute path is longer than the entire user-facing error budget.
    secret = "/private/" + "s" * 700 + "/source.w3x"
    error = OSError(errno.EACCES, "denied", secret)

    # When: the exception crosses a display boundary.
    text = format_user_exception(error)

    # Then: no truncated prefix of the path survives.
    assert "<path>" in text
    assert "s" * 32 not in text
    assert len(text) <= 512


def test_structured_write_error_redacts_foreign_paths_and_controls(tmp_path: Path) -> None:
    # Given: a raw sink error includes a non-output path and terminal controls.
    root = tmp_path / "pack"
    secret = tmp_path / "private" / "source.w3x"
    raw_error = f"failed '{secret}'\x1b\u202e"
    raw = SafeWriteResult(SafeWriteStatus.FAILED, str(root / "result.tsv"), 0, raw_error)
    recorder = KnowledgeWriteRecorder(str(root), str(root))

    # When: the error becomes a structured publication item.
    recorder.record(str(root), "result.tsv", raw)
    cleaned = recorder.report().items_by_path["result.tsv"].error or ""

    # Then: raw diagnostics stay intact while the user-facing copy is inert.
    assert raw.error == raw_error
    assert str(secret) not in cleaned
    assert "<path>" in cleaned
    assert all(unicodedata.category(char) not in {"Cc", "Cf"} for char in cleaned)


def test_cli_option_error_removes_control_characters() -> None:
    # Given: an unsupported option contains terminal and line controls.
    with pytest.raises(CliOptionError) as caught:
        parse_cli_options(("map.w3x", "--bad\x1b[2J\nforged"))

    # When: the typed error is rendered by the process entrypoint.
    text = str(caught.value)

    # Then: it cannot alter terminal state or inject a second line.
    assert "\x1b" not in text
    assert "\n" not in text


def test_cli_removes_map_control_sequences(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: a map-controlled display name contains terminal controls.
    md = MapData("fixture.w3x", "Visible\x1b[2J\nForged")
    _patch_cli_load(monkeypatch, md)

    # When: the summary is printed through the real CLI boundary.
    assert run_cli(CliOptions("fixture.w3x")) == 0

    # Then: control bytes cannot alter terminal state or inject a new line.
    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert "地图: Visible [2J Forged" in output


def test_cli_redacts_absolute_paths_from_boundary_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # Given: an expected top-level failure contains an absolute source path.
    md = MapData("fixture.w3x", "Fixture")
    secret = tmp_path / "private" / "source.w3x"
    _patch_cli_load(monkeypatch, md)

    def fail_summary(_md: MapData):
        raise OSError(errno.EACCES, "denied", str(secret))

    monkeypatch.setattr("w3xtool.cli_options.iter_cli_summary_lines", fail_summary)

    # When: the CLI converts that exception into a user-facing error.
    assert run_cli(CliOptions("fixture.w3x")) == 2

    # Then: the error class remains useful but the host path is removed.
    error = capsys.readouterr().err
    assert "PermissionError" in error
    assert str(secret) not in error
    assert "<path>" in error


def test_safe_filename_removes_unicode_control_characters() -> None:
    # Given/When: an archive-controlled label is converted to a filename.
    filename = safe_filename("Unit\x1b[31m\nName")

    # Then: no control or formatting character survives in the component.
    assert all(unicodedata.category(char) not in {"Cc", "Cf"} for char in filename)


def test_world_tsv_prefixes_spreadsheet_formula_cells() -> None:
    # Given: a map-controlled region name begins with a spreadsheet formula marker.
    region = Region(0, 0, 1, 1, "=1+1", 1, "", "", (0, 0, 0), 255)

    # When: the World Editor report is rendered.
    text = format_regions_tsv((region,))

    # Then: opening the TSV cannot execute the cell as a formula.
    assert "\t'=1+1\t" in text


def _patch_cli_load(monkeypatch: pytest.MonkeyPatch, md: MapData) -> None:
    monkeypatch.setattr("w3xtool.cli_options.read_external_listfile", lambda _path: ())
    monkeypatch.setattr(
        "w3xtool.cli_options.build_map_load_context",
        lambda **_kwargs: MapLoadContext(),
    )
    monkeypatch.setattr("w3xtool.cli_options.load_map", lambda _path, **_kwargs: md)

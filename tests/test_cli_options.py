"""Task 6 CLI parsing and execution workflow."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from main import (
    iter_cli_summary_lines as main_cli_summary,
    iter_game_config_summary_lines as main_game_config_summary,
)
from w3xtool.api import MapData
from w3xtool.cli_summary import iter_cli_summary_lines
from w3xtool.cli_options import CliOptionError, CliOptions, parse_cli_options, run_cli
from w3xtool.game_config_summary import iter_game_config_summary_lines
from w3xtool.load_context import MapLoadContext


def test_main_reexports_responsibility_split_summaries() -> None:
    # Given: summary implementations live outside the process entrypoint.
    # When/Then: existing main imports remain source-compatible re-exports.
    assert main_cli_summary is iter_cli_summary_lines
    assert main_game_config_summary is iter_game_config_summary_lines


def test_parse_cli_options_accepts_all_supported_sources(tmp_path: Path) -> None:
    # Given: the documented map, listfile, game-data, and pack arguments.
    argv = (
        "map.w3x",
        "--listfile",
        str(tmp_path / "listfile.txt"),
        "--game-data",
        str(tmp_path / "game-data"),
        "--author-bundle",
        str(tmp_path / "author-bundle"),
        "--pack",
        str(tmp_path / "pack"),
    )

    # When: CLI arguments cross the typed parsing boundary.
    options = parse_cli_options(argv)

    # Then: every supported path is retained exactly.
    assert options == CliOptions(
        map_path="map.w3x",
        listfile_path=str(tmp_path / "listfile.txt"),
        game_data_path=str(tmp_path / "game-data"),
        pack_dir=str(tmp_path / "pack"),
        author_bundle_path=str(tmp_path / "author-bundle"),
    )


@pytest.mark.parametrize(
    "argv",
    ((), ("map.w3x", "--unknown"), ("map.w3x", "--pack"), ("a.w3x", "b.w3x")),
)
def test_parse_cli_options_rejects_invalid_arguments(argv: tuple[str, ...]) -> None:
    # Given: an incomplete or unsupported CLI argument sequence.
    # When/Then: parsing fails at the boundary instead of silently ignoring input.
    with pytest.raises(CliOptionError):
        parse_cli_options(argv)


def test_cli_parse_failure_returns_nonzero(capsys) -> None:
    # Given: CLI options naming a missing map.
    options = CliOptions(map_path="missing.w3x")

    # When: the CLI workflow runs.
    code = run_cli(options)

    # Then: the user receives a stable stderr error and process-style code 2.
    captured = capsys.readouterr()
    assert code == 2
    assert "无法解析地图" in captured.err
    assert captured.out == ""


def test_run_cli_reuses_listfile_context_and_pack_writer(tmp_path: Path, monkeypatch, capsys) -> None:
    # Given: all optional inputs and fakes at the existing shared boundaries.
    options = CliOptions(
        map_path="fixture.w3x",
        listfile_path="names.txt",
        game_data_path="game-data",
        pack_dir=str(tmp_path / "pack"),
        author_bundle_path="author-bundle",
    )
    md = MapData(path="fixture.w3x", name="CLI fixture")
    context = MapLoadContext(external_names=("hidden.blp",))
    calls = []

    monkeypatch.setattr(
        "w3xtool.cli_options.read_external_listfile",
        lambda path: calls.append(("listfile", path)) or ("hidden.blp",),
    )
    monkeypatch.setattr(
        "w3xtool.cli_options.build_map_load_context",
        lambda *, external_names, game_data_path, author_bundle_path: (
            calls.append(("context", (external_names, game_data_path, author_bundle_path))) or context
        ),
    )
    monkeypatch.setattr(
        "w3xtool.cli_options.load_map",
        lambda path, *, load_context: calls.append(("load", (path, load_context))) or md,
    )
    monkeypatch.setattr(
        "w3xtool.cli_options.iter_cli_summary_lines",
        lambda _md: iter(("地图: CLI fixture",)),
    )
    monkeypatch.setattr(
        "w3xtool.cli_options.write_knowledge_pack",
        lambda _md, out, external_names=(), game_data_path=None: (
            calls.append(("pack", (out, external_names, game_data_path))) or 7
        ),
    )

    # When: the CLI loads and exports the map.
    code = run_cli(options)

    # Then: it delegates listfile, context, loading, and pack work to shared APIs.
    captured = capsys.readouterr()
    assert code == 0
    assert "地图: CLI fixture" in captured.out
    assert "资料包: 7 个文件" in captured.out
    assert captured.err == ""
    assert calls == [
        ("listfile", "names.txt"),
        ("context", (("hidden.blp",), "game-data", "author-bundle")),
        ("load", ("fixture.w3x", context)),
        ("pack", (str(tmp_path / "pack"), ("hidden.blp",), "game-data")),
    ]


def test_cli_summary_failure_returns_two_without_archive_diagnosis(monkeypatch, capsys) -> None:
    # Given: a map that opened successfully but whose summary renderer fails.
    md = MapData(path="fixture.w3x", name="CLI fixture")
    monkeypatch.setattr("w3xtool.cli_options.read_external_listfile", lambda _path: ())
    monkeypatch.setattr(
        "w3xtool.cli_options.build_map_load_context",
        lambda **_kwargs: MapLoadContext(),
    )
    monkeypatch.setattr("w3xtool.cli_options.load_map", lambda _path, **_kwargs: md)
    monkeypatch.setattr(
        "w3xtool.cli_options.iter_cli_summary_lines",
        lambda _md: (_ for _ in ()).throw(ValueError("summary failed")),
    )

    # When: the CLI workflow reaches summary rendering.
    code = run_cli(CliOptions(map_path="fixture.w3x"))

    # Then: it is a stable CLI error, not a false archive-open diagnosis.
    captured = capsys.readouterr()
    assert code == 2
    assert "无法生成地图摘要" in captured.err
    assert "MPQ 头" not in captured.err
    assert captured.out == ""


def test_main_cli_process_returns_two_for_invalid_options() -> None:
    # Given: the real main.py CLI with an unsupported option.
    project_root = Path(__file__).resolve().parents[1]

    # When: the process is invoked through its public command shape.
    result = subprocess.run(
        (sys.executable, "main.py", "cli", "map.w3x", "--unknown"),
        cwd=project_root,
        check=False,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )

    # Then: argument errors use stderr and process exit code 2.
    assert result.returncode == 2
    assert "参数" in result.stderr
    assert result.stdout == ""

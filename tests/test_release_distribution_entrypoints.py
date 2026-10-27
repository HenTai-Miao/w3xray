"""Release entrypoints expose help and stable errors without GUI side effects."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from gametool import __version__, app, cli_options
from gametool.dev_test import create_test_environment
from gametool.knowledge_results import KnowledgeWriteItem, KnowledgeWriteReport

_ROOT = Path(__file__).resolve().parents[1]
_COMMANDS = (
    "cli",
    "pack-query",
    "guide",
    "live",
    "live-report",
    "reference",
    "current",
    "batch",
    "casc",
    "save",
    "savecodes",
    "wgc",
    "gameconfig",
    "acceptance",
)


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "gametool", *arguments],
        cwd=_ROOT,
        env=create_test_environment(),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("command", _COMMANDS)
@pytest.mark.parametrize("flag", ("--help", "-h"))
def test_every_command_help_finishes_without_opening_inputs(
    command: str, flag: str
) -> None:
    result = _run(command, flag)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    assert not result.stderr
    assert "Traceback" not in result.stdout


@pytest.mark.parametrize("command", ("integrity", "description-cache"))
@pytest.mark.parametrize("flag", ("--help", "-h"))
def test_retired_command_help_returns_two_with_supported_alternatives(
    command: str, flag: str
) -> None:
    result = _run(command, flag)

    assert result.returncode == 2
    assert not result.stdout
    assert "Windows" in result.stderr and "--help" in result.stderr
    assert "pack-query" in result.stderr
    if command == "integrity":
        assert "live-report inspect" in result.stderr
        assert "live-report diff" in result.stderr
    else:
        assert "--description-cache" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "arguments",
    (
        ("integrity",),
        ("integrity", "snapshot", "--root", "fixture=unread", "--output", "unwritten"),
        ("integrity", "verify", "--snapshot", "unread"),
        (
            "integrity",
            "retained-cache",
            "--active-root",
            "unread",
            "--output",
            "unwritten",
        ),
        ("description-cache",),
        (
            "description-cache",
            "migrate",
            "--legacy-output",
            "unread",
            "--legacy-cache",
            "unread.tsv",
            "--output",
            "unwritten",
        ),
    ),
)
@pytest.mark.parametrize("help_flag", ((), ("--help",), ("-h",)))
def test_retired_commands_never_enter_backends_inputs_single_instance_or_gui(
    arguments: tuple[str, ...],
    help_flag: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    touched: list[str] = []
    for name, function in (
        ("gametool.integrity_cli", "run_integrity_cli"),
        ("gametool.description_cache_cli", "run_description_cache_cli"),
        ("gametool.single_instance", "ensure_single_instance"),
        ("gametool.gui", "main"),
    ):
        module = ModuleType(name)
        monkeypatch.setattr(
            module,
            function,
            lambda *_args, selected=name: touched.append(selected) or 7,
            raising=False,
        )
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sys, "argv", ["gamexray", *arguments, *help_flag])

    def unexpected_input(*_args: object, **_kwargs: object):
        touched.append("input")
        raise AssertionError("retired commands must not inspect paths")

    with monkeypatch.context() as inputs:
        inputs.setattr(Path, "open", unexpected_input)
        inputs.setattr(Path, "stat", unexpected_input)
        with pytest.raises(SystemExit) as caught:
            app.main()

    assert caught.value.code == 2
    assert not touched
    output = capsys.readouterr()
    assert not output.out
    assert "Windows" in output.err and "pack-query" in output.err
    assert "--help" in output.err


def test_release_build_help_gate_matches_only_supported_commands() -> None:
    script = (_ROOT / "tools" / "build_windows_release.ps1").read_text(encoding="utf-8")
    command_gate = next(
        line
        for line in script.splitlines()
        if line.startswith("foreach ($Command in @(")
    )
    for command in _COMMANDS:
        assert f'"{command}"' in command_gate
    for command in ("integrity", "description-cache"):
        assert f'"{command}"' not in command_gate


def test_top_help_discovers_every_command_and_all_entrypoints_share_version() -> None:
    result = _run("--help")
    assert result.returncode == 0
    for command in _COMMANDS:
        assert command in result.stdout
    for command in ("integrity", "description-cache"):
        assert command not in result.stdout

    version = _run("--version")
    assert version.returncode == 0
    assert version.stdout.strip() == f"GameXRay {__version__}"
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"]["gamexray"] == "gametool.app:main"
    assert project["project"]["gui-scripts"]["gamexray-gui"] == "gametool.app:main"


@pytest.mark.parametrize("argument", ("typo", "--hlep", "--unknown-option", "-v"))
def test_unknown_top_argument_never_enters_single_instance_or_gui(
    argument: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    touched: list[str] = []
    single_instance = ModuleType("gametool.single_instance")
    monkeypatch.setattr(
        single_instance,
        "ensure_single_instance",
        lambda: touched.append("instance"),
        raising=False,
    )
    gui = ModuleType("gametool.gui")
    monkeypatch.setattr(gui, "main", lambda: touched.append("gui"), raising=False)
    monkeypatch.setitem(sys.modules, "gametool.single_instance", single_instance)
    monkeypatch.setitem(sys.modules, "gametool.gui", gui)
    monkeypatch.setattr(sys, "argv", ["gamexray", argument])

    with pytest.raises(SystemExit) as caught:
        app.main()

    assert caught.value.code == 2
    assert not touched
    assert "--help" in capsys.readouterr().err


@pytest.mark.parametrize("command", ("wgc", "gameconfig"))
def test_configuration_input_errors_return_two_on_stderr(
    command: str, tmp_path: Path
) -> None:
    result = _run(command, str(tmp_path / "missing.wgc"))

    assert result.returncode == 2
    assert "无法解析游戏配置" in result.stderr
    assert not result.stdout


def test_invalid_profile_is_an_argument_error_before_any_input_access(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unexpected_load(*_args: object, **_kwargs: object) -> None:
        pytest.fail("an invalid extraction profile must not load a map")

    monkeypatch.setattr(cli_options, "load_map", unexpected_load)
    with pytest.raises(cli_options.CliOptionError, match="未知提取类目"):
        cli_options.parse_cli_options(("missing.w3x", "--profile", "-not-a-category"))
    assert (
        cli_options.run_cli(
            cli_options.CliOptions("missing.w3x", profile_text="-not-a-category")
        )
        == 2
    )
    output = capsys.readouterr()
    assert "--help" in output.err
    assert not output.out


def test_cli_does_not_publish_campaign_children_after_parent_input_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = KnowledgeWriteReport((KnowledgeWriteItem(".", False, 0, "请选择空目录"),))
    destinations: list[str] = []

    def refuse(_map_data: object, destination: str, **_kwargs: object):
        destinations.append(destination)
        return report

    monkeypatch.setattr(cli_options, "write_knowledge_pack_report", refuse)
    map_data = SimpleNamespace(sub_maps=(SimpleNamespace(name="child"),))

    result = cli_options._write_cli_packs(
        map_data, cli_options.CliOptions("campaign.w3n", pack_dir="existing-pack"), ()
    )

    assert result is report
    assert destinations == ["existing-pack"]

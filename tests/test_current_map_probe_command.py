"""Low-level command and output parsing for current-map probes."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from w3xtool.current_map_models import EvidenceKind, GameProcess, MapEvidence
from w3xtool.current_map_probe_command import (
    parse_lsof_open_maps,
    parse_posix_processes,
    parse_windows_processes,
    popen_creation_flags,
    run_bounded_command,
)


def test_parses_posix_game_records_and_excludes_editor_and_launcher() -> None:
    # Given: ps records for two games plus editor and launcher lookalikes.
    commands = (
        " 101 /Applications/Warcraft III.app/Contents/MacOS/Warcraft III -launch",
        " 102 /Applications/Warcraft III/World Editor.app/Contents/MacOS/World Editor",
        ' 103 "/Applications/Battle.net.app/Contents/MacOS/Battle.net" --game=war3',
        ' 104 /usr/bin/wine64 "C:\\Games\\Warcraft III.exe" -loadfile arena.w3x',
    )

    # When: the bounded POSIX parser classifies the records.
    processes = parse_posix_processes("\n".join(commands).encode())

    # Then: only actual game processes remain with their original command lines.
    assert processes == (
        GameProcess(101, "Warcraft III", commands[0].lstrip().split(maxsplit=1)[1]),
        GameProcess(104, "Warcraft III", commands[3].lstrip().split(maxsplit=1)[1]),
    )


def test_posix_process_classification_uses_executable_identity() -> None:
    # Given: Wine game/editor records and a non-game process with game-like arguments.
    commands = (
        ' 111 /usr/bin/wine64 "C:\\Games\\Warcraft III.exe" -loadfile "Maps\\launcher arena.w3x"',
        ' 112 /usr/bin/wine64 "C:\\Games\\Warcraft III Editor.exe" -loadfile arena.w3x',
        ' 113 /usr/bin/python worker.py --map "C:\\Games\\Warcraft III.exe"',
        ' 114 "/Applications/Warcraft III Launcher.app/Contents/MacOS/Warcraft III Launcher"',
    )

    # When: POSIX records are classified from executable identity.
    processes = parse_posix_processes("\n".join(commands).encode())

    # Then: the real game survives argument text while editor/decoy/launcher do not.
    assert processes == (
        GameProcess(111, "Warcraft III", commands[0].lstrip().split(maxsplit=1)[1]),
    )


def test_wine_classifier_preserves_unquoted_windows_executable_path() -> None:
    # Given: Wine launches an unquoted Windows path alongside identity lookalikes.
    commands = (
        r" 121 /usr/bin/wine64 C:\Games\war3.exe -loadfile Maps\arena.w3x",
        r" 122 /usr/bin/wine64 C:\Games\WarcraftIIIEditor.exe",
        r" 123 /usr/bin/wine64 C:\Games\WarcraftIIILauncher.exe",
        r" 124 /usr/bin/python worker.py C:\Games\war3.exe",
    )

    # When: POSIX process records parse the Wine target executable.
    processes = parse_posix_processes("\n".join(commands).encode())

    # Then: only the exact game executable is retained with separators intact.
    assert processes == (
        GameProcess(121, "Warcraft III", commands[0].lstrip().split(maxsplit=1)[1]),
    )


def test_parses_windows_cim_csv_and_excludes_non_game_processes() -> None:
    # Given: PowerShell CIM CSV containing game, editor, and launcher rows.
    payload = (
        '"ProcessId","Name","CommandLine"\r\n'
        '"201","Warcraft III.exe","""C:\\Games\\Warcraft III.exe"" -launch"\r\n'
        '"202","World Editor.exe","""C:\\Games\\World Editor.exe"""\r\n'
        '"203","Battle.net.exe","""C:\\Battle.net\\Battle.net.exe"" --game=war3"\r\n'
    ).encode()

    # When: the Windows process boundary parses the CIM records.
    processes = parse_windows_processes(payload)

    # Then: only the actual game record is retained exactly.
    assert processes == (
        GameProcess(201, "Warcraft III.exe", '"C:\\Games\\Warcraft III.exe" -launch'),
    )


def test_windows_process_classification_uses_cim_executable_name() -> None:
    # Given: CIM names identify a real game, its editor, and a game-like argument decoy.
    payload = (
        '"ProcessId","Name","CommandLine"\r\n'
        '"211","Warcraft III.exe","""C:\\Games\\Warcraft III.exe"" -loadfile ""Maps\\launcher arena.w3x"""\r\n'
        '"212","Warcraft III Editor.exe","""C:\\Games\\Warcraft III Editor.exe"""\r\n'
        '"213","helper.exe","helper.exe --map ""C:\\Games\\Warcraft III.exe"""\r\n'
    ).encode()

    # When: Windows records are classified from their CIM executable name.
    processes = parse_windows_processes(payload)

    # Then: command-line arguments neither suppress nor impersonate the game executable.
    assert processes == (
        GameProcess(
            211,
            "Warcraft III.exe",
            '"C:\\Games\\Warcraft III.exe" -loadfile "Maps\\launcher arena.w3x"',
        ),
    )


def test_windows_parser_skips_kernel_pseudo_process_rows() -> None:
    # Given: real CIM listings always open with the PID 0 and PID 4 kernel rows.
    payload = (
        '"ProcessId","Name","CommandLine"\r\n'
        '"0","System Idle Process",\r\n'
        '"4","System",\r\n'
        '"301","Warcraft III.exe","""C:\\Games\\Warcraft III.exe"" -launch"\r\n'
    ).encode()

    # When: the Windows parser classifies the records.
    processes = parse_windows_processes(payload)

    # Then: kernel rows are skipped and the game record survives intact.
    assert processes == (
        GameProcess(301, "Warcraft III.exe", '"C:\\Games\\Warcraft III.exe" -launch'),
    )


def test_posix_parser_skips_kernel_task_record() -> None:
    # Given: macOS ps output starts with the PID 0 kernel_task record.
    commands = (
        "     0 kernel_task",
        " 311 /Applications/Warcraft III.app/Contents/MacOS/Warcraft III",
    )

    # When: the POSIX parser classifies the records.
    processes = parse_posix_processes("\n".join(commands).encode())

    # Then: the kernel record is skipped without rejecting the whole output.
    assert processes == (
        GameProcess(311, "Warcraft III", commands[1].lstrip().split(maxsplit=1)[1]),
    )


def test_bounded_command_times_out_without_exposing_the_command() -> None:
    # Given: an absolute executable whose child will outlive a tiny deadline.
    command = (str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(10)")

    # When: the fixed command boundary reaches its deadline.
    result = run_bounded_command(command, timeout_seconds=0.05, output_limit=64)

    # Then: it reports only a typed timeout and retains no command or output text.
    assert result.issue is not None
    assert result.issue.value == "timeout"
    assert result.stdout == b""


def test_bounded_command_rejects_output_above_the_fixed_limit() -> None:
    # Given: an absolute executable emits more than the retained byte budget.
    command = (
        str(Path(sys.executable).resolve()),
        "-c",
        "import os; os.write(1, b'x' * 4096)",
    )

    # When: the command runs with a 64-byte output limit.
    result = run_bounded_command(command, timeout_seconds=1.0, output_limit=64)

    # Then: no truncated prefix is accepted or exposed as valid tool output.
    assert result.issue is not None
    assert result.issue.value == "output_limit"
    assert result.stdout == b""


def test_bounded_command_hides_windows_probe_windows() -> None:
    # Given: Popen creation flags are selected for each operating-system family.

    # When: the low-level command adapter computes platform-specific flags.
    windows_flags = popen_creation_flags("nt")
    posix_flags = popen_creation_flags("posix")

    # Then: Windows uses CREATE_NO_WINDOW and POSIX adds no creation flags.
    assert windows_flags == 0x08000000
    assert posix_flags == 0


def test_parses_nul_delimited_lsof_with_chinese_map_path(tmp_path: Path) -> None:
    # Given: lsof field output associates a Chinese map path with one allowed PID.
    map_path = tmp_path / "平台 地图.w3m"
    _ = map_path.write_bytes(b"map")
    payload = b"p401\0\nn" + os.fsencode(map_path) + b"\0\np999\0\nn/ignored.w3x\0\n"

    # When: the lsof boundary parses NUL-delimited PID and name fields.
    evidence = parse_lsof_open_maps(payload, frozenset({401}))

    # Then: only the allowed PID's exact filesystem path becomes direct evidence.
    assert evidence == (MapEvidence(map_path, EvidenceKind.DIRECT_OPEN, 401),)

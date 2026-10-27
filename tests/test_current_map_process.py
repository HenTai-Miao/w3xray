"""Public process-linked current-map probe behavior."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from gametool.current_map_models import EvidenceKind, GameProcess, MapEvidence
from gametool.current_map_process import (
    ProbeIssue,
    ProcessProbeReport,
    explicit_argument_evidence,
    posix_process_report,
    windows_process_report,
)


def test_public_process_report_exposes_every_game_process() -> None:
    # Given: valid ps output exceeds the former 128-process limit.
    payload = "\n".join(f"{pid} war3" for pid in range(601, 850)).encode()

    # When: the POSIX boundary constructs its public process report.
    report = posix_process_report(payload)

    # Then: every PID record is exposed.
    assert tuple(item.pid for item in report.processes) == tuple(range(601, 850))


@pytest.mark.parametrize(
    ("report_factory", "payload"),
    (
        (posix_process_report, b"not-a-pid malformed"),
        (windows_process_report, b'"Wrong","Columns"\r\n"1","war3"\r\n'),
    ),
)
def test_malformed_process_output_returns_typed_unavailable_report(
    report_factory: Callable[[bytes], ProcessProbeReport],
    payload: bytes,
) -> None:
    # Given: successful tools returned structurally invalid process records.

    # When: each platform boundary converts its untrusted output.
    report = report_factory(payload)

    # Then: callers receive a stable issue without any raw output text.
    assert report == ProcessProbeReport((), False, ProbeIssue.MALFORMED_OUTPUT)


def test_resolves_quoted_map_argument_against_bounded_roots(tmp_path: Path) -> None:
    # Given: a Wine-style quoted relative map argument exists under the second root.
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    map_path = second_root / "Maps" / "中文 对战.w3x"
    map_path.parent.mkdir(parents=True)
    _ = map_path.write_bytes(b"map")
    process = GameProcess(
        501, "Warcraft III", 'war3.exe -loadfile "Maps\\中文 对战.w3x"'
    )

    # When: explicit arguments are resolved under the supplied roots.
    evidence = explicit_argument_evidence((process,), (first_root, second_root))

    # Then: the existing map is normalized and linked to its process.
    assert evidence == (
        MapEvidence(map_path.resolve(), EvidenceKind.EXPLICIT_ARGUMENT, process.pid),
    )


def test_quoted_map_path_requires_loadfile_flag(tmp_path: Path) -> None:
    # Given: both quoted paths exist, but one is ordinary description text.
    maps = tmp_path / "Maps"
    maps.mkdir()
    selected = maps / "selected map.w3x"
    decoy = maps / "decoy map.w3x"
    _ = selected.write_bytes(b"selected")
    _ = decoy.write_bytes(b"decoy")
    process = GameProcess(
        503,
        "Warcraft III",
        'war3.exe --description "Maps\\decoy map.w3x" --loadfile "Maps\\selected map.w3x"',
    )

    # When: explicit quoted arguments are extracted.
    evidence = explicit_argument_evidence((process,), (tmp_path,))

    # Then: only the path syntactically bound to loadfile becomes evidence.
    assert evidence == (
        MapEvidence(selected.resolve(), EvidenceKind.EXPLICIT_ARGUMENT, process.pid),
    )


def test_nested_description_loadfile_text_is_not_an_argument(tmp_path: Path) -> None:
    # Given: a description token contains loadfile-like text naming an existing map.
    decoy = tmp_path / "Maps" / "decoy.w3x"
    decoy.parent.mkdir()
    _ = decoy.write_bytes(b"decoy")
    process = GameProcess(
        504,
        "Warcraft III",
        "war3.exe --description 'please use -loadfile \"Maps\\decoy.w3x\" later'",
    )

    # When: explicit arguments are parsed from top-level command tokens.
    evidence = explicit_argument_evidence((process,), (tmp_path,))

    # Then: nested prose cannot create direct map evidence.
    assert evidence == ()


def test_resolves_unquoted_loadfile_but_ignores_ordinary_map_text(
    tmp_path: Path,
) -> None:
    # Given: both paths exist, but only one follows the explicit -loadfile flag.
    maps = tmp_path / "Maps"
    maps.mkdir()
    selected = maps / "a.w3x"
    decoy = maps / "decoy.w3x"
    _ = selected.write_bytes(b"selected")
    _ = decoy.write_bytes(b"ordinary text")
    process = GameProcess(
        502,
        "Warcraft III",
        r"war3.exe --description Maps\decoy.w3x -loadfile Maps\a.w3x",
    )

    # When: explicit map arguments are extracted from the command line.
    evidence = explicit_argument_evidence((process,), (tmp_path,))

    # Then: the flag-bound unquoted path is retained and ordinary text is ignored.
    assert evidence == (
        MapEvidence(selected.resolve(), EvidenceKind.EXPLICIT_ARGUMENT, process.pid),
    )


def test_explicit_argument_probe_checks_every_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: two process commands contain 80 nonexistent loadfile occurrences.
    calls = 0

    def record_is_file(_path: Path) -> bool:
        nonlocal calls
        calls += 1
        return False

    monkeypatch.setattr(Path, "is_file", record_is_file)
    processes = tuple(
        GameProcess(
            520 + process_index,
            "Warcraft III",
            "war3.exe "
            + " ".join(
                f"-loadfile Maps\\missing-{process_index}-{item}.w3x"
                for item in range(40)
            ),
        )
        for process_index in range(2)
    )
    roots = tuple(tmp_path / f"root-{item}" for item in range(70))

    # When: explicit arguments are checked against all bounded roots.
    evidence = explicit_argument_evidence(processes, roots)

    # Then: every occurrence checks every supplied root.
    assert evidence == ()
    assert calls == 80 * 70

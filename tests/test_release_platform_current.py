"""Release regressions for current-map discovery outside the default install."""

import ctypes
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from gametool import current_map_discovery as discovery
from gametool import current_map_inuse_probe as inuse
from gametool.current_map_models import EvidenceKind, GameProcess, ResolutionStatus
from gametool.current_map_process import (
    OpenMapProbeReport,
    ProcessProbeReport,
    explicit_argument_evidence,
)


def test_loadfile_resolves_from_running_install_directory(tmp_path: Path) -> None:
    install = tmp_path / "custom install"
    target = install / "Maps" / "selected map.w3x"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fixture map")
    process = GameProcess(
        73, "war3.exe", f'"{install / "war3.exe"}" -loadfile "Maps\\selected map.w3x"'
    )

    evidence = explicit_argument_evidence((process,), (target.parent,))

    assert len(evidence) == 1
    assert evidence[0].path == target.resolve()
    assert evidence[0].process_id == 73
    assert evidence[0].kind is EvidenceKind.EXPLICIT_ARGUMENT


@pytest.mark.parametrize("subdir", ("Maps", "Campaigns"))
def test_current_finds_stale_open_map_beside_running_custom_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subdir: str
) -> None:
    install = tmp_path / "another drive" / "Warcraft III"
    target = install / subdir / "session.w3n"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fixture campaign")
    os.utime(target, ns=(1_000_000_000, 1_000_000_000))
    process = GameProcess(73, "war3.exe", f'"{install / "war3.exe"}"')
    monkeypatch.setattr(discovery, "_known_map_roots", lambda _home: ())

    resolution = discovery.locate_current_map(
        process_provider=lambda: ProcessProbeReport((process,), True),
        open_file_provider=lambda _processes: OpenMapProbeReport((), False),
        in_use_provider=lambda paths: tuple(path for path in paths if path == target),
    )

    assert resolution.status is ResolutionStatus.FOUND
    assert tuple(candidate.path for candidate in resolution.candidates) == (
        Path(os.path.normcase(target.resolve())),
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows file-sharing API")
def test_inuse_probe_reads_readonly_source_maps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = {"value": 0}

    def open_file(_path, access, _sharing, *_args):
        error["value"] = 5 if access & inuse.GENERIC_WRITE else 32
        return inuse._INVALID_HANDLE

    api = SimpleNamespace(
        CreateFileW=open_file,
        GetLastError=lambda: error["value"],
        CloseHandle=lambda _handle: True,
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: api)

    probe = inuse._windows_probe.__wrapped__()

    assert probe(Path("readonly-map.w3x")) is True

"""Packaged-runtime acceptance report contracts."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from w3xtool.casclib_enumeration import CascEntry, CascNameType

_ROOT = Path(__file__).resolve().parents[1]
_MAP = _ROOT / "tests" / "fixtures" / "maps" / "war3net-map-script-builder.w3x"
_CAMPAIGN = _ROOT / "tests" / "fixtures" / "reference" / "stormlib-campaign.w3n"


def test_core_acceptance_executes_map_campaign_export_and_repeat_load(
    tmp_path: Path,
) -> None:
    # Given: portable real map/campaign fixtures and a clean evidence directory.
    module = importlib.import_module("w3xtool.acceptance_runner")
    config = module.AcceptanceConfig(
        map_path=_MAP,
        campaign_path=_CAMPAIGN,
        war3_dir=None,
        output_dir=tmp_path,
        repeat_count=3,
        run_gui=False,
        require_windows=False,
    )

    # When: the same runner used by the packaged EXE performs acceptance.
    report = module.run_acceptance(config)

    # Then: every portable user workflow passed and produced real output evidence.
    statuses = {check.name: check.status.value for check in report.checks}
    assert statuses["map_load"] == "pass"
    assert statuses["campaign_switch"] == "pass"
    assert statuses["knowledge_pack_export"] == "pass"
    assert statuses["batch_publication"] == "pass"
    assert statuses["repeat_load"] == "pass"
    assert statuses["real_windows_casc"] == "skip"
    assert report.overall_status.value == "pass"
    assert (tmp_path / "knowledge-pack" / "资料包目录.tsv").is_file()


def test_portable_acceptance_skips_bundled_casclib(tmp_path: Path) -> None:
    # Given: a portable acceptance run that does not require Windows.
    module = importlib.import_module("w3xtool.acceptance_runner")
    config = module.AcceptanceConfig(
        map_path=_MAP,
        campaign_path=None,
        war3_dir=None,
        output_dir=tmp_path,
        run_gui=False,
        require_windows=False,
    )

    # When: the acceptance runner executes every configured lane.
    report = module.run_acceptance(config)

    # Then: the packaged CascLib lane is explicitly skipped.
    statuses = {check.name: check.status.value for check in report.checks}
    assert statuses["bundled_casclib"] == "skip"


def test_windows_acceptance_loads_bundled_casclib(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: a packaged DLL path and an observable native API constructor.
    module = importlib.import_module("w3xtool.acceptance_runner")
    dll = tmp_path / "CascLib.dll"
    dll.write_bytes(b"MZfixture")
    loaded: list[Path] = []

    monkeypatch.setattr(module, "default_dll_path", lambda: dll)
    monkeypatch.setattr(
        module, "CtypesCascLibApi", lambda *, dll_path: loaded.append(dll_path)
    )

    # When: Windows acceptance proves the bundled CascLib runtime can load.
    check = module._bundled_casclib_check(require_windows=True)

    # Then: construction binds the DLL and records packaged-file evidence.
    assert check.status.value == "pass"
    assert loaded == [dll]
    assert "CascLib.dll" in check.detail


def test_main_acceptance_mode_writes_machine_readable_report(tmp_path: Path) -> None:
    # Given: the public main entrypoint and explicit acceptance arguments.
    report_path = tmp_path / "acceptance.json"
    command = [
        sys.executable,
        str(_ROOT / "main.py"),
        "acceptance",
        "--map",
        str(_MAP),
        "--campaign",
        str(_CAMPAIGN),
        "--output",
        str(tmp_path / "evidence"),
        "--report",
        str(report_path),
        "--repeat",
        "2",
        "--no-gui",
    ]

    # When: the process runs exactly as a packaged EXE subcommand will run.
    result = subprocess.run(
        command,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        check=False,
    )

    # Then: exit status and JSON both expose the acceptance result.
    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["overall_status"] == "pass"
    assert {item["name"] for item in payload["checks"]} >= {
        "map_load",
        "campaign_switch",
        "knowledge_pack_export",
        "batch_publication",
        "repeat_load",
    }


def test_main_acceptance_mode_loads_and_visits_all_gui_tabs(tmp_path: Path) -> None:
    # Given: a fresh process running the real Tk workbench acceptance lane.
    report_path = tmp_path / "gui-acceptance.json"
    command = [
        sys.executable,
        str(_ROOT / "main.py"),
        "acceptance",
        "--map",
        str(_MAP),
        "--output",
        str(tmp_path / "gui-evidence"),
        "--report",
        str(report_path),
        "--repeat",
        "1",
    ]

    # When: GUI acceptance loads the map and cycles the primary tab set.
    result = subprocess.run(
        command,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        check=False,
    )

    # Then: the lane reports all ten tabs through the public entrypoint.
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    gui_check = next(item for item in payload["checks"] if item["name"] == "gui_tabs")
    assert gui_check["status"] == "pass"
    assert "tabs=10" in gui_check["detail"]


def test_packaged_acceptance_rejects_partial_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: publication writes its manifest but reports one failed artifact.
    module = importlib.import_module("w3xtool.acceptance_runner")
    from w3xtool.knowledge_results import KnowledgeWriteItem, KnowledgeWriteReport
    from w3xtool.map_data import MapData

    partial = KnowledgeWriteReport(
        (
            KnowledgeWriteItem("资料包目录.tsv", True, 10, None),
            KnowledgeWriteItem("对象ID/单位.tsv", False, 0, "disk full"),
        )
    )

    def publish(_md: MapData, pack_dir: str) -> KnowledgeWriteReport:
        path = Path(pack_dir)
        path.mkdir(parents=True)
        (path / "资料包目录.tsv").write_text("ok", encoding="utf-8")
        return partial

    monkeypatch.setattr(
        module, "load_map", lambda _path: MapData("fixture.w3x", "fixture")
    )
    monkeypatch.setattr(module, "write_knowledge_pack_report", publish, raising=False)

    # When/Then: the packaged acceptance lane refuses to false-pass a partial pack.
    with pytest.raises(module.AcceptanceCheckError, match="部分"):
        module._check_knowledge_pack(Path("fixture.w3x"), tmp_path)


def test_real_casc_acceptance_reopens_one_unknown_root_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: native enumeration exposes a local FileDataID entry after a known path.
    module = importlib.import_module("w3xtool.acceptance_runner")
    unknown_name = "FILE0000004D.dat"

    class FakeSource:
        def __init__(self, _root: str) -> None:
            self.read_names: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read_file(self, name: str) -> bytes:
            self.read_names.append(name)
            return b"data"

        def iter_entries(self):
            yield CascEntry(
                "UI\\TriggerData.txt",
                CascNameType.FULL,
                None,
                "01" * 16,
                "02" * 16,
                4,
                True,
                None,
                None,
            )
            yield CascEntry(
                unknown_name,
                CascNameType.FILE_DATA_ID,
                77,
                "03" * 16,
                "04" * 16,
                4,
                True,
                None,
                None,
            )

    source = FakeSource("C:/Warcraft III")
    monkeypatch.setattr(module, "CascLibDataSource", lambda _root: source)

    # When: the real-CASC acceptance lane runs.
    detail = module._check_casc(Path("C:/Warcraft III"))

    # Then: it proves an enumerated unknown identity can be opened, not merely listed.
    assert unknown_name in source.read_names
    assert f"unknown_root_entry={unknown_name}" in detail

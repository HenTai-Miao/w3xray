"""Run real offline workspace acceptance in its own Tcl/App subprocess."""

from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
import sys
import tkinter as tk

from gametool.dev_test import create_test_environment


_CHILD_FLAG = "GAMEXRAY_OFFLINE_ACCEPTANCE_CHILD"


def test_real_offline_workspaces_and_parent_teardown(tmp_path: Path) -> None:
    node = "test_real_offline_workspaces_and_parent_teardown"
    if os.environ.get(_CHILD_FLAG) != node:
        environment = create_test_environment()
        environment[_CHILD_FLAG] = node
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "pytest",
                "-q",
                "-s",
                "--basetemp",
                str(tmp_path / "child-pytest"),
                f"{Path(__file__).resolve()}::{node}",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=240,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout
        assert "OFFLINE-GUI-ACCEPTED" in result.stdout
        assert "hotkeys-declared-bindings=2; hotkeys-projection=2x42" in result.stdout
        assert "invalid command name" not in result.stderr
        assert "TclError" not in result.stderr
        print(result.stdout, end="")
        return

    from gametool.gui import App
    from gametool.gui_acceptance import _destroy_without_persisting
    from gametool.gui_offline_acceptance import (
        _capture_callbacks,
        _pump_after_close,
        exercise_offline_workspaces,
    )

    app = App()
    with _capture_callbacks(app) as errors:
        try:
            environment_before = {
                key: os.environ.get(key)
                for key in ("GAMEXRAY_CACHE_DIR", "GAMEXRAY_GUI_CONFIG_PATH")
            }
            detail = exercise_offline_workspaces(app)
            assert app.map_data is None
            assert "offline-id-records=2" in detail
            assert "offline-save-files=2" in detail
            assert "offline-map-records=2" in detail
            assert "offline-map-filtered=1" in detail
            assert "offline-gui-exports=31" in detail
            assert "legacy-gui-exports=22" in detail
            assert "v12-gui-exports=8" in detail
            assert "offline-selected-exports=json/tsv/md" in detail
            assert "offline-pack-handoffs=2" in detail
            assert "offline-utf16-carriers=2" in detail
            assert "upgrade-field-records=37" in detail
            assert "archive-recovered-members=7" in detail
            assert (
                "diagnostic-maps=4; diagnostic-groups=4; diagnostic-mutations=4"
                in detail
            )
            artifacts = Path(detail.rsplit("offline-artifacts=", 1)[1])
            inventory = json.loads(
                (artifacts / "acceptance-inventory.json").read_text(encoding="utf-8")
            )
            assert inventory["accepted"] == 14
            assert {case["name"] for case in inventory["cases"]} == {
                "external-id-full-records",
                "direct-map-multiselect-json-tsv-md",
                "pack-scope-real-query-handoff",
                "save-independent-full-files",
                "save-explicit-utf16le-no-bom",
                "hotkeys-complete-static-projections",
                "upgrade-explicit-category-full-exports",
                "archive-all-export-exact-recovered-members",
                "script-diagnostics-visible-complete-evidence",
                "source-bytes-and-metadata-unchanged",
                "owned-window-teardown",
                "calls-source-query-history-replay",
                "offline-loadout-complete-records",
                "unicode-wts-w3f-inheritance",
            }
            from gametool.gui_offline_acceptance_v12 import expected_export_names

            assert len(inventory["exports"]) == 31
            assert set(inventory["exports"]) == expected_export_names()
            assert inventory["failed"] == inventory["not_run"] == 0
            assert inventory["callback_errors"] == []
            assert all(case["status"] == "accepted" for case in inventory["cases"])
            assert "hotkeys-runtime-verified=False" in detail
            assert not [
                child
                for child in app.winfo_children()
                if isinstance(child, tk.Toplevel)
            ]
            assert {
                key: os.environ.get(key) for key in environment_before
            } == environment_before
            print("OFFLINE-GUI-ACCEPTED " + detail)
        finally:
            errors.remember(app)
            _destroy_without_persisting(app)
            _pump_after_close(app, errors)
        assert errors == []

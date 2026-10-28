"""Run real offline workspace acceptance in its own Tcl/App subprocess."""

from __future__ import annotations

import os
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
            timeout=180,
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
            assert "offline-gui-exports=5" in detail
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

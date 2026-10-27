"""Private GUI profiles follow the repository test-cache boundary."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest

from gametool.dev_test import create_test_environment


@pytest.mark.parametrize("previous", [None, "", "caller-gui-profile.json"])
def test_test_environment_allocates_gui_profile_without_mutating_caller(
    monkeypatch: pytest.MonkeyPatch, previous: str | None
) -> None:
    if previous is None:
        monkeypatch.delenv("GAMEXRAY_GUI_CONFIG_PATH", raising=False)
    else:
        monkeypatch.setenv("GAMEXRAY_GUI_CONFIG_PATH", previous)
    before = dict(os.environ)

    env = create_test_environment()

    assert Path(env["GAMEXRAY_GUI_CONFIG_PATH"]).parent == Path(
        env["GAMEXRAY_CACHE_DIR"]
    )
    assert env["GAMEXRAY_GUI_CONFIG_PATH"] != before.get("GAMEXRAY_GUI_CONFIG_PATH")
    assert not Path(env["GAMEXRAY_GUI_CONFIG_PATH"]).exists()
    assert dict(os.environ) == before


class _SessionConfig:
    def __init__(self) -> None:
        self.cleanups = []

    def add_cleanup(self, callback) -> None:
        self.cleanups.append(callback)


def _repository_conftest() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("release_gui_conftest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("previous", [None, "", "caller-gui-profile.json"])
def test_direct_pytest_installs_private_gui_profile_and_restores_exact_env(
    monkeypatch: pytest.MonkeyPatch, previous: str | None
) -> None:
    if previous is None:
        monkeypatch.delenv("GAMEXRAY_GUI_CONFIG_PATH", raising=False)
    else:
        monkeypatch.setenv("GAMEXRAY_GUI_CONFIG_PATH", previous)
    before = dict(os.environ)
    session = _SessionConfig()
    try:
        _repository_conftest().pytest_configure(session)
        assert Path(os.environ["GAMEXRAY_GUI_CONFIG_PATH"]).parent == Path(
            os.environ["GAMEXRAY_CACHE_DIR"]
        )
        assert os.environ["GAMEXRAY_GUI_CONFIG_PATH"] != previous
    finally:
        for cleanup in reversed(session.cleanups):
            cleanup()

    assert dict(os.environ) == before

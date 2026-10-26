"""Keep repository pytest sessions away from the caller's runtime assets."""

from __future__ import annotations

import os

import pytest

from gametool.dev_test import create_test_environment


def pytest_configure(config: pytest.Config) -> None:
    previous = os.environ.get("GAMEXRAY_CACHE_DIR")
    try:
        env = create_test_environment()
    except OSError as error:
        raise pytest.UsageError(f"无法创建隔离测试缓存: {error}") from error

    def restore_environment() -> None:
        if previous is None:
            os.environ.pop("GAMEXRAY_CACHE_DIR", None)
        else:
            os.environ["GAMEXRAY_CACHE_DIR"] = previous

    config.add_cleanup(restore_environment)
    os.environ["GAMEXRAY_CACHE_DIR"] = env["GAMEXRAY_CACHE_DIR"]

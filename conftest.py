"""Keep repository pytest sessions away from the caller's runtime assets."""

from __future__ import annotations

import os

import pytest

from gametool.dev_test import create_test_environment


def pytest_configure(config: pytest.Config) -> None:
    keys = ("GAMEXRAY_CACHE_DIR", "GAMEXRAY_GUI_CONFIG_PATH")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        env = create_test_environment()
    except OSError as error:
        raise pytest.UsageError(f"无法创建隔离测试缓存: {error}") from error

    def restore_environment() -> None:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    config.add_cleanup(restore_environment)
    for key in keys:
        os.environ[key] = env[key]

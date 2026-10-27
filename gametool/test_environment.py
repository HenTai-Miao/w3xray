"""Private test cache allocation shared by runners and pytest scope policy."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

from .cache_root import gamexray_cache_root


def create_test_environment() -> dict[str, str]:
    """Give a test process a fresh cache without changing the caller's env."""
    temporary = Path(tempfile.gettempdir()).resolve()
    repository = Path(__file__).resolve().parents[1]
    caller_cache = gamexray_cache_root().resolve()
    if temporary.is_relative_to(repository):
        raise OSError("系统临时目录位于仓库内，请将 TMPDIR/TMP/TEMP 设到仓库外。")
    if temporary.is_relative_to(caller_cache):
        raise OSError(
            "系统临时目录位于调用方缓存内，请将 TMPDIR/TMP/TEMP 设到该缓存外。"
        )
    cache = tempfile.mkdtemp(prefix="gamexray-test-cache-", dir=temporary)
    env = dict(os.environ)
    env["GAMEXRAY_CACHE_DIR"] = str(Path(cache).resolve())
    env["GAMEXRAY_GUI_CONFIG_PATH"] = str(Path(cache).resolve() / "gui-config.json")
    return env

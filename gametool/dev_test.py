"""Windows-safe project test runner."""

from __future__ import annotations

import subprocess
import sys
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from .cache_root import gamexray_cache_root

DEFAULT_PYTEST_ARGS: Final = ("-q",)


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
    return env


def build_pytest_module_command(
    args: Sequence[str],
    *,
    python_executable: str = sys.executable,
) -> tuple[str, ...]:
    """Build a pytest command that avoids console-script launchers."""
    pytest_args = tuple(args) if args else DEFAULT_PYTEST_ARGS
    return (python_executable, "-m", "pytest", *pytest_args)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `uv run gamexray-test`."""
    args = tuple(sys.argv[1:] if argv is None else argv)
    command = build_pytest_module_command(args)
    try:
        env = create_test_environment()
    except OSError as error:
        print(f"gamexray-test: 无法创建隔离测试缓存: {error}", file=sys.stderr)
        return 2
    return subprocess.run(command, check=False, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())

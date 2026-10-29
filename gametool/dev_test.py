"""Windows-safe project test runner."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from .test_environment import create_test_environment as create_test_environment

DEFAULT_PYTEST_ARGS: Final = ("-q",)


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
    from .test_scope import ScopeRequestError, prepare_test_scope

    args = tuple(sys.argv[1:] if argv is None else argv)
    try:
        request = prepare_test_scope(args)
    except ScopeRequestError as error:
        print(f"gamexray-test: {error}", file=sys.stderr)
        return 2
    try:
        env = create_test_environment()
        env.update(request.environment)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
    except OSError as error:
        print(f"gamexray-test: 无法创建隔离测试缓存: {error}", file=sys.stderr)
        return 2
    arguments = request.arguments
    options = arguments[: arguments.index("--")] if "--" in arguments else arguments
    if not any(
        option == "--basetemp" or option.startswith("--basetemp=") for option in options
    ):
        # pytest's default user-wide pytest-current link can belong to an
        # elevated or concurrent session. Keep its cleanup inside this fresh,
        # private allocation; the caller's cache and shared temp are untouched.
        arguments = (
            "--basetemp",
            str(Path(env["GAMEXRAY_CACHE_DIR"]) / "pytest"),
            *arguments,
        )
    command = build_pytest_module_command(("-p", "gametool.test_scope", *arguments))
    return subprocess.run(command, check=False, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())

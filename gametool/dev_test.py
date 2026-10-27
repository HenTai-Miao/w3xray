"""Windows-safe project test runner."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
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
    command = build_pytest_module_command(
        ("-p", "gametool.test_scope", *request.arguments)
    )
    try:
        env = create_test_environment()
        env.update(request.environment)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
    except OSError as error:
        print(f"gamexray-test: 无法创建隔离测试缓存: {error}", file=sys.stderr)
        return 2
    return subprocess.run(command, check=False, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())

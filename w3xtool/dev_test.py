"""Windows-safe project test runner."""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from typing import Final

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
    """CLI entrypoint for `uv run w3xray-test`."""
    args = tuple(sys.argv[1:] if argv is None else argv)
    command = build_pytest_module_command(args)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

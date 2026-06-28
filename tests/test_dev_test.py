"""Windows-safe test runner command tests."""
from __future__ import annotations

import subprocess
import sys

from w3xtool.dev_test import build_pytest_module_command


def test_build_pytest_module_command_defaults_to_quiet_full_suite() -> None:
    # Given: no explicit pytest arguments.
    args: tuple[str, ...] = ()

    # When: the test command is built.
    command = build_pytest_module_command(args, python_executable="python")

    # Then: pytest is launched as a Python module, not through its console script.
    assert command == ("python", "-m", "pytest", "-q")


def test_dev_test_module_can_forward_to_pytest_without_console_script() -> None:
    # Given: the project test runner is invoked as a module.
    command = [sys.executable, "-m", "w3xtool.dev_test", "--version"]

    # When: it forwards to pytest.
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )

    # Then: pytest answers without going through the pytest executable trampoline.
    assert "pytest" in result.stdout.lower()

"""Cross-platform static quality gate for the maintained changed-path set."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shlex
import subprocess
import sys

from .quality_paths import STRICT_PATHS


@dataclass(frozen=True, slots=True)
class QualityCommand:
    """One labeled module command executed without a shell."""

    tool: str
    module: str
    argv: tuple[str, ...]


def build_quality_commands(
    *,
    python_executable: str = sys.executable,
) -> tuple[QualityCommand, ...]:
    """Build the three commands from one immutable path authority."""
    return (
        QualityCommand(
            "ruff-check",
            "ruff",
            (python_executable, "-m", "ruff", "check", *STRICT_PATHS),
        ),
        QualityCommand(
            "ruff-format",
            "ruff",
            (python_executable, "-m", "ruff", "format", "--check", *STRICT_PATHS),
        ),
        QualityCommand(
            "basedpyright",
            "basedpyright",
            (
                python_executable,
                "-m",
                "basedpyright",
                "--level",
                "error",
                *STRICT_PATHS,
            ),
        ),
    )


def run_quality_commands(commands: tuple[QualityCommand, ...]) -> int:
    """Echo and execute commands, stopping at the first failure."""
    environment = dict(os.environ)
    environment["PYRIGHT_DISABLE_GITHUB_ACTIONS_OUTPUT"] = "1"
    for command in commands:
        print(f"[{command.tool}] {shlex.join(command.argv)}", flush=True)
        result = subprocess.run(
            command.argv,
            check=False,
            shell=False,
            env=environment,
        )
        if result.returncode:
            return result.returncode
    return 0


def main() -> int:
    """Run the maintained quality gate in the active Python environment."""
    return run_quality_commands(build_quality_commands())


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "STRICT_PATHS",
    "QualityCommand",
    "build_quality_commands",
    "main",
    "run_quality_commands",
)

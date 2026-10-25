"""Cross-platform static quality gate for the maintained changed-path set.

四步语义：风格（ruff check）→ 格式（ruff format）→ 类型（basedpyright）→
转义字面量（syntax-warnings，AST 级扫描无效转义/heredoc 降级残留）。
进程级缓存的失效键必须含内容指纹（见 pack_query_cli._ROWS_CACHE——仅
(mtime, size) 在 Windows 15ms 粒度下会返回旧缓存，曾致测试偶发失败）。
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
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
    path_start: int | None = None


def _windows_units(argv: tuple[str, ...]) -> int:
    """CreateProcessW counts UTF-16 units, including the terminating NUL."""
    return (
        len(subprocess.list2cmdline(argv).encode("utf-16-le", errors="surrogatepass"))
        // 2
        + 1
    )


def _windows_limit(command: QualityCommand) -> int:
    """Measure the installed tool launcher's forwarded command prefix as well."""
    if command.path_start is None:
        return 32767
    prefix = command.argv[: command.path_start]
    forwarded = prefix
    if command.module == "ruff":
        from ruff import find_ruff_bin

        forwarded = (str(find_ruff_bin()), *command.argv[3 : command.path_start])
    elif command.module == "basedpyright":
        based = importlib.util.find_spec("basedpyright")
        node = importlib.util.find_spec("nodejs_wheel.executable")
        if based is None or based.origin is None or node is None or node.origin is None:
            raise ValueError(
                "无法定位 basedpyright/Node 安装路径；请运行 uv sync --dev"
            )
        forwarded = (
            str(Path(node.origin).parent / "node.exe"),
            str(Path(based.origin).parent / "index.js"),
            *command.argv[3 : command.path_start],
        )
    return 32767 - max(0, _windows_units(forwarded) - _windows_units(prefix))


def _command_batches(
    command: QualityCommand, *, windows_units: int | None = None
) -> tuple[tuple[str, ...], ...]:
    if windows_units is None or command.path_start is None:
        return (command.argv,)
    prefix = command.argv[: command.path_start]
    prefix_size = _windows_units(prefix)
    batches: list[tuple[str, ...]] = []
    paths: list[str] = []
    size = prefix_size
    for path in command.argv[command.path_start :]:
        extra = _windows_units((path,))
        if prefix_size + extra > windows_units:
            raise ValueError(f"单个检查路径超出 Windows 命令行容量，无法分批: {path}")
        if paths and size + extra > windows_units:
            batches.append((*prefix, *paths))
            paths, size = [], prefix_size
        paths.append(path)
        size += extra
    if paths or not batches:
        batches.append((*prefix, *paths))
    return tuple(batches)


def build_quality_commands(
    *,
    python_executable: str = sys.executable,
) -> tuple[QualityCommand, ...]:
    """Build the four commands (风格/格式/类型/转义扫描) from one path authority."""
    return (
        QualityCommand(
            "ruff-check",
            "ruff",
            (python_executable, "-m", "ruff", "check", *STRICT_PATHS),
            path_start=4,
        ),
        QualityCommand(
            "ruff-format",
            "ruff",
            (python_executable, "-m", "ruff", "format", "--check", *STRICT_PATHS),
            path_start=5,
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
            path_start=5,
        ),
        QualityCommand(
            "syntax-warnings",
            "tools.check_syntax_warnings",
            (
                python_executable,
                "-m",
                "tools.check_syntax_warnings",
                *STRICT_PATHS,
            ),
            path_start=3,
        ),
    )


def run_quality_commands(commands: tuple[QualityCommand, ...]) -> int:
    """Echo and execute commands, stopping at the first failure."""
    environment = dict(os.environ)
    environment["PYRIGHT_DISABLE_GITHUB_ACTIONS_OUTPUT"] = "1"
    for command in commands:
        try:
            # Documented OS boundary, not a ceiling on checked files.
            batches = _command_batches(
                command,
                windows_units=_windows_limit(command) if os.name == "nt" else None,
            )
        except ValueError as exc:
            print(f"[{command.tool}] {exc}", file=sys.stderr)
            return 2
        for number, argv in enumerate(batches, 1):
            prefix = (
                argv[: command.path_start] if command.path_start is not None else argv
            )
            count = (
                f"; {len(argv) - command.path_start} files"
                if command.path_start is not None
                else ""
            )
            print(
                f"[{command.tool} {number}/{len(batches)}] {shlex.join(prefix)}{count}",
                flush=True,
            )
            result = subprocess.run(argv, check=False, shell=False, env=environment)
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

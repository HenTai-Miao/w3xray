"""Project-local PyInstaller dist builder."""
from __future__ import annotations

import platform
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

APP_NAME: Final = "魔兽地图提取器"
SPEC_FILE: Final = f"{APP_NAME}.spec"


@dataclass(frozen=True, slots=True)
class DistBuildConfig:
    """Stable project paths used by the dist build."""

    project_root: Path
    spec_path: Path
    dist_path: Path
    work_path: Path
    clean: bool


@dataclass(frozen=True, slots=True)
class DistCliOptions:
    """CLI options for the dist builder."""

    dry_run: bool = False
    clean: bool = True


@dataclass(frozen=True, slots=True)
class ProjectRootNotFoundError(RuntimeError):
    """Raised when the dist builder cannot find this repository root."""

    start: Path

    def __str__(self) -> str:
        return f"找不到项目根目录：从 {self.start} 向上没有发现 {SPEC_FILE}"


@dataclass(frozen=True, slots=True)
class DistSpecMissingError(RuntimeError):
    """Raised when the PyInstaller spec file is missing."""

    spec_path: Path

    def __str__(self) -> str:
        return f"找不到 PyInstaller spec 文件：{self.spec_path}"


@dataclass(frozen=True, slots=True)
class DistArgumentError(ValueError):
    """Raised when a CLI option is not supported."""

    argument: str

    def __str__(self) -> str:
        return f"不支持的参数：{self.argument}"


class DistHelpRequested(Exception):
    """Raised internally when the user asks for CLI help."""


def find_project_root(start: Path) -> Path:
    """Find the repository root that owns the PyInstaller spec."""
    first = start if start.is_dir() else start.parent
    for candidate in (first, *first.parents):
        if (
            (candidate / SPEC_FILE).is_file()
            and (candidate / "pyproject.toml").is_file()
        ):
            return candidate
    raise ProjectRootNotFoundError(start=start)


def default_dist_config(project_root: Path | None = None) -> DistBuildConfig:
    """Build the default dist config for this checkout."""
    if project_root is None:
        try:
            root = find_project_root(Path.cwd())
        except ProjectRootNotFoundError:
            root = find_project_root(Path(__file__).resolve())
    else:
        root = project_root
    return DistBuildConfig(
        project_root=root,
        spec_path=root / SPEC_FILE,
        dist_path=root / "dist",
        work_path=root / "build" / "pyinstaller",
        clean=True,
    )


def build_pyinstaller_command(
    config: DistBuildConfig,
    *,
    python_executable: str = sys.executable,
) -> tuple[str, ...]:
    """Return the PyInstaller command without executing it."""
    clean_args = ("--clean",) if config.clean else ()
    return (
        python_executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        *clean_args,
        "--distpath",
        str(config.dist_path),
        "--workpath",
        str(config.work_path),
        str(config.spec_path),
    )


def expected_artifact_path(config: DistBuildConfig, *, system: str | None = None) -> Path:
    """Return the executable path users should launch after a successful build."""
    app_dir = config.dist_path / APP_NAME
    current_system = system or platform.system()
    match current_system:
        case "Windows":
            return app_dir / f"{APP_NAME}.exe"
        case "Darwin" | "Linux":
            return app_dir / APP_NAME
        case _:
            return app_dir / APP_NAME


def parse_cli_options(argv: Sequence[str]) -> DistCliOptions:
    """Parse the tiny dist-builder CLI."""
    options = DistCliOptions()
    for argument in argv:
        match argument:
            case "--dry-run":
                options = replace(options, dry_run=True)
            case "--no-clean":
                options = replace(options, clean=False)
            case "--clean":
                options = replace(options, clean=True)
            case "-h" | "--help":
                raise DistHelpRequested()
            case unknown:
                raise DistArgumentError(argument=unknown)
    return options


def run_dist_build(config: DistBuildConfig, *, dry_run: bool = False) -> int:
    """Run PyInstaller for the configured project."""
    if not config.spec_path.is_file():
        raise DistSpecMissingError(spec_path=config.spec_path)
    command = build_pyinstaller_command(config)
    print("构建命令:")
    print(f"  {shlex.join(command)}")
    if dry_run:
        print("dry-run: 未执行 PyInstaller。")
        return 0
    result = subprocess.run(command, cwd=config.project_root, check=False)
    if result.returncode == 0:
        print("构建完成:")
        print(f"  当前平台产物: {expected_artifact_path(config)}")
        print(f"  Windows exe 路径: {expected_artifact_path(config, system='Windows')}")
    return result.returncode


def help_text() -> str:
    """Return CLI help for the dist builder."""
    return "\n".join(
        (
            "用法: uv run w3xray-dist [--dry-run] [--no-clean]",
            "",
            "选项:",
            "  --dry-run   只打印 PyInstaller 命令，不执行构建",
            "  --no-clean  不传递 PyInstaller --clean",
            "  -h, --help  显示帮助",
            "",
            "说明: PyInstaller 不是跨平台编译器；Windows .exe 需要在 Windows 上构建。",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `uv run w3xray-dist`."""
    try:
        options = parse_cli_options(tuple(sys.argv[1:] if argv is None else argv))
        config = replace(default_dist_config(), clean=options.clean)
        return run_dist_build(config, dry_run=options.dry_run)
    except DistHelpRequested:
        print(help_text())
        return 0
    except (DistArgumentError, DistSpecMissingError, ProjectRootNotFoundError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        print(help_text(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

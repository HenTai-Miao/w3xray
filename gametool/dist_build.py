"""Project-local Windows PyInstaller dist builder."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Final, assert_never

from .casclib_dist import CascLibDistError, validate_casclib_dist_assets
from .cli_output import configure_cli_output

APP_NAME: Final = "GameXRay 游戏档案透视器"
SPEC_FILE: Final = f"{APP_NAME}.spec"
BUILD_MODE_ENV: Final = "GAMEXRAY_PYINSTALLER_MODE"


class DistFormat(StrEnum):
    """Supported PyInstaller package topologies."""

    ONEDIR = "onedir"
    ONEFILE = "onefile"


@dataclass(frozen=True, slots=True)
class DistBuildConfig:
    """Stable project paths used by the dist build."""

    project_root: Path
    spec_path: Path
    dist_path: Path
    work_path: Path
    clean: bool
    format: DistFormat = DistFormat.ONEDIR


@dataclass(frozen=True, slots=True)
class DistCliOptions:
    """CLI options for the dist builder."""

    dry_run: bool = False
    clean: bool = True
    format: DistFormat = DistFormat.ONEDIR
    dist_path: Path | None = None
    work_path: Path | None = None


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


@dataclass(frozen=True, slots=True)
class DistPlatformError(RuntimeError):
    """Raised before a distribution build on an unsupported host."""

    system: str

    def __str__(self) -> str:
        return f"发行构建仅支持 Windows；当前平台：{self.system or '未知'}"


def _require_windows(system: str | None = None) -> None:
    current_system = platform.system() if system is None else system
    if current_system != "Windows":
        raise DistPlatformError(system=current_system)


class DistHelpRequested(Exception):
    """Raised internally when the user asks for CLI help."""


def find_project_root(start: Path) -> Path:
    """Find the repository root that owns the PyInstaller spec."""
    first = start if start.is_dir() else start.parent
    for candidate in (first, *first.parents):
        if (candidate / SPEC_FILE).is_file() and (
            candidate / "pyproject.toml"
        ).is_file():
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


def expected_artifact_path(
    config: DistBuildConfig, *, system: str | None = None
) -> Path:
    """Return the Windows executable path after a successful build."""
    _require_windows(system)
    match config.format:
        case DistFormat.ONEFILE:
            app_dir = config.dist_path
        case DistFormat.ONEDIR:
            app_dir = config.dist_path / APP_NAME
        case unreachable:
            assert_never(unreachable)
    return app_dir / f"{APP_NAME}.exe"


def parse_cli_options(argv: Sequence[str]) -> DistCliOptions:
    """Parse the tiny dist-builder CLI."""
    options = DistCliOptions()
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument in {"--distpath", "--workpath"}:
            index += 1
            if index >= len(argv) or not argv[index] or argv[index].startswith("--"):
                raise DistArgumentError(argument=f"{argument} 需要目录路径")
            path = Path(argv[index]).expanduser().absolute()
            options = (
                replace(options, dist_path=path)
                if argument == "--distpath"
                else replace(options, work_path=path)
            )
            index += 1
            continue
        match (
            argument
        ):  # [OK: MATCH_OK] - unknown CLI strings become DistArgumentError.
            case "--dry-run":
                options = replace(options, dry_run=True)
            case "--no-clean":
                options = replace(options, clean=False)
            case "--clean":
                options = replace(options, clean=True)
            case "--onefile":
                options = replace(options, format=DistFormat.ONEFILE)
            case "-h" | "--help":
                raise DistHelpRequested()
            case unknown:
                raise DistArgumentError(argument=unknown)
        index += 1
    return options


def run_dist_build(config: DistBuildConfig, *, dry_run: bool = False) -> int:
    """Run PyInstaller for the configured Windows project."""
    _require_windows()
    if not config.spec_path.is_file():
        raise DistSpecMissingError(spec_path=config.spec_path)
    validate_casclib_dist_assets(config.project_root)
    command = build_pyinstaller_command(config)
    print("构建命令:")
    rendered_command = "& " + subprocess.list2cmdline(command)
    print(f"  {rendered_command}")
    if dry_run:
        print("dry-run: 未执行 PyInstaller。")
        return 0
    result = subprocess.run(
        command,
        cwd=config.project_root,
        check=False,
        env={**os.environ, BUILD_MODE_ENV: config.format.value},
    )
    if result.returncode == 0:
        print("构建完成:")
        print(f"  Windows exe 路径: {expected_artifact_path(config)}")
    return result.returncode


def help_text() -> str:
    """Return CLI help for the dist builder."""
    return "\n".join(
        (
            "用法: uv run gamexray-dist [--dry-run] [--no-clean] [--onefile]",
            "                         [--distpath <目录>] [--workpath <目录>]",
            "",
            "选项:",
            "  --dry-run   只打印 PyInstaller 命令，不执行构建",
            "  --no-clean  不传递 PyInstaller --clean",
            "  --onefile   构建单文件可执行程序（默认为 onedir）",
            "  --distpath  显式指定发行产物目录（可放在仓库外）",
            "  --workpath  显式指定临时构建目录（可放在仓库外）",
            "  -h, --help  显示帮助",
            "",
            "说明: 发行构建仅支持 Windows，生成 Windows .exe。",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `uv run gamexray-dist`."""
    configure_cli_output()
    try:
        options = parse_cli_options(tuple(sys.argv[1:] if argv is None else argv))
        _require_windows()
        config = replace(
            default_dist_config(),
            clean=options.clean,
            format=options.format,
        )
        config = replace(
            config,
            dist_path=options.dist_path or config.dist_path,
            work_path=options.work_path or config.work_path,
        )
        return run_dist_build(config, dry_run=options.dry_run)
    except DistHelpRequested:
        print(help_text())
        return 0
    except (
        CascLibDistError,
        DistArgumentError,
        DistPlatformError,
        DistSpecMissingError,
        ProjectRootNotFoundError,
    ) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        print(help_text(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

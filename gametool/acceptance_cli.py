"""CLI boundary for source and packaged acceptance execution."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from .acceptance_runner import (
    AcceptanceConfig,
    AcceptanceStatus,
    prepare_acceptance_report,
    run_acceptance,
    write_acceptance_report,
)
from .dev_test import create_test_environment
from .presentation_safety import format_user_exception
from .windows_output_paths import validate_output_root


@contextmanager
def _private_acceptance_environment() -> Iterator[None]:
    """Keep acceptance memo and GUI configuration away from caller assets."""
    environment = create_test_environment()
    names = ("GAMEXRAY_CACHE_DIR", "GAMEXRAY_GUI_CONFIG_PATH")
    saved = {
        name: os.environ.get(name) for name in (*names, "GAMEXRAY_MATERIALIZE_WORKERS")
    }
    try:
        for name in names:
            os.environ[name] = environment.get(
                name, str(Path(environment["GAMEXRAY_CACHE_DIR"]) / "gui-config.json")
            )
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def run_acceptance_cli(argv: tuple[str, ...]) -> int:
    """Parse requested acceptance checks and persist their JSON evidence."""
    parser = argparse.ArgumentParser(prog="gamexray acceptance")
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument(
        "--war3-dir",
        type=_war3_dir,
        default=_environment_war3_dir(),
        help="可选：真实 CASC 安装目录；未提供时不请求此检查",
    )
    parser.add_argument("--output", required=True, type=_output_path)
    parser.add_argument("--report", type=_output_path)
    parser.add_argument("--repeat", type=_positive_int, default=5)
    parser.add_argument("--require-windows", action="store_true")
    parser.add_argument("--no-gui", action="store_true")
    args = parser.parse_args(argv)
    report_path = args.report or args.output / "acceptance.json"
    config = AcceptanceConfig(
        map_path=args.map,
        campaign_path=args.campaign,
        war3_dir=args.war3_dir,
        output_dir=args.output,
        repeat_count=args.repeat,
        run_gui=not args.no_gui,
        require_windows=args.require_windows,
    )
    try:
        report_path = prepare_acceptance_report(report_path)
        with _private_acceptance_environment():
            report = run_acceptance(config)
        write_acceptance_report(report, report_path)
    except (OSError, ValueError) as exc:
        print(
            "验收无法完成："
            + format_user_exception(exc, paths=(str(report_path),))
            + "；请选择新的报告文件和可写的普通输出目录。",
            file=sys.stderr,
        )
        return 2
    for check in report.checks:
        print(f"[{check.status.value.upper()}] {check.name}: {check.detail}")
    for check in report.not_requested:
        print(f"[NOT_REQUESTED] {check.name}: {check.reason}")
    print(
        "COVERAGE requested: "
        f"complete={str(report.requested_coverage_complete).lower()}; "
        f"real_casc_verified={str(report.real_casc_verified).lower()}"
    )
    print(f"REPORT {report_path}")
    return 0 if report.overall_status is AcceptanceStatus.PASS else 1


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _output_path(value: str) -> Path:
    """Validate Windows spellings before Path can normalize their separators."""
    try:
        validate_output_root(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return Path(value)


def _war3_dir(value: str) -> Path:
    if not value.strip():
        raise argparse.ArgumentTypeError(
            "--war3-dir requires a non-empty directory path"
        )
    return Path(value)


def _environment_war3_dir() -> Path | None:
    value = os.getenv("GAMEXRAY_WAR3_DIR")
    return Path(value) if value and value.strip() else None

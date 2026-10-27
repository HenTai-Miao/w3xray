"""CLI boundary for source and packaged acceptance execution."""

from __future__ import annotations

import argparse
import os
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from .acceptance_runner import (
    AcceptanceConfig,
    AcceptanceStatus,
    run_acceptance,
    write_acceptance_report,
)
from .dev_test import create_test_environment


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
    """Parse acceptance arguments, run all lanes, and persist JSON evidence."""
    parser = argparse.ArgumentParser(prog="gamexray acceptance")
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--war3-dir", type=Path, default=_environment_war3_dir())
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
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
    with _private_acceptance_environment():
        report = run_acceptance(config)
    write_acceptance_report(report, report_path)
    for check in report.checks:
        print(f"[{check.status.value.upper()}] {check.name}: {check.detail}")
    print(f"REPORT {report_path}")
    return 0 if report.overall_status is AcceptanceStatus.PASS else 1


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _environment_war3_dir() -> Path | None:
    value = os.getenv("GAMEXRAY_WAR3_DIR")
    return Path(value) if value else None

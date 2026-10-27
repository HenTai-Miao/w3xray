"""Strict UTF-8 parsing for every external integrity CLI path and label."""

from __future__ import annotations

from pathlib import Path

import pytest

from gametool.integrity_cli import run_integrity_cli
from gametool.integrity_cli_options import (
    IntegrityCliOptionError,
    parse_integrity_cli_options,
)


@pytest.mark.parametrize(
    "argv",
    (
        ("snapshot", "--root", "label-\udcff=/root", "--output", "/report"),
        ("snapshot", "--root", "root=/root-\udcff", "--output", "/report"),
        ("snapshot", "--root", "root=/root", "--output", "/report-\udcff"),
        ("verify", "--snapshot", "/snapshot-\udcff"),
        (
            "retained-cache",
            "--active-root",
            "/active-\udcff",
            "--output",
            "/report",
        ),
        (
            "retained-cache",
            "--active-root",
            "/active",
            "--output",
            "/report-\udcff",
        ),
    ),
)
def test_integrity_options_reject_surrogate_external_values(
    argv: tuple[str, ...],
) -> None:
    with pytest.raises(IntegrityCliOptionError):
        parse_integrity_cli_options(argv)


def test_snapshot_maps_a_surrogate_label_to_code_two(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    output = tmp_path / "snapshot.json"

    code = run_integrity_cli(
        (
            "snapshot",
            "--root",
            f"label-\udcff={root}",
            "--output",
            str(output),
        )
    )

    assert code == 2
    assert not output.exists()

"""Strict UTF-8 parsing for every external integrity CLI path and label."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from tests.retained_integrity_fixture import active_cache
from w3xtool.integrity_cli import run_integrity_cli
from w3xtool.integrity_cli_options import (
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


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="requires a filesystem that accepts undecodable byte names",
)
@pytest.mark.parametrize("location", ("root", "ancestor"))
def test_snapshot_maps_a_raw_byte_explicit_root_to_code_two(
    tmp_path: Path,
    location: str,
) -> None:
    raw_component = os.path.join(os.fsencode(tmp_path), b"invalid-\xff")
    os.mkdir(raw_component)
    raw_root = raw_component
    if location == "ancestor":
        raw_root = os.path.join(raw_component, b"root")
        os.mkdir(raw_root)
    root = Path(os.fsdecode(raw_root))
    output = tmp_path / "snapshot.json"

    code = run_integrity_cli(
        ("snapshot", "--root", f"root={root}", "--output", str(output))
    )

    assert code == 2
    assert not output.exists()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="requires a filesystem that accepts undecodable byte names",
)
def test_retained_cache_maps_a_raw_byte_ancestor_to_code_two(
    tmp_path: Path,
) -> None:
    staged = active_cache(tmp_path / "staged")
    raw_parent = os.path.join(os.fsencode(tmp_path), b"invalid-\xff")
    os.mkdir(raw_parent)
    raw_active = os.path.join(raw_parent, b"active")
    os.rename(os.fsencode(staged), raw_active)
    active = Path(os.fsdecode(raw_active))
    output = tmp_path / "report.json"

    code = run_integrity_cli(
        (
            "retained-cache",
            "--active-root",
            str(active),
            "--output",
            str(output),
        )
    )

    assert code == 2
    assert not output.exists()

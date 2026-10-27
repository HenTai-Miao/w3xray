"""Base integrity snapshot/verify CLI safety and exit-code contracts."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

import main as entrypoint
from gametool import integrity_cli as cli
from gametool import single_instance
from gametool.integrity_cli import run_integrity_cli


@pytest.mark.parametrize(
    "argv",
    (
        (),
        ("unknown",),
        ("snapshot",),
        ("snapshot", "--root", "missing-separator", "--output", "out"),
        ("verify",),
        ("verify", "--snapshot", "one", "--snapshot", "two"),
    ),
)
def test_integrity_cli_returns_two_for_inexact_requests(
    argv: tuple[str, ...],
) -> None:
    assert run_integrity_cli(argv) == 2


def test_integrity_cli_returns_two_for_invalid_snapshot_payload(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "invalid.json"
    snapshot.write_text("{}", encoding="utf-8")

    assert run_integrity_cli(("verify", "--snapshot", str(snapshot))) == 2


def test_main_rejects_retired_integrity_without_starting_gui(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        cli,
        "run_integrity_cli",
        lambda argv: received.append(argv) or 7,
    )
    monkeypatch.setattr(
        single_instance,
        "ensure_single_instance",
        lambda: (_ for _ in ()).throw(AssertionError("GUI fallback reached")),
    )
    argv = ("main.py", "integrity", "verify", "--snapshot", "before.json")
    monkeypatch.setattr(sys, "argv", list(argv))

    with pytest.raises(SystemExit) as caught:
        entrypoint.main()

    assert caught.value.code == 2
    assert received == []
    output = capsys.readouterr()
    assert not output.out
    assert "live-report inspect" in output.err
    assert "live-report diff" in output.err
    assert "pack-query" in output.err

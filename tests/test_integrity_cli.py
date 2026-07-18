"""Base integrity snapshot/verify CLI safety and exit-code contracts."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

import main as entrypoint
from w3xtool import integrity_cli as cli
from w3xtool import single_instance
from w3xtool.integrity_cli import run_integrity_cli


def test_integrity_cli_snapshots_then_verifies_exact_roots(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "maps"
    root.mkdir()
    (root / "a.w3x").write_bytes(b"map")
    snapshot = tmp_path / "before.json"
    assert (
        run_integrity_cli(
            ("snapshot", "--root", f"maps={root}", "--output", str(snapshot))
        )
        == 0
    )
    assert run_integrity_cli(("verify", "--snapshot", str(snapshot))) == 0
    assert "完整性验证通过" in capsys.readouterr().out


def test_integrity_cli_returns_one_for_a_changed_input(tmp_path: Path) -> None:
    root = tmp_path / "history"
    root.mkdir()
    source = root / "state.json"
    source.write_text("first", encoding="utf-8")
    snapshot = tmp_path / "before.json"
    assert (
        run_integrity_cli(
            ("snapshot", "--root", f"history={root}", "--output", str(snapshot))
        )
        == 0
    )
    source.write_text("second", encoding="utf-8")

    code = run_integrity_cli(("verify", "--snapshot", str(snapshot)))

    assert code == 1


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


def test_integrity_cli_rejects_output_inside_snapshotted_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    output = root / "snapshot.json"

    code = run_integrity_cli(
        ("snapshot", "--root", f"root={root}", "--output", str(output))
    )

    assert code == 2
    assert not output.exists()


def test_integrity_cli_returns_two_for_invalid_snapshot_payload(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "invalid.json"
    snapshot.write_text("{}", encoding="utf-8")

    assert run_integrity_cli(("verify", "--snapshot", str(snapshot))) == 2


def test_main_dispatches_integrity_without_starting_gui(
    monkeypatch: pytest.MonkeyPatch,
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

    assert caught.value.code == 7
    assert received == [argv[2:]]

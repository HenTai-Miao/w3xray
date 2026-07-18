"""Protected ancestry and publication namespace contracts for integrity output."""

from __future__ import annotations

from collections.abc import Callable
import errno
from pathlib import Path

import pytest

from tests.retained_integrity_fixture import active_cache, backup, retained, stage
from w3xtool import integrity_output as output_api
from w3xtool import safe_output_publication as publication_api
from w3xtool.integrity_cli import run_integrity_cli


def _snapshot_argv(root: Path, output: Path) -> tuple[str, ...]:
    return ("snapshot", "--root", f"root={root}", "--output", str(output))


def _retained_argv(active: Path, output: Path) -> tuple[str, ...]:
    return (
        "retained-cache",
        "--active-root",
        str(active),
        "--output",
        str(output),
    )


def test_snapshot_output_rejects_a_symlink_ancestor_into_the_input(
    tmp_path: Path,
) -> None:
    protected = tmp_path / "protected"
    root = protected / "input"
    root.mkdir(parents=True)
    (root / "payload").write_bytes(b"evidence")
    alias = tmp_path / "alias"
    alias.symlink_to(protected, target_is_directory=True)
    output = alias / "input" / "snapshot.json"

    code = run_integrity_cli(_snapshot_argv(root, output))

    assert code == 2
    assert not (root / "snapshot.json").exists()


def test_retained_output_rejects_a_symlink_ancestor_into_the_active_cache(
    tmp_path: Path,
) -> None:
    active = active_cache(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(active.parent, target_is_directory=True)
    output = alias / active.name / "report.json"

    code = run_integrity_cli(_retained_argv(active, output))

    assert code == 2
    assert not (active / "report.json").exists()


@pytest.mark.parametrize("reserved", ("retained", "stage", "backup"))
def test_retained_output_rejects_nonexistent_reserved_names(
    tmp_path: Path,
    reserved: str,
) -> None:
    active = active_cache(tmp_path)
    if reserved == "retained":
        output = retained(active, "7", "failed-output")
    elif reserved == "stage":
        output = stage(active, "7")
    else:
        output = backup(active, "7")

    code = run_integrity_cli(_retained_argv(active, output))

    assert code == 2
    assert not output.exists()


def test_snapshot_rejects_output_parent_replacement_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected = tmp_path / "protected"
    root = protected / "input"
    root.mkdir(parents=True)
    (root / "payload").write_bytes(b"evidence")
    output_root = tmp_path / "output"
    output_parent = output_root / "input"
    output_parent.mkdir(parents=True)
    moved = tmp_path / "moved-output"
    output = output_parent / "snapshot.json"
    original = output_api.BoundIntegrityOutput._publication_error
    checks = 0
    replaced = False

    def replace_parent_before_proof(
        bound: output_api.BoundIntegrityOutput,
        require_protected: Callable[[], None] | None,
    ) -> str | None:
        nonlocal checks, replaced
        checks += 1
        if checks == 2:
            replaced = True
            output_root.rename(moved)
            output_root.symlink_to(protected, target_is_directory=True)
        return original(bound, require_protected)

    monkeypatch.setattr(
        output_api.BoundIntegrityOutput,
        "_publication_error",
        replace_parent_before_proof,
    )
    try:
        code = run_integrity_cli(_snapshot_argv(root, output))
    finally:
        if output_root.is_symlink():
            output_root.unlink()
            moved.rename(output_root)

    assert code == 2
    assert not output.exists()
    assert not (root / "snapshot.json").exists()


def test_retained_publication_failure_writes_no_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = active_cache(tmp_path)
    output = tmp_path / "report.json"

    def fail_claim(
        _parent_descriptor: int,
        _source: str,
        _destination: str,
        _identity: tuple[int, int],
    ) -> None:
        raise OSError(errno.EIO, "publication failed")

    monkeypatch.setattr(publication_api, "claim_name", fail_claim)

    assert run_integrity_cli(_retained_argv(active, output)) == 2
    assert not output.exists()


def test_retained_rejects_relevant_namespace_insertion_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = active_cache(tmp_path)
    output = tmp_path / "report.json"
    inserted = stage(active, "8")
    original = output_api.BoundIntegrityOutput._publication_error
    checks = 0
    mutated = False

    def insert_stage_before_proof(
        bound: output_api.BoundIntegrityOutput,
        require_protected: Callable[[], None] | None,
    ) -> str | None:
        nonlocal checks, mutated
        checks += 1
        if checks == 2:
            mutated = True
            inserted.mkdir()
        return original(bound, require_protected)

    monkeypatch.setattr(
        output_api.BoundIntegrityOutput,
        "_publication_error",
        insert_stage_before_proof,
    )

    code = run_integrity_cli(_retained_argv(active, output))

    assert code == 2
    assert not output.exists()
    assert inserted.is_dir()

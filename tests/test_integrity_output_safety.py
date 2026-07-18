"""Protected ancestry and publication namespace contracts for integrity output."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from tests.retained_integrity_fixture import active_cache, backup, retained, stage
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
    original_link = os.link
    replaced = False

    def replace_parent_before_link(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal replaced
        if not replaced:
            replaced = True
            output_root.rename(moved)
            output_root.symlink_to(protected, target_is_directory=True)
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(os, "link", replace_parent_before_link)
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

    def fail_link(
        _source: str,
        _destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        del src_dir_fd, dst_dir_fd, follow_symlinks
        raise OSError(errno.EIO, "publication failed")

    monkeypatch.setattr(os, "link", fail_link)

    assert run_integrity_cli(_retained_argv(active, output)) == 2
    assert not output.exists()


def test_retained_rejects_relevant_namespace_insertion_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = active_cache(tmp_path)
    output = tmp_path / "report.json"
    inserted = stage(active, "8")
    original_link = os.link
    mutated = False

    def insert_stage_before_link(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal mutated
        if not mutated:
            mutated = True
            inserted.mkdir()
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(os, "link", insert_stage_before_link)

    code = run_integrity_cli(_retained_argv(active, output))

    assert code == 2
    assert not output.exists()
    assert inserted.is_dir()

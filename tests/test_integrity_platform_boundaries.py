"""Descriptor capability, ancestry, and filename encoding boundaries."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from tests.retained_integrity_fixture import active_cache
from w3xtool import integrity_path_binding as binding_api
from w3xtool import integrity_snapshot_tree as tree_api
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


def test_retained_cache_rejects_an_ancestor_swap_without_a_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder = tmp_path / "holder"
    active = active_cache(holder / "branch")
    moved = tmp_path / "moved-holder"
    attacker_holder = tmp_path / "attacker-holder"
    _ = active_cache(attacker_holder / "branch")
    output = tmp_path / "report.json"
    original_open = os.open
    swapped = False

    def swap_ancestor_before_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        component_open = path == holder.name and dir_fd is not None
        old_full_path_open = os.fsdecode(path) == str(active.parent)
        if not swapped and (component_open or old_full_path_open):
            holder.rename(moved)
            holder.symlink_to(attacker_holder, target_is_directory=True)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_ancestor_before_open)
    try:
        code = run_integrity_cli(_retained_argv(active, output))
    finally:
        if holder.is_symlink():
            holder.unlink()
            moved.rename(holder)

    assert swapped
    assert code == 2
    assert not output.exists()


def test_snapshot_fails_closed_when_path_binding_capabilities_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "payload").write_bytes(b"evidence")
    output = tmp_path / "snapshot.json"
    monkeypatch.setattr(binding_api, "_PATH_BINDING_AVAILABLE", False, raising=False)

    code = run_integrity_cli(_snapshot_argv(root, output))

    assert code == 2
    assert not output.exists()


def test_snapshot_maps_not_implemented_descriptor_open_to_code_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    output = tmp_path / "snapshot.json"

    def unsupported_open(
        _path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        _flags: int,
        _mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        del dir_fd
        raise NotImplementedError("descriptor-relative open is unavailable")

    monkeypatch.setattr(binding_api.os, "open", unsupported_open)

    assert run_integrity_cli(_snapshot_argv(root, output)) == 2
    assert not output.exists()


@pytest.mark.parametrize("operation", ("list", "stat"))
def test_snapshot_maps_not_implemented_descriptor_operations_to_code_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "payload").write_bytes(b"evidence")
    output = tmp_path / "snapshot.json"
    if operation == "list":
        monkeypatch.setattr(
            tree_api.os,
            "listdir",
            lambda _descriptor: (_ for _ in ()).throw(
                NotImplementedError("descriptor list is unavailable")
            ),
        )
    else:
        original = tree_api.os.stat

        def unsupported_stat(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            *,
            dir_fd: int | None = None,
            follow_symlinks: bool = True,
        ) -> os.stat_result:
            if path == "payload" and dir_fd is not None:
                raise NotImplementedError("descriptor stat is unavailable")
            return original(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

        monkeypatch.setattr(tree_api.os, "stat", unsupported_stat)

    assert run_integrity_cli(_snapshot_argv(root, output)) == 2
    assert not output.exists()


def test_retained_cache_maps_not_implemented_descriptor_list_to_code_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = active_cache(tmp_path)
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        os,
        "listdir",
        lambda _descriptor: (_ for _ in ()).throw(
            NotImplementedError("descriptor list is unavailable")
        ),
    )

    assert run_integrity_cli(_retained_argv(active, output)) == 2
    assert not output.exists()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="requires a POSIX filesystem that accepts undecodable byte names",
)
def test_snapshot_rejects_a_non_utf8_posix_filename_at_the_cli_boundary(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    raw_path = os.path.join(os.fsencode(root), b"invalid-\xff")
    descriptor = os.open(raw_path, os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        _ = os.write(descriptor, b"evidence")
    finally:
        os.close(descriptor)
    output = tmp_path / "snapshot.json"

    code = run_integrity_cli(_snapshot_argv(root, output))

    assert code == 2
    assert not output.exists()

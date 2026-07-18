"""Deterministic descriptor and metadata races for base snapshots."""

from __future__ import annotations

from collections.abc import Iterator
import hashlib
import os
from pathlib import Path

import pytest

from w3xtool import integrity_snapshot as snapshot_api


def test_snapshot_does_not_accept_an_os_walk_ancestor_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    source = child / "payload"
    source.write_bytes(b"inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload").write_bytes(b"escape")
    moved = tmp_path / "moved-child"
    root_before = root.stat()

    def swap_walk(
        _root: Path,
        *,
        followlinks: bool,
    ) -> Iterator[tuple[str, list[str], list[str]]]:
        assert not followlinks
        yield str(root), ["child"], []
        child.rename(moved)
        child.symlink_to(outside, target_is_directory=True)
        os.utime(root, ns=(root_before.st_atime_ns, root_before.st_mtime_ns))
        try:
            yield str(child), [], ["payload"]
        finally:
            child.unlink()
            moved.rename(child)
            os.utime(root, ns=(root_before.st_atime_ns, root_before.st_mtime_ns))

    monkeypatch.setattr(os, "walk", swap_walk)

    result = snapshot_api.build_integrity_snapshot(
        (snapshot_api.SnapshotRoot("root", root),)
    )

    assert result.roots[0].entries[0].sha256 == hashlib.sha256(b"inside").hexdigest()


def test_snapshot_rejects_same_size_write_with_restored_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = root / "payload"
    source.write_bytes(b"before")
    before = source.stat()
    original_read = os.read
    mutated = False

    def mutate_after_read(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = original_read(descriptor, size)
        if chunk and not mutated:
            mutated = True
            source.write_bytes(b"after!")
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        return chunk

    monkeypatch.setattr(os, "read", mutate_after_read)

    with pytest.raises(snapshot_api.IntegritySnapshotError):
        snapshot_api.build_integrity_snapshot(
            (snapshot_api.SnapshotRoot("root", root),)
        )


def test_snapshot_rejects_restored_ancestor_swap_before_child_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "payload").write_bytes(b"inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload").write_bytes(b"escape")
    moved = tmp_path / "moved-child"
    original_open = os.open
    swapped = False

    def swap_before_open(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path != "child" or dir_fd is None or swapped:
            return original_open(path, flags, mode, dir_fd=dir_fd)
        swapped = True
        child.rename(moved)
        child.symlink_to(outside, target_is_directory=True)
        try:
            return original_open(path, flags, mode, dir_fd=dir_fd)
        finally:
            child.unlink()
            moved.rename(child)

    monkeypatch.setattr(os, "open", swap_before_open)

    with pytest.raises(snapshot_api.IntegritySnapshotError):
        snapshot_api.build_integrity_snapshot(
            (snapshot_api.SnapshotRoot("root", root),)
        )

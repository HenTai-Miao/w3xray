"""Stable current-map snapshot behavior."""

from __future__ import annotations

from dataclasses import fields
import hashlib
import os
from pathlib import Path
import stat

import pytest

from w3xtool.current_map_snapshot import (
    CurrentMapSnapshot,
    CurrentMapSnapshotError,
    cleanup_current_map_snapshot,
    create_current_map_snapshot,
)


def _isolated_snapshot_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    root = tmp_path / "snapshots"
    root.mkdir()
    monkeypatch.setattr(
        "w3xtool.current_map_snapshot.tempfile.gettempdir",
        lambda: str(root),
    )
    return root


def test_snapshot_dataclass_preserves_original_private_directory_fields() -> None:
    # Given: the established immutable snapshot result type.
    field_names = tuple(model_field.name for model_field in fields(CurrentMapSnapshot))

    # When/Then: its original private directory identity fields remain stable.
    assert field_names[-2:] == ("_directory_device", "_directory_inode")
    assert "directory_identity" not in field_names


def test_snapshot_preserves_exact_bytes_and_sha256(tmp_path: Path) -> None:
    # Given: a map whose data spans multiple copy chunks.
    source = tmp_path / "地图.w3x"
    payload = (bytes(range(256)) * 8193) + b"tail"
    _ = source.write_bytes(payload)

    # When: a stable snapshot is created.
    snapshot = create_current_map_snapshot(source)

    # Then: the copied bytes and reported digest are exact.
    try:
        assert snapshot.path.read_bytes() == payload
        assert snapshot.sha256 == hashlib.sha256(payload).hexdigest()
    finally:
        cleanup_current_map_snapshot(snapshot)


def test_snapshot_uses_fixed_private_name(tmp_path: Path) -> None:
    # Given: a valid map with an uppercase extension.
    source = tmp_path / "unsafe name.W3M"
    _ = source.write_bytes(b"map")

    # When: a snapshot is created.
    snapshot = create_current_map_snapshot(source)

    # Then: its unique directory and fixed file are safely named.
    try:
        assert snapshot.path.name == "current.w3m"
        assert snapshot.path.parent != source.parent
    finally:
        cleanup_current_map_snapshot(snapshot)


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX permission bits do not express Windows temp-directory ownership",
)
def test_snapshot_permissions_are_private_on_posix(tmp_path: Path) -> None:
    # Given: a valid map on a platform with enforceable POSIX permission bits.
    source = tmp_path / "private.w3x"
    _ = source.write_bytes(b"map")

    # When: a snapshot is created.
    snapshot = create_current_map_snapshot(source)

    # Then: group and other users receive no directory or file permissions.
    try:
        assert stat.S_IMODE(snapshot.path.parent.stat().st_mode) & 0o077 == 0
        assert stat.S_IMODE(snapshot.path.stat().st_mode) & 0o077 == 0
    finally:
        cleanup_current_map_snapshot(snapshot)


def test_snapshot_preserves_source_identity_and_metadata(tmp_path: Path) -> None:
    # Given: a map with a deliberate nanosecond modification time.
    source = tmp_path / "identity.w3n"
    _ = source.write_bytes(b"unchanged source")
    mtime_ns = 1_700_000_000_123_456_789
    os.utime(source, ns=(mtime_ns, mtime_ns))
    before = source.stat()
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    # When: the source is snapshotted.
    snapshot = create_current_map_snapshot(source)

    # Then: the source identity, size, mtime, and bytes remain unchanged.
    try:
        after = source.stat()
        assert (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            hashlib.sha256(source.read_bytes()).hexdigest(),
        ) == (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before_hash,
        )
        assert (
            snapshot.source_device,
            snapshot.source_inode,
            snapshot.source_size,
            snapshot.source_mtime_ns,
        ) == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    finally:
        cleanup_current_map_snapshot(snapshot)


@pytest.mark.parametrize("name", ["map", "map.txt", "map.w3x.bak"])
def test_snapshot_rejects_invalid_extensions(tmp_path: Path, name: str) -> None:
    # Given: a regular file without an allowed map extension.
    source = tmp_path / name
    _ = source.write_bytes(b"not a map")

    # When/Then: snapshot creation rejects it at the input boundary.
    with pytest.raises(CurrentMapSnapshotError, match="extension"):
        _ = create_current_map_snapshot(source)


def test_snapshot_rejects_missing_source(tmp_path: Path) -> None:
    # Given: a map path that does not exist.
    source = tmp_path / "missing.w3x"

    # When/Then: snapshot creation reports a typed error.
    with pytest.raises(CurrentMapSnapshotError, match="inspect"):
        _ = create_current_map_snapshot(source)


def test_snapshot_rejects_non_regular_source(tmp_path: Path) -> None:
    # Given: a directory with a valid-looking map extension.
    source = tmp_path / "directory.w3x"
    source.mkdir()

    # When/Then: snapshot creation refuses the non-regular object.
    with pytest.raises(CurrentMapSnapshotError, match="regular file"):
        _ = create_current_map_snapshot(source)


def test_snapshot_rejects_symlink_source(tmp_path: Path) -> None:
    # Given: a valid-looking symlink to a regular map.
    target = tmp_path / "target.w3x"
    _ = target.write_bytes(b"target")
    source = tmp_path / "linked.w3x"
    try:
        source.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    # When/Then: snapshot creation never follows the symlink.
    with pytest.raises(CurrentMapSnapshotError, match="regular file"):
        _ = create_current_map_snapshot(source)


def test_snapshot_nonblocking_open_rejects_fifo_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a regular source that becomes a FIFO immediately before open.
    if not hasattr(os, "mkfifo") or getattr(os, "O_NONBLOCK", 0) == 0:
        pytest.skip("POSIX FIFO and O_NONBLOCK support are required")
    source = tmp_path / "swapped.w3x"
    _ = source.write_bytes(b"map")
    real_open = os.open
    swapped = False

    def swapping_open(path: str | os.PathLike[str], flags: int, mode: int = 0o777) -> int:
        nonlocal swapped
        if Path(path) == source:
            source.unlink()
            os.mkfifo(source)
            swapped = True
            if flags & os.O_NONBLOCK == 0:
                pytest.fail("source open omitted O_NONBLOCK and would hang on the FIFO")
        return real_open(path, flags, mode)

    monkeypatch.setattr("w3xtool.current_map_snapshot.os.open", swapping_open)

    # When/Then: opening never blocks and fstat rejects the swapped object.
    with pytest.raises(CurrentMapSnapshotError, match="changed"):
        _ = create_current_map_snapshot(source)
    assert swapped


def test_snapshot_rejects_source_changed_during_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a source that changes immediately before the required destination fsync.
    source = tmp_path / "changing.w3x"
    _ = source.write_bytes(b"a" * (2 * 1024 * 1024))
    before = source.stat()
    snapshot_root = _isolated_snapshot_root(tmp_path, monkeypatch)
    real_fsync = os.fsync
    changed = False

    def fsync_after_source_change(descriptor: int) -> None:
        nonlocal changed
        if not changed:
            changed = True
            with source.open("r+b") as source_file:
                _ = source_file.write(b"b" * 4096)
                source_file.flush()
                real_fsync(source_file.fileno())
            changed_mtime = before.st_mtime_ns + 1_000_000_000
            os.utime(source, ns=(changed_mtime, changed_mtime))
        real_fsync(descriptor)

    monkeypatch.setattr("w3xtool.current_map_snapshot.os.fsync", fsync_after_source_change)

    # When/Then: the inconsistent snapshot is rejected and its directory is removed.
    with pytest.raises(CurrentMapSnapshotError, match="changed"):
        _ = create_current_map_snapshot(source)
    assert changed
    assert list(snapshot_root.iterdir()) == []

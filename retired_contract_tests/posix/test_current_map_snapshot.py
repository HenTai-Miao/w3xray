"""Stable current-map snapshot behavior."""

from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from gametool.current_map_snapshot import (
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
        "gametool.current_map_snapshot.tempfile.gettempdir",
        lambda: str(root),
    )
    return root


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

    def swapping_open(
        path: str | os.PathLike[str], flags: int, mode: int = 0o777
    ) -> int:
        nonlocal swapped
        if Path(path) == source:
            source.unlink()
            os.mkfifo(source)
            swapped = True
            if flags & os.O_NONBLOCK == 0:
                pytest.fail("source open omitted O_NONBLOCK and would hang on the FIFO")
        return real_open(path, flags, mode)

    monkeypatch.setattr("gametool.current_map_snapshot.os.open", swapping_open)

    # When/Then: opening never blocks and fstat rejects the swapped object.
    with pytest.raises(CurrentMapSnapshotError, match="changed"):
        _ = create_current_map_snapshot(source)
    assert swapped

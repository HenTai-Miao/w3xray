"""Adversarial parent-move tests for anchored output writes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from w3xtool.safe_output import write_bytes_safely
from w3xtool.safe_output_anchored import ANCHORED_WRITES_AVAILABLE
from w3xtool.safe_output_models import SafeWriteStatus
from w3xtool import safe_output_publication_rollback as rollback_api


class _UnexpectedWrapperError(RuntimeError):
    """Synthetic non-OSError from the file-wrapper boundary."""


@pytest.mark.skipif(
    not ANCHORED_WRITES_AVAILABLE,
    reason="requires anchored directory operations",
)
def test_parent_move_before_open_preserves_existing_external_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the held parent is moved outside immediately before file creation.
    root = tmp_path / "out"
    parent = root / "assets"
    parent.mkdir(parents=True)
    existing = parent / "x.bin"
    _ = existing.write_bytes(b"outside-before")
    moved_parent = tmp_path / "assets-moved"
    redirected_parent = tmp_path / "assets-redirected"
    redirected_parent.mkdir()
    original_open = os.open
    parent_moved = False

    def racing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal parent_moved
        if not parent_moved and flags & os.O_WRONLY:
            _ = parent.rename(moved_parent)
            _ = parent.symlink_to(redirected_parent, target_is_directory=True)
            parent_moved = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", racing_open)

    # When: the anchored writer attempts to replace the destination.
    result = write_bytes_safely(str(root), "assets/x.bin", b"new-data")

    # Then: no pre-existing file outside the root is truncated or removed.
    assert parent_moved
    assert result.status is SafeWriteStatus.UNSAFE
    assert (moved_parent / "x.bin").read_bytes() == b"outside-before"
    assert not (redirected_parent / "x.bin").exists()


@pytest.mark.skipif(
    not ANCHORED_WRITES_AVAILABLE,
    reason="requires anchored directory operations",
)
def test_parent_move_during_publish_restores_existing_external_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the destination exists before its parent moves during publication.
    root = tmp_path / "out"
    parent = root / "assets"
    parent.mkdir(parents=True)
    _ = (parent / "x.bin").write_bytes(b"outside-before")
    moved_parent = tmp_path / "assets-moved"
    redirected_parent = tmp_path / "assets-redirected"
    redirected_parent.mkdir()
    original_rename = os.rename
    parent_moved = False

    original_claim = rollback_api.claim_name

    def racing_claim(
        parent_descriptor: int,
        source: str,
        destination: str,
        identity: tuple[int, int],
    ) -> None:
        nonlocal parent_moved
        if not parent_moved:
            original_rename(parent, moved_parent)
            _ = parent.symlink_to(redirected_parent, target_is_directory=True)
            parent_moved = True
        original_claim(
            parent_descriptor,
            source,
            destination,
            identity,
        )

    monkeypatch.setattr(rollback_api, "claim_name", racing_claim)

    # When: the staged output is published through the held parent fd.
    result = write_bytes_safely(str(root), "assets/x.bin", b"new-data")

    # Then: the original outside file is restored after containment fails.
    assert parent_moved
    assert result.status is SafeWriteStatus.UNSAFE
    assert (moved_parent / "x.bin").read_bytes() == b"outside-before"
    assert not (redirected_parent / "x.bin").exists()


@pytest.mark.skipif(
    not ANCHORED_WRITES_AVAILABLE,
    reason="requires anchored directory operations",
)
def test_unexpected_write_error_removes_the_staged_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an unexpected exception after the staged file has been created.
    root = tmp_path / "out"
    output_parent = root / "assets"
    output_parent.mkdir(parents=True)

    def failing_fdopen(
        _descriptor: int,
        _mode: str,
        *,
        closefd: bool = True,
    ) -> None:
        _ = closefd
        raise _UnexpectedWrapperError("unexpected wrapper failure")

    monkeypatch.setattr(os, "fdopen", failing_fdopen)

    # When: the unexpected error escapes the public writer.
    with pytest.raises(_UnexpectedWrapperError, match="unexpected wrapper failure"):
        _ = write_bytes_safely(str(root), "assets/x.bin", b"new-data")

    # Then: the original exception is preserved and no staged data remains.
    assert tuple(output_parent.iterdir()) == ()

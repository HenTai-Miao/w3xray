"""Durable path-based publication for hosts without directory-fd writes."""

from __future__ import annotations

import os
import errno
from pathlib import Path
import stat
from uuid import uuid4

from . import durable_io
from .windows_output_paths import native_output_path, remove_owned_output


def publish_staged_path(
    staged_path: str,
    destination: str,
    *,
    expected_stage_identity: tuple[int, int] | None = None,
) -> None:
    """Keep an existing public name present through replacement and rollback.

    A same-directory hard link retains the old inode before atomic replacement.
    No failure path falls back to moving the public name out of the way.
    """
    target = Path(native_output_path(destination))
    staged = Path(native_output_path(staged_path))
    parent = target.parent
    stage_identity = _file_identity(staged)
    if stage_identity is None:
        raise FileNotFoundError(errno.ENOENT, "staged output disappeared", str(staged))
    if (
        expected_stage_identity is not None
        and stage_identity != expected_stage_identity
    ):
        raise OSError(errno.EIO, "staged output identity changed", str(staged))
    old_identity = _file_identity(target)
    if old_identity is None:
        _publish_new(staged, target, stage_identity)
        return
    backup = parent / f".gamexray-backup-{uuid4().hex}.tmp"
    # CreateHardLinkW neither removes nor renames the old public target. It also
    # fails without overwriting a colliding backup name or an unsupported volume.
    os.link(target, backup, follow_symlinks=False)
    try:
        _require_identity(backup, old_identity, "backup")
        _require_identity(target, old_identity, "public target")
        durable_io.sync_directory(parent)
        _require_identity(staged, stage_identity, "staged output")
        _require_identity(backup, old_identity, "backup")
        _require_identity(target, old_identity, "public target")
        os.replace(staged, target)
        _require_identity(target, stage_identity, "published output")
        durable_io.sync_directory(parent)
    except OSError as failure:
        # No pathname check can authorize a later overwrite atomically. Preserve
        # both complete objects instead of guessing that rollback is safe.
        raise OSError(
            f"{failure}; recovery retained without automatic overwrite: "
            f"current public={target}; original backup={backup}"
        ) from failure
    # Preserve both the old backup and any foreign public object if a concurrent
    # replacement appears during the commit seam. Never unlink a foreign backup.
    _require_identity(target, stage_identity, "published output")
    _require_identity(backup, old_identity, "backup")
    if not remove_owned_output(str(backup), old_identity):
        raise OSError(f"backup cleanup retained a missing or replaced object: {backup}")
    durable_io.sync_directory(parent)


def _publish_new(staged: Path, target: Path, stage_identity: tuple[int, int]) -> None:
    # On Windows rename refuses an existing destination; replace would erase a
    # concurrent creator. The stage and target are on the same filesystem.
    _require_identity(staged, stage_identity, "staged output")
    os.rename(staged, target)
    try:
        _require_identity(target, stage_identity, "published output")
        durable_io.sync_directory(target.parent)
    except OSError as failure:
        try:
            if not remove_owned_output(str(target), stage_identity):
                raise OSError("new public output changed; cleanup object retained")
            durable_io.sync_directory(target.parent)
        except OSError as cleanup_error:
            raise OSError(
                f"{failure}; new-output cleanup was not completed at {target}: "
                f"{cleanup_error}"
            ) from failure
        raise


def _file_identity(path: Path) -> tuple[int, int] | None:
    try:
        details = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(details.st_mode) or (
        getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise OSError(
            errno.ELOOP, "publication file is not a regular no-follow file", str(path)
        )
    return details.st_dev, details.st_ino


def _require_identity(path: Path, expected: tuple[int, int], label: str) -> None:
    if _file_identity(path) != expected:
        raise OSError(errno.EIO, f"{label} identity changed", str(path))

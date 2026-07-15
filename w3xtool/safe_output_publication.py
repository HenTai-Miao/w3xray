"""Atomic publication and restoration for anchored staged outputs.

Publication commits when the post-publish ancestry check succeeds. A later
external move may relocate the committed directory while its private rollback
link is being discarded; that does not alter another destination path.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import errno
import os
import secrets
import stat
from typing import Final

from w3xtool.durable_io import sync_directory_descriptor
from w3xtool.safe_output_models import SafeWriteResult, SafeWriteStatus
from w3xtool.safe_output_staging import discard_file


_BACKUP_NAME_ATTEMPTS: Final = 16
_ContainmentCheck = Callable[[], str | None]
_FailureStatus = Callable[[OSError], SafeWriteStatus]


def publish_staged_file(
    parent_descriptor: int,
    staged_name: str,
    destination_name: str,
    destination: str,
    check_containment: _ContainmentCheck,
    failure_status: _FailureStatus,
) -> SafeWriteResult | None:
    """Publish staged data while preserving an existing destination on failure."""
    try:
        backup_name = _backup_destination(parent_descriptor, destination_name)
    except OSError as exc:
        return discard_file(
            parent_descriptor,
            staged_name,
            destination,
            failure_status(exc),
            str(exc),
        )
    containment_error = check_containment()
    if containment_error is not None:
        return _discard_files(
            parent_descriptor,
            _present_names(staged_name, backup_name),
            destination,
            SafeWriteStatus.UNSAFE,
            containment_error,
        )
    if backup_name is None:
        return _publish_new_destination(
            parent_descriptor,
            staged_name,
            destination_name,
            destination,
            check_containment,
            failure_status,
        )
    return _replace_with_backup(
        parent_descriptor,
        staged_name,
        destination_name,
        backup_name,
        destination,
        check_containment,
        failure_status,
    )


def _backup_destination(parent_descriptor: int, name: str) -> str | None:
    try:
        details = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(details.st_mode):
        raise OSError(errno.EINVAL, "unsafe destination changed before publication")
    for _ in range(_BACKUP_NAME_ATTEMPTS):
        backup_name = f".w3xray-backup-{secrets.token_hex(16)}.tmp"
        try:
            os.link(
                name,
                backup_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError:
            continue
        except FileNotFoundError:
            return None
        try:
            sync_directory_descriptor(parent_descriptor)
        except OSError:
            _ = _unlink_error(parent_descriptor, backup_name)
            sync_directory_descriptor(parent_descriptor)
            raise
        return backup_name
    raise FileExistsError(errno.EEXIST, "could not allocate destination backup")


def _publish_new_destination(
    parent_descriptor: int,
    staged_name: str,
    destination_name: str,
    destination: str,
    check_containment: _ContainmentCheck,
    failure_status: _FailureStatus,
) -> SafeWriteResult | None:
    try:
        os.link(
            staged_name,
            destination_name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        return discard_file(
            parent_descriptor,
            staged_name,
            destination,
            failure_status(exc),
            str(exc),
        )
    containment_error = check_containment()
    if containment_error is not None:
        return _discard_files(
            parent_descriptor,
            (destination_name, staged_name),
            destination,
            SafeWriteStatus.UNSAFE,
            containment_error,
        )
    try:
        sync_directory_descriptor(parent_descriptor)
    except OSError as exc:
        return _discard_files(
            parent_descriptor,
            (destination_name, staged_name),
            destination,
            SafeWriteStatus.FAILED,
            str(exc),
        )
    cleanup_error = _unlink_error(parent_descriptor, staged_name)
    if cleanup_error is not None:
        return SafeWriteResult(SafeWriteStatus.FAILED, destination, 0, cleanup_error)
    try:
        sync_directory_descriptor(parent_descriptor)
    except OSError as exc:
        return SafeWriteResult(SafeWriteStatus.FAILED, destination, 0, str(exc))
    return None


def _replace_with_backup(
    parent_descriptor: int,
    staged_name: str,
    destination_name: str,
    backup_name: str,
    destination: str,
    check_containment: _ContainmentCheck,
    failure_status: _FailureStatus,
) -> SafeWriteResult | None:
    try:
        os.rename(
            staged_name,
            destination_name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
    except OSError as exc:
        return _discard_files(
            parent_descriptor,
            (staged_name, backup_name),
            destination,
            failure_status(exc),
            str(exc),
        )
    containment_error = check_containment()
    if containment_error is not None:
        try:
            os.rename(
                backup_name,
                destination_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
        except OSError as exc:
            containment_error = f"{containment_error}; restore failed: {exc}"
        return SafeWriteResult(
            SafeWriteStatus.UNSAFE,
            destination,
            0,
            containment_error,
        )
    try:
        sync_directory_descriptor(parent_descriptor)
    except OSError as exc:
        reason = str(exc)
        try:
            os.rename(
                backup_name,
                destination_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            sync_directory_descriptor(parent_descriptor)
        except OSError as restore_exc:
            reason = f"{reason}; restore failed: {restore_exc}"
        return SafeWriteResult(SafeWriteStatus.FAILED, destination, 0, reason)
    cleanup_error = _unlink_error(parent_descriptor, backup_name)
    if cleanup_error is not None:
        return SafeWriteResult(SafeWriteStatus.FAILED, destination, 0, cleanup_error)
    try:
        sync_directory_descriptor(parent_descriptor)
    except OSError as exc:
        return SafeWriteResult(SafeWriteStatus.FAILED, destination, 0, str(exc))
    return None


def _discard_files(
    parent_descriptor: int,
    names: Iterable[str],
    destination: str,
    status: SafeWriteStatus,
    reason: str,
) -> SafeWriteResult:
    for name in names:
        cleanup_error = _unlink_error(parent_descriptor, name)
        if cleanup_error is not None:
            reason = f"{reason}; cleanup failed: {cleanup_error}"
    try:
        sync_directory_descriptor(parent_descriptor)
    except OSError as exc:
        reason = f"{reason}; cleanup sync failed: {exc}"
    return SafeWriteResult(status, destination, 0, reason)


def _unlink_error(parent_descriptor: int, name: str) -> str | None:
    try:
        os.unlink(name, dir_fd=parent_descriptor)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return str(exc)
    return None


def _present_names(staged_name: str, backup_name: str | None) -> tuple[str, ...]:
    if backup_name is None:
        return (staged_name,)
    return staged_name, backup_name

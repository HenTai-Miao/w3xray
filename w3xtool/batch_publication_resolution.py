"""Durable resolution actions selected by map-publication recovery."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import shutil

from .batch_publication_models import (
    PublicationPhase,
    PublicationTransaction,
    RecoveryDiagnostic,
)
from .batch_publication_record import (
    paths_for,
    publication_matches,
    remove_transaction,
    write_transaction,
)
from .durable_io import sync_directory


def commit_existing_destination(
    maps_root: Path,
    transaction: PublicationTransaction,
    stage_matches: bool,
    backup_owned: bool,
) -> tuple[RecoveryDiagnostic, ...]:
    """Keep the exact new destination and clean only proved leftovers."""
    unproved = _cleanup_leftovers(
        maps_root,
        transaction,
        stage_matches,
        backup_owned,
    )
    if unproved:
        return unproved
    committed = replace(transaction, phase=PublicationPhase.COMMITTED)
    write_transaction(maps_root, committed)
    remove_transaction(maps_root, committed)
    return (_diagnostic("kept_committed_destination", transaction),)


def keep_previous_destination(
    maps_root: Path,
    transaction: PublicationTransaction,
    stage_matches: bool,
    backup_owned: bool,
) -> tuple[RecoveryDiagnostic, ...]:
    """Prefer an untouched prior destination when replacement never started."""
    unproved = _cleanup_leftovers(
        maps_root,
        transaction,
        stage_matches,
        backup_owned,
    )
    if unproved:
        return unproved
    remove_transaction(maps_root, transaction)
    return (_diagnostic("kept_previous_destination", transaction),)


def publish_prepared_stage(
    maps_root: Path,
    transaction: PublicationTransaction,
    backup_owned: bool,
) -> tuple[RecoveryDiagnostic, ...]:
    """Finish a valid prepared stage when no destination remains."""
    paths = paths_for(maps_root, transaction)
    os.replace(paths.stage, paths.destination)
    sync_directory(maps_root)
    ready = replace(transaction, phase=PublicationPhase.DESTINATION_READY)
    write_transaction(maps_root, ready)
    if not publication_matches(paths.destination, ready):
        return (unproved_diagnostic(ready, paths.destination),)
    if paths.backup.exists():
        if not backup_owned:
            return (unproved_diagnostic(ready, paths.backup),)
        shutil.rmtree(paths.backup)
        sync_directory(maps_root)
    committed = replace(ready, phase=PublicationPhase.COMMITTED)
    write_transaction(maps_root, committed)
    remove_transaction(maps_root, committed)
    return (_diagnostic("published_prepared_stage", transaction),)


def restore_backup(
    maps_root: Path,
    transaction: PublicationTransaction,
) -> tuple[RecoveryDiagnostic, ...]:
    """Restore a source-owned backup when the new stage cannot be proven."""
    paths = paths_for(maps_root, transaction)
    os.replace(paths.backup, paths.destination)
    sync_directory(maps_root)
    diagnostics = [_diagnostic("restored_owned_backup", transaction)]
    if paths.stage.exists() or paths.stage.is_symlink():
        diagnostics.append(unproved_diagnostic(transaction, paths.stage))
        return tuple(diagnostics)
    remove_transaction(maps_root, transaction)
    return tuple(diagnostics)


def unproved_diagnostic(
    transaction: PublicationTransaction,
    path: Path,
) -> RecoveryDiagnostic:
    """Report a path that recovery deliberately refused to mutate."""
    return RecoveryDiagnostic(
        "unproved_path",
        str(path),
        transaction.transaction_id,
    )


def _cleanup_leftovers(
    maps_root: Path,
    transaction: PublicationTransaction,
    stage_matches: bool,
    backup_owned: bool,
) -> tuple[RecoveryDiagnostic, ...]:
    paths = paths_for(maps_root, transaction)
    diagnostics: list[RecoveryDiagnostic] = []
    if paths.stage.exists() or paths.stage.is_symlink():
        if stage_matches:
            shutil.rmtree(paths.stage)
            sync_directory(maps_root)
        else:
            diagnostics.append(unproved_diagnostic(transaction, paths.stage))
    if paths.backup.exists() or paths.backup.is_symlink():
        if backup_owned:
            shutil.rmtree(paths.backup)
            sync_directory(maps_root)
        else:
            diagnostics.append(unproved_diagnostic(transaction, paths.backup))
    return tuple(diagnostics)


def _diagnostic(
    code: str,
    transaction: PublicationTransaction,
) -> RecoveryDiagnostic:
    return RecoveryDiagnostic(code, transaction_id=transaction.transaction_id)

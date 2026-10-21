"""Idempotent startup recovery for interrupted map-directory transactions."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
import shutil
from typing import Final

from .batch_manifest_validation import verify_map_publication
from .batch_publication_models import (
    PublicationPhase,
    PublicationRecordError,
    PublicationTransaction,
    RecoveryDiagnostic,
)
from .batch_publication_record import (
    TRANSACTION_PREFIX,
    load_transaction,
    owned_source_digest,
    paths_for,
    publication_matches,
    remove_transaction,
    write_transaction,
)
from .batch_publication_resolution import (
    commit_existing_destination,
    keep_previous_destination,
    publish_prepared_stage,
    restore_backup,
    unproved_diagnostic,
)
from .durable_io import sync_directory


_RECORD_NAME: Final = re.compile(
    rf"{re.escape(TRANSACTION_PREFIX)}([0-9a-f]{{32}})\.json"
)


def recover_map_publications(output_root: str) -> tuple[RecoveryDiagnostic, ...]:
    """Recover every strict transaction without touching unproved paths."""
    maps_root = Path(output_root, "地图")
    if not maps_root.exists():
        return ()
    if maps_root.is_symlink() or not maps_root.is_dir():
        return (RecoveryDiagnostic("unsafe_map_root", str(maps_root)),)
    diagnostics: list[RecoveryDiagnostic] = []
    for record_path in sorted(maps_root.iterdir(), key=lambda item: item.name):
        if not record_path.name.startswith(TRANSACTION_PREFIX):
            continue
        match = _RECORD_NAME.fullmatch(record_path.name)
        if match is None:
            diagnostics.append(
                RecoveryDiagnostic("invalid_transaction", record_path.name)
            )
            continue
        try:
            transaction = load_transaction(record_path)
            if transaction.transaction_id != match.group(1):
                raise PublicationRecordError("record filename does not match payload")
            diagnostics.extend(_recover_one(maps_root, transaction))
        except (OSError, PublicationRecordError) as exc:
            diagnostics.append(
                RecoveryDiagnostic(
                    "invalid_transaction",
                    str(exc),
                    match.group(1),
                )
            )
    return tuple(diagnostics)


def _recover_one(
    maps_root: Path,
    transaction: PublicationTransaction,
) -> tuple[RecoveryDiagnostic, ...]:
    paths = paths_for(maps_root, transaction)
    transaction = _bind_completed_manifest(transaction, paths.stage, maps_root)
    if transaction.phase is PublicationPhase.BUILDING:
        return _discard_incomplete_build(maps_root, transaction)
    paths = paths_for(maps_root, transaction)
    stage_matches = publication_matches(paths.stage, transaction)
    destination_matches = publication_matches(paths.destination, transaction)
    destination_owned = (
        owned_source_digest(paths.destination) == transaction.source_sha256
    )
    backup_owned = owned_source_digest(paths.backup) == transaction.source_sha256
    if destination_matches:
        return commit_existing_destination(
            maps_root,
            transaction,
            stage_matches,
            backup_owned,
        )
    if paths.destination.exists() or paths.destination.is_symlink():
        if destination_owned:
            return keep_previous_destination(
                maps_root,
                transaction,
                stage_matches,
                backup_owned,
            )
        return (unproved_diagnostic(transaction, paths.destination),)
    if stage_matches:
        return publish_prepared_stage(
            maps_root,
            transaction,
            backup_owned,
        )
    if backup_owned:
        return restore_backup(maps_root, transaction)
    candidate = paths.stage if paths.stage.exists() else paths.backup
    return (unproved_diagnostic(transaction, candidate),)


def _bind_completed_manifest(
    transaction: PublicationTransaction,
    stage: Path,
    maps_root: Path,
) -> PublicationTransaction:
    if transaction.phase is not PublicationPhase.BUILDING:
        return transaction
    validation = verify_map_publication(stage)
    manifest = validation.manifest
    if (
        not validation.valid
        or manifest is None
        or manifest.transaction_id != transaction.transaction_id
        or manifest.source.sha256 != transaction.source_sha256
    ):
        return transaction
    prepared = replace(
        transaction,
        phase=PublicationPhase.PREPARED,
        manifest_sha256=validation.manifest_sha256,
    )
    write_transaction(maps_root, prepared)
    return prepared


def _discard_incomplete_build(
    maps_root: Path,
    transaction: PublicationTransaction,
) -> tuple[RecoveryDiagnostic, ...]:
    paths = paths_for(maps_root, transaction)
    if paths.destination.exists() or paths.backup.exists() or paths.stage.is_symlink():
        return (unproved_diagnostic(transaction, paths.stage),)
    if paths.stage.exists():
        if not paths.stage.is_dir():
            return (unproved_diagnostic(transaction, paths.stage),)
        shutil.rmtree(paths.stage)
        sync_directory(maps_root)
    remove_transaction(maps_root, transaction)
    return (
        RecoveryDiagnostic(
            "discarded_building_stage",
            transaction_id=transaction.transaction_id,
        ),
    )

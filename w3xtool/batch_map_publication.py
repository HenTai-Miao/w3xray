"""Owned staging directories and recoverable per-map publication."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
from uuid import uuid4

from .batch_manifest_validation import verify_map_publication
from .batch_publication_models import (
    BatchMapPublicationError,
    MapPublicationStage,
    PublicationPhase,
    PublicationRecordError,
    PublicationTransaction,
    RecoveryDiagnostic,
)
from .batch_publication_record import (
    load_transaction,
    new_transaction,
    owned_source_digest,
    paths_for,
    publication_matches,
    record_path,
    remove_transaction,
    write_transaction,
)
from .batch_publication_recovery import recover_map_publications
from .durable_io import sync_directory
from .safe_output import safe_destination, safe_relative_path


def map_output_relative(index: int, display_name: str, digest: str) -> str:
    """Build a bounded human-readable, content-addressed output directory."""
    cleaned = "".join(
        character if character.isalnum() or character in " ._-" else "_"
        for character in display_name
    ).strip(" ._")
    name = (cleaned or "未命名地图")[:64].rstrip(" ._")
    return f"地图/{index:03d}_{name}_{digest[:8]}"


def create_map_stage(
    output_root: str,
    relative: str,
    digest: str,
    *,
    transaction_id: str | None = None,
) -> MapPublicationStage:
    """Create a private stage and durably bind it to one destination."""
    maps_root, destination_name = _map_paths(output_root, relative)
    identifier = transaction_id or uuid4().hex
    stage = maps_root / f".w3xray-map-stage-{identifier}"
    publication = MapPublicationStage(stage, identifier, relative, digest)
    transaction = new_transaction(publication)
    if transaction.destination_name != destination_name:
        raise BatchMapPublicationError("map destination identity changed")
    if stage.exists() or stage.is_symlink():
        raise BatchMapPublicationError("map stage already exists")
    stage.mkdir(mode=0o700)
    try:
        _sync_map_root(maps_root)
        write_transaction(maps_root, transaction)
    except OSError, PublicationRecordError:
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage)
            _sync_map_root(maps_root)
        raise
    return publication


def publish_map_stage(
    publication: MapPublicationStage,
    output_root: str,
    manifest_sha256: str,
) -> Path:
    """Advance a manifest-valid stage through a durable directory transaction."""
    maps_root, destination_name = _map_paths(output_root, publication.relative)
    transaction = load_transaction(record_path(maps_root, publication.transaction_id))
    _require_matching_record(publication, transaction, destination_name)
    prepared = _prepare_transaction(
        maps_root,
        publication,
        transaction,
        manifest_sha256,
    )
    paths = paths_for(maps_root, prepared)
    current = prepared
    if paths.destination.exists() or paths.destination.is_symlink():
        _require_owned_destination(paths.destination, publication.digest)
        if paths.backup.exists() or paths.backup.is_symlink():
            raise BatchMapPublicationError("transaction backup already exists")
        _replace_directory(paths.destination, paths.backup)
        _sync_map_root(maps_root)
        current = replace(prepared, phase=PublicationPhase.BACKUP_READY)
        write_transaction(maps_root, current)
    _replace_directory(paths.stage, paths.destination)
    _sync_map_root(maps_root)
    current = replace(current, phase=PublicationPhase.DESTINATION_READY)
    write_transaction(maps_root, current)
    if not publication_matches(paths.destination, current):
        raise BatchMapPublicationError("published map generation failed validation")
    current = replace(current, phase=PublicationPhase.COMMITTED)
    write_transaction(maps_root, current)
    if paths.backup.exists() or paths.backup.is_symlink():
        _remove_owned_directory(paths.backup, publication.digest)
        _sync_map_root(maps_root)
    remove_transaction(maps_root, current)
    return paths.destination


def discard_map_stage(
    publication: MapPublicationStage | None,
    output_root: str,
) -> tuple[RecoveryDiagnostic, ...]:
    """Discard only an exact, still-building stage with its matching record."""
    if publication is None:
        return ()
    maps_root = Path(output_root, "地图")
    try:
        transaction = load_transaction(
            record_path(maps_root, publication.transaction_id)
        )
    except OSError as exc:
        return (
            RecoveryDiagnostic(
                "missing_transaction",
                str(exc),
                publication.transaction_id,
            ),
        )
    try:
        _require_matching_record(
            publication,
            transaction,
            Path(publication.relative).name,
        )
    except BatchMapPublicationError as exc:
        return (
            RecoveryDiagnostic(
                "unproved_path",
                str(exc),
                publication.transaction_id,
            ),
        )
    if transaction.phase is not PublicationPhase.BUILDING:
        return (
            RecoveryDiagnostic(
                "publication_pending_recovery",
                transaction.phase.value,
                transaction.transaction_id,
            ),
        )
    if publication.stage.is_symlink() or (
        publication.stage.exists() and not publication.stage.is_dir()
    ):
        return (
            RecoveryDiagnostic(
                "unproved_path",
                str(publication.stage),
                publication.transaction_id,
            ),
        )
    if publication.stage.exists():
        shutil.rmtree(publication.stage)
        _sync_map_root(maps_root)
    remove_transaction(maps_root, transaction)
    return ()


def _map_paths(output_root: str, relative: str) -> tuple[Path, str]:
    parsed = safe_relative_path(relative)
    if parsed is None or len(parsed.parts) != 2 or parsed.parts[0] != "地图":
        raise BatchMapPublicationError("unsafe map output path")
    destination = safe_destination(output_root, relative)
    if destination is None:
        raise BatchMapPublicationError("unsafe map output path")
    maps_root = Path(output_root, "地图")
    if Path(output_root).is_symlink() or maps_root.is_symlink():
        raise BatchMapPublicationError("map output directory is a symlink")
    maps_root.mkdir(parents=True, exist_ok=True)
    if maps_root.is_symlink() or not maps_root.is_dir():
        raise BatchMapPublicationError("map output directory is unsafe")
    if Path(destination).parent != maps_root.resolve():
        raise BatchMapPublicationError("map destination escaped its parent")
    return maps_root, parsed.name


def _prepare_transaction(
    maps_root: Path,
    publication: MapPublicationStage,
    transaction: PublicationTransaction,
    manifest_sha256: str,
) -> PublicationTransaction:
    prepared = replace(
        transaction,
        phase=PublicationPhase.PREPARED,
        manifest_sha256=manifest_sha256,
    )
    validation = verify_map_publication(publication.stage)
    manifest = validation.manifest
    if (
        not validation.valid
        or manifest is None
        or validation.manifest_sha256 != manifest_sha256
        or manifest.transaction_id != publication.transaction_id
        or manifest.source.sha256 != publication.digest
    ):
        reason = validation.detail or validation.code
        raise BatchMapPublicationError(f"map stage manifest mismatch: {reason}")
    write_transaction(maps_root, prepared)
    return prepared


def _require_matching_record(
    publication: MapPublicationStage,
    transaction: PublicationTransaction,
    destination_name: str,
) -> None:
    expected = new_transaction(publication)
    if (
        transaction.transaction_id != expected.transaction_id
        or transaction.stage_name != expected.stage_name
        or transaction.destination_name != expected.destination_name
        or transaction.backup_name != expected.backup_name
        or transaction.source_sha256 != expected.source_sha256
        or transaction.destination_name != destination_name
    ):
        raise BatchMapPublicationError("transaction record does not match stage")


def _require_owned_destination(destination: Path, digest: str) -> None:
    if owned_source_digest(destination) != digest:
        raise BatchMapPublicationError("refusing to replace unowned map output")


def _replace_directory(source: Path, destination: Path) -> None:
    source.replace(destination)


def _sync_map_root(maps_root: Path) -> None:
    sync_directory(maps_root)


def _remove_owned_directory(path: Path, digest: str) -> None:
    _require_owned_destination(path, digest)
    shutil.rmtree(path)


__all__ = (
    "BatchMapPublicationError",
    "MapPublicationStage",
    "RecoveryDiagnostic",
    "create_map_stage",
    "discard_map_stage",
    "map_output_relative",
    "publish_map_stage",
    "recover_map_publications",
)

"""Strict durable I/O and identity checks for map publication records."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
from typing import Final

from .batch_manifest_io import parse_ownership_record
from .batch_manifest_models import OWNERSHIP_MARKER_NAME
from .batch_manifest_validation import verify_map_publication
from .batch_publication_models import (
    BatchMapPublicationError,
    MapPublicationStage,
    PublicationPaths,
    PublicationPhase,
    PublicationRecordError,
    PublicationTransaction,
)
from .bounded_file import read_bounded_regular_file
from .durable_io import sync_directory
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteStatus
from .batch_stage_cleanup import StageCleanupStatus, remove_owned_record
from .windows_output_paths import native_output_path
from .windows_source_reads import WindowsSourceRoot


TRANSACTION_PREFIX: Final = ".gamexray-map-transaction-"
_MAX_RECORD_BYTES: Final[int | None] = None
_MAX_MARKER_BYTES: Final[int | None] = None
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_TRANSACTION_ID: Final = re.compile(r"[0-9a-f]{32}")

type JsonValue = (
    str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None
)


def new_transaction(stage: MapPublicationStage) -> PublicationTransaction:
    """Build the initial transaction record for a newly created stage."""
    destination_name = Path(stage.relative).name
    return PublicationTransaction(
        stage.transaction_id,
        PublicationPhase.BUILDING,
        f".gamexray-map-stage-{stage.transaction_id}",
        destination_name,
        f".gamexray-map-backup-{stage.transaction_id}",
        stage.digest,
        "",
        stage.stage_identity,
    )


def record_with_phase(
    transaction: PublicationTransaction,
    phase: PublicationPhase,
    *,
    manifest_sha256: str | None = None,
) -> PublicationTransaction:
    """Return a transaction advanced to one explicitly persisted phase."""
    digest = transaction.manifest_sha256
    if manifest_sha256 is not None:
        digest = manifest_sha256
    return replace(transaction, phase=phase, manifest_sha256=digest)


def record_path(maps_root: Path, transaction_id: str) -> Path:
    """Return the strict private record path for one transaction ID."""
    if _TRANSACTION_ID.fullmatch(transaction_id) is None:
        raise PublicationRecordError("invalid transaction ID")
    return maps_root / f"{TRANSACTION_PREFIX}{transaction_id}.json"


def paths_for(
    maps_root: Path,
    transaction: PublicationTransaction,
) -> PublicationPaths:
    """Resolve only the immediate children bound by a validated record."""
    return PublicationPaths(
        record_path(maps_root, transaction.transaction_id),
        maps_root / transaction.stage_name,
        maps_root / transaction.destination_name,
        maps_root / transaction.backup_name,
    )


def write_transaction(maps_root: Path, transaction: PublicationTransaction) -> None:
    """Atomically and durably persist one strict transaction record."""
    text = format_transaction(transaction)
    result = write_text_safely(
        str(maps_root),
        record_path(maps_root, transaction.transaction_id).name,
        text,
    )
    if result.status is not SafeWriteStatus.WRITTEN:
        raise BatchMapPublicationError(result.error or result.status.value)


def load_transaction(path: Path) -> PublicationTransaction:
    """Read and parse one bounded, no-follow transaction record."""
    payload, _identity = read_bounded_regular_file(path, _MAX_RECORD_BYTES)
    return _parse_transaction_payload(payload)


def _parse_transaction_payload(payload: bytes) -> PublicationTransaction:
    try:
        return parse_transaction(payload.decode("utf-8"))
    except UnicodeError as exc:
        raise PublicationRecordError("transaction record is not UTF-8") from exc


def remove_transaction(
    maps_root: Path,
    expected: PublicationTransaction,
) -> None:
    """Remove a record only while its full parsed value still matches."""
    path = Path(
        native_output_path(
            str(record_path(maps_root, expected.transaction_id).absolute())
        )
    )
    payload, identity = read_bounded_regular_file(path, _MAX_RECORD_BYTES)
    if _parse_transaction_payload(payload) != expected:
        raise BatchMapPublicationError("transaction record changed before cleanup")
    cleanup = remove_owned_record(path, (identity.device, identity.inode), payload)
    if cleanup.status is not StageCleanupStatus.REMOVED:
        raise BatchMapPublicationError(
            f"transaction record retained: {cleanup.detail or cleanup.status.value}"
        )
    sync_directory(maps_root)


def format_transaction(transaction: PublicationTransaction) -> str:
    """Serialize one transaction deterministically after semantic validation."""
    _validate_transaction(transaction)
    payload: dict[str, JsonValue] = {
        "backup_name": transaction.backup_name,
        "destination_name": transaction.destination_name,
        "manifest_sha256": transaction.manifest_sha256,
        "phase": transaction.phase.value,
        "source_sha256": transaction.source_sha256,
        "stage_name": transaction.stage_name,
        "transaction_id": transaction.transaction_id,
    }
    if transaction.stage_identity is not None:
        payload["stage_identity"] = list(transaction.stage_identity)
    if transaction.backup_identity is not None:
        payload["backup_identity"] = list(transaction.backup_identity)
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def parse_transaction(text: str) -> PublicationTransaction:
    """Parse a record and reject extra keys, unsafe names, and phase drift."""
    try:
        value: JsonValue = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PublicationRecordError(f"invalid transaction JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise PublicationRecordError("transaction record must be an object")
    expected = {
        "backup_name",
        "destination_name",
        "manifest_sha256",
        "phase",
        "source_sha256",
        "stage_name",
        "transaction_id",
    }
    if not expected <= set(value) <= expected | {"stage_identity", "backup_identity"}:
        raise PublicationRecordError("unexpected transaction keys")
    try:
        transaction = PublicationTransaction(
            _text(value["transaction_id"], "transaction ID"),
            PublicationPhase(_text(value["phase"], "phase")),
            _text(value["stage_name"], "stage name"),
            _text(value["destination_name"], "destination name"),
            _text(value["backup_name"], "backup name"),
            _text(value["source_sha256"], "source SHA-256"),
            _text(value["manifest_sha256"], "manifest SHA-256"),
            _stage_identity(value.get("stage_identity")),
            _stage_identity(value.get("backup_identity")),
        )
    except ValueError as exc:
        raise PublicationRecordError("invalid publication phase") from exc
    _validate_transaction(transaction)
    return transaction


def owned_source_digest(directory: Path) -> str | None:
    """Return the source digest only for a no-follow owned directory marker."""
    if directory.is_symlink() or not directory.is_dir():
        return None
    try:
        payload, _identity = read_bounded_regular_file(
            directory / OWNERSHIP_MARKER_NAME,
            _MAX_MARKER_BYTES,
        )
        text = payload.decode("utf-8")
        try:
            return parse_ownership_record(text).source_sha256
        except ValueError:
            digest = text.strip().lower()
            return digest if _SHA256.fullmatch(digest) is not None else None
    except OSError, UnicodeError:
        return None


def publication_matches(
    directory: Path,
    transaction: PublicationTransaction,
) -> bool:
    """Prove a directory is the exact new generation bound by a transaction."""
    validation = verify_map_publication(directory)
    manifest = validation.manifest
    return bool(
        validation.valid
        and manifest is not None
        and validation.manifest_sha256 == transaction.manifest_sha256
        and manifest.transaction_id == transaction.transaction_id
        and manifest.source.sha256 == transaction.source_sha256
    )


def owned_directory_identity(directory: Path, digest: str) -> tuple[int, int]:
    """Bind a source-owned existing directory while its ancestry remains held."""
    path = Path(native_output_path(str(directory.absolute())))
    with WindowsSourceRoot.open(path):
        if owned_source_digest(path) != digest:
            raise BatchMapPublicationError("refusing to replace unowned map output")
        identity = path.stat(follow_symlinks=False)
        if not identity.st_ino:
            raise BatchMapPublicationError("map directory identity is unavailable")
        return identity.st_dev, identity.st_ino


def _validate_transaction(transaction: PublicationTransaction) -> None:
    transaction_id = transaction.transaction_id
    if _TRANSACTION_ID.fullmatch(transaction_id) is None:
        raise PublicationRecordError("invalid transaction ID")
    if _SHA256.fullmatch(transaction.source_sha256) is None:
        raise PublicationRecordError("invalid source SHA-256")
    expected_stage = f".gamexray-map-stage-{transaction_id}"
    expected_backup = f".gamexray-map-backup-{transaction_id}"
    if transaction.stage_name != expected_stage:
        raise PublicationRecordError("transaction stage name mismatch")
    if transaction.backup_name != expected_backup:
        raise PublicationRecordError("transaction backup name mismatch")
    destination = Path(transaction.destination_name)
    if (
        not transaction.destination_name
        or destination.name != transaction.destination_name
        or transaction.destination_name.startswith(".")
    ):
        raise PublicationRecordError("unsafe transaction destination")
    if transaction.phase is PublicationPhase.BUILDING:
        if transaction.manifest_sha256:
            raise PublicationRecordError("building transaction has a manifest hash")
    elif _SHA256.fullmatch(transaction.manifest_sha256) is None:
        raise PublicationRecordError("invalid manifest SHA-256")
    if transaction.stage_identity is not None:
        _stage_identity(list(transaction.stage_identity))
    if transaction.backup_identity is not None:
        _stage_identity(list(transaction.backup_identity))


def _stage_identity(value: JsonValue) -> tuple[int, int] | None:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in value
        )
    ):
        raise PublicationRecordError("invalid stage directory identity")
    device, inode = value
    assert isinstance(device, int) and isinstance(inode, int)
    if not inode:
        raise PublicationRecordError("stage directory identity is unavailable")
    return device, inode


def _text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise PublicationRecordError(f"{label} must be text")
    return value

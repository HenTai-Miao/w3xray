"""Held directory bindings for append-only integrity-report history."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
import stat
from types import TracebackType
from typing import Literal, Self

from .descriptor_open_flags import directory_read_flags
from .durable_io import sync_directory_descriptor
from .integrity_report_history import (
    INTEGRITY_HISTORY_ROOT_NAME,
    IntegrityHistoryError,
)


@dataclass(frozen=True, slots=True)
class BoundIntegrityHistoryStage:
    """One held, uniquely named history generation before final publication."""

    destination: Path
    parent_descriptor: int
    root_descriptor: int
    bucket_descriptor: int
    stage_descriptor: int
    bucket_name: str
    stage_name: str
    generation_id: str
    stage_identity: tuple[int, int]

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        os.close(self.stage_descriptor)
        os.close(self.bucket_descriptor)
        os.close(self.root_descriptor)
        return False

    @property
    def stage_path(self) -> Path:
        """Return the expected display path for this never-deleted stage."""
        return (
            self.destination.parent
            / INTEGRITY_HISTORY_ROOT_NAME
            / self.bucket_name
            / self.stage_name
        )

    @property
    def generation_path(self) -> Path:
        """Return the expected final immutable generation display path."""
        return self.stage_path.with_name(self.generation_id)


def prepare_integrity_history_stage(
    parent_descriptor: int,
    destination: Path,
    forbidden_identities: frozenset[tuple[int, int]],
) -> BoundIntegrityHistoryStage:
    """Create and hold one append-only generation namespace."""
    root_descriptor = _open_or_create_directory(
        parent_descriptor,
        INTEGRITY_HISTORY_ROOT_NAME,
        forbidden_identities,
    )
    bucket_descriptor = -1
    stage_descriptor = -1
    try:
        bucket_name = hashlib.sha256(destination.name.encode("utf-8")).hexdigest()
        bucket_descriptor = _open_or_create_directory(
            root_descriptor,
            bucket_name,
            forbidden_identities,
        )
        for _ in range(16):
            generation_id = secrets.token_hex(16)
            stage_name = f".w3xray-history-stage-{generation_id}"
            try:
                os.mkdir(stage_name, 0o700, dir_fd=bucket_descriptor)
            except FileExistsError:
                continue
            sync_directory_descriptor(bucket_descriptor)
            stage_descriptor = os.open(
                stage_name,
                directory_read_flags(),
                dir_fd=bucket_descriptor,
            )
            stage_identity = _require_directory(
                bucket_descriptor,
                stage_name,
                stage_descriptor,
                forbidden_identities,
            )
            return BoundIntegrityHistoryStage(
                destination,
                parent_descriptor,
                root_descriptor,
                bucket_descriptor,
                stage_descriptor,
                bucket_name,
                stage_name,
                generation_id,
                stage_identity,
            )
        raise FileExistsError("could not allocate integrity history generation")
    except OSError:
        if stage_descriptor >= 0:
            os.close(stage_descriptor)
        if bucket_descriptor >= 0:
            os.close(bucket_descriptor)
        os.close(root_descriptor)
        raise


def require_history_stage_current(
    stage: BoundIntegrityHistoryStage,
    forbidden_identities: frozenset[tuple[int, int]],
) -> None:
    """Re-prove every held history directory and the stage's public binding."""
    _ = _require_directory(
        stage.parent_descriptor,
        INTEGRITY_HISTORY_ROOT_NAME,
        stage.root_descriptor,
        forbidden_identities,
    )
    _ = _require_directory(
        stage.root_descriptor,
        stage.bucket_name,
        stage.bucket_descriptor,
        forbidden_identities,
    )
    identity = _require_directory(
        stage.bucket_descriptor,
        stage.stage_name,
        stage.stage_descriptor,
        forbidden_identities,
    )
    if identity != stage.stage_identity:
        raise IntegrityHistoryError("integrity history stage identity changed")


def require_history_generation_current(
    stage: BoundIntegrityHistoryStage,
    forbidden_identities: frozenset[tuple[int, int]],
) -> None:
    """Re-prove the held history ancestry and finalized generation binding."""
    _ = _require_directory(
        stage.parent_descriptor,
        INTEGRITY_HISTORY_ROOT_NAME,
        stage.root_descriptor,
        forbidden_identities,
    )
    _ = _require_directory(
        stage.root_descriptor,
        stage.bucket_name,
        stage.bucket_descriptor,
        forbidden_identities,
    )
    identity = _require_directory(
        stage.bucket_descriptor,
        stage.generation_id,
        stage.stage_descriptor,
        forbidden_identities,
    )
    if identity != stage.stage_identity:
        raise IntegrityHistoryError("integrity history generation identity changed")


def _open_or_create_directory(
    parent_descriptor: int,
    name: str,
    forbidden_identities: frozenset[tuple[int, int]],
) -> int:
    created = False
    try:
        os.mkdir(name, 0o700, dir_fd=parent_descriptor)
        created = True
    except FileExistsError:
        created = False
    if created:
        sync_directory_descriptor(parent_descriptor)
    descriptor = os.open(name, directory_read_flags(), dir_fd=parent_descriptor)
    try:
        _ = _require_directory(
            parent_descriptor,
            name,
            descriptor,
            forbidden_identities,
        )
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def _require_directory(
    parent_descriptor: int,
    name: str,
    descriptor: int,
    forbidden_identities: frozenset[tuple[int, int]],
) -> tuple[int, int]:
    held = os.fstat(descriptor)
    named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    identity = held.st_dev, held.st_ino
    if (
        not stat.S_ISDIR(held.st_mode)
        or not stat.S_ISDIR(named.st_mode)
        or (named.st_dev, named.st_ino) != identity
        or stat.S_IMODE(held.st_mode) != 0o700
        or held.st_uid != os.geteuid()
        or identity in forbidden_identities
    ):
        raise IntegrityHistoryError("unsafe integrity history directory")
    return identity


__all__ = (
    "BoundIntegrityHistoryStage",
    "prepare_integrity_history_stage",
    "require_history_generation_current",
    "require_history_stage_current",
)

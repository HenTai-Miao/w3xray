"""Held-path integrity report publication outside protected namespaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
from types import TracebackType
from typing import Literal, Self, assert_never

from .description_cache_retained_binding import BoundActiveCache
from .description_cache_retained_integrity_models import (
    DescriptionCacheRetentionError,
)
from .integrity_output_path import (
    IntegrityOutputError,
    bind_retained_output_path,
    bind_snapshot_output_path,
)
from .integrity_path_binding import BoundDirectoryPath, IntegrityPathBindingError
from .integrity_report_publication import publish_integrity_report
from .integrity_report_publication_models import (
    IntegrityPublicationComplete,
    IntegrityStageCleanupRequired,
    IntegrityStageRetained,
)
from .integrity_snapshot_binding import BoundSnapshotRoot
from .integrity_snapshot_models import IntegritySnapshotError
from .safe_output_chunk_writer import write_chunks_to_descriptor
from .safe_output_models import SafeWriteResult, SafeWriteStatus
from .safe_output_staging import (
    destination_error,
    discard_file,
    open_staged_file,
)


@dataclass(frozen=True, slots=True)
class BoundIntegrityOutput:
    """One held output parent and a no-follow final destination name."""

    destination: Path
    parent: BoundDirectoryPath
    protected_identities: frozenset[tuple[int, int]]

    def __enter__(self) -> Self:
        self.parent.__enter__()
        try:
            self.require_current()
        except IntegrityOutputError, IntegrityPathBindingError:
            self.parent.close()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        return self.parent.__exit__(exc_type, exc_value, traceback)

    def require_current(self) -> None:
        """Re-prove the output ancestry and safe destination kind."""
        self.parent.require_current()
        unsafe = destination_error(self.parent.descriptor, self.destination.name)
        if unsafe is not None:
            raise IntegrityOutputError(unsafe)

    def write_text(
        self,
        payload: str,
        require_protected: Callable[[], None] | None = None,
    ) -> SafeWriteResult:
        """Stage and atomically publish text through the held parent."""
        self.require_current()
        try:
            descriptor, staged_name = open_staged_file(self.parent.descriptor)
        except OSError as exc:
            return SafeWriteResult(
                SafeWriteStatus.FAILED,
                str(self.destination),
                0,
                str(exc),
            )
        staged = os.fstat(descriptor)
        staged_identity = staged.st_dev, staged.st_ino
        try:
            size = write_chunks_to_descriptor(
                descriptor,
                (payload.encode("utf-8"),),
            )
        except OSError as exc:
            return discard_file(
                self.parent.descriptor,
                staged_name,
                staged_identity,
                str(self.destination),
                SafeWriteStatus.FAILED,
                str(exc),
            )
        finally:
            os.close(descriptor)
        publication = publish_integrity_report(
            self.parent.descriptor,
            staged_name,
            staged_identity,
            self.destination.name,
            self.destination,
            lambda: self._publication_error(require_protected),
            _failure_status,
            self.protected_identities,
        )
        match publication:
            case IntegrityPublicationComplete(result=result):
                if result is not None:
                    return result
            case IntegrityStageCleanupRequired(result=result):
                return discard_file(
                    self.parent.descriptor,
                    staged_name,
                    staged_identity,
                    result.path,
                    result.status,
                    result.error,
                )
            case IntegrityStageRetained(result=result):
                return result
            case unreachable:
                assert_never(unreachable)
        return SafeWriteResult(
            SafeWriteStatus.WRITTEN,
            str(self.destination),
            size,
        )

    def _publication_error(
        self,
        require_protected: Callable[[], None] | None,
    ) -> str | None:
        try:
            self.parent.require_current()
            if require_protected is not None:
                require_protected()
        except (
            DescriptionCacheRetentionError,
            IntegrityOutputError,
            IntegrityPathBindingError,
            IntegritySnapshotError,
            OSError,
        ) as exc:
            return str(exc)
        return None


def bind_snapshot_output(
    requested: Path,
    roots: tuple[BoundSnapshotRoot, ...],
) -> BoundIntegrityOutput:
    """Bind one output outside all held physical snapshot roots."""
    destination, parent, protected = bind_snapshot_output_path(requested, roots)
    return BoundIntegrityOutput(destination, parent, protected)


def bind_retained_output(
    requested: Path,
    active: BoundActiveCache,
) -> BoundIntegrityOutput:
    """Bind one output outside the held active and reserved cache objects."""
    destination, parent, protected = bind_retained_output_path(requested, active)
    return BoundIntegrityOutput(destination, parent, protected)


def _failure_status(exc: OSError) -> SafeWriteStatus:
    match exc.errno:
        case None:
            return SafeWriteStatus.FAILED
        case 20 | 21 | 40:
            return SafeWriteStatus.UNSAFE
        case int():
            return SafeWriteStatus.FAILED
        case unreachable:
            assert_never(unreachable)


__all__ = (
    "BoundIntegrityOutput",
    "IntegrityOutputError",
    "bind_retained_output",
    "bind_snapshot_output",
)

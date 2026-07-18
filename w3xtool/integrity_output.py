"""Held-path integrity report publication outside protected namespaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
from types import TracebackType
from typing import Literal, Self, assert_never, override

from .description_cache_retained_siblings import (
    BACKUP_PREFIX,
    RETAINED_PREFIX,
    STAGE_PREFIX,
)
from .description_cache_retained_integrity_models import (
    DescriptionCacheRetentionError,
)
from .integrity_path_binding import (
    BoundDirectoryPath,
    IntegrityPathBindingError,
    bind_directory_path,
)
from .safe_output_chunk_writer import write_chunks_to_descriptor
from .safe_output_models import SafeWriteResult, SafeWriteStatus
from .safe_output_publication import publish_staged_file
from .safe_output_staging import (
    destination_error,
    discard_file,
    open_staged_file,
    remove_owned_staged_file,
)


class IntegrityOutputError(OSError):
    """An integrity output path or publication crossed a safety boundary."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class BoundIntegrityOutput:
    """One held output parent and a no-follow final destination name."""

    destination: Path
    parent: BoundDirectoryPath

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
            try:
                size = write_chunks_to_descriptor(
                    descriptor,
                    (payload.encode("utf-8"),),
                )
            except OSError as exc:
                return discard_file(
                    self.parent.descriptor,
                    staged_name,
                    str(self.destination),
                    SafeWriteStatus.FAILED,
                    str(exc),
                )
            finally:
                os.close(descriptor)
            publication_error = publish_staged_file(
                self.parent.descriptor,
                staged_name,
                self.destination.name,
                str(self.destination),
                lambda: self._publication_error(require_protected),
                _failure_status,
            )
            if publication_error is not None:
                return publication_error
            return SafeWriteResult(
                SafeWriteStatus.WRITTEN,
                str(self.destination),
                size,
            )
        finally:
            remove_owned_staged_file(
                self.parent.descriptor,
                staged_name,
                staged_identity,
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
            OSError,
        ) as exc:
            return str(exc)
        return None


def bind_snapshot_output(
    requested: Path,
    roots: tuple[Path, ...],
) -> BoundIntegrityOutput:
    """Reject lexical/proven input containment and bind the output parent."""
    destination = _absolute_destination(requested)
    normalized_roots = tuple(_absolute_path(root) for root in roots)
    if any(
        destination == root or destination.is_relative_to(root)
        for root in normalized_roots
    ):
        raise IntegrityOutputError("output is inside a snapshot root")
    return _bind_output(destination)


def bind_retained_output(
    requested: Path,
    active_root: Path,
) -> BoundIntegrityOutput:
    """Reject active and all reserved sibling prefixes before binding output."""
    destination = _absolute_destination(requested)
    active = _absolute_path(active_root)
    if destination == active or destination.is_relative_to(active):
        raise IntegrityOutputError("output is inside the active cache")
    try:
        relative = destination.relative_to(active.parent)
    except ValueError:
        relative = None
    if relative is not None and relative.parts:
        first = relative.parts[0]
        if first == active.name or first.startswith(
            (RETAINED_PREFIX, STAGE_PREFIX, BACKUP_PREFIX)
        ):
            raise IntegrityOutputError("output uses a reserved cache publication name")
    return _bind_output(destination)


def _bind_output(destination: Path) -> BoundIntegrityOutput:
    if not destination.name or destination.name in {".", ".."}:
        raise IntegrityOutputError("output must name a file")
    try:
        parent = bind_directory_path(destination.parent, create=True)
    except IntegrityPathBindingError as exc:
        raise IntegrityOutputError(str(exc)) from exc
    return BoundIntegrityOutput(destination, parent)


def _absolute_destination(path: Path) -> Path:
    return _absolute_path(path)


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


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

"""Continuously held, physically nonoverlapping integrity snapshot roots."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import os
from pathlib import Path
from types import TracebackType
from typing import Literal

from .integrity_path_binding import (
    BoundDirectoryPath,
    IntegrityPathBindingError,
    bind_directory_path,
)
from .integrity_snapshot_models import IntegritySnapshotError, SnapshotRoot
from .integrity_utf8 import IntegrityUtf8Error, require_utf8_text


@dataclass(frozen=True, slots=True)
class BoundSnapshotRoot:
    """One requested label and its held no-follow directory ancestry."""

    requested: SnapshotRoot
    binding: BoundDirectoryPath


class SnapshotRootBindings:
    """Resource owner for one complete held snapshot-root set."""

    __slots__ = ("_roots", "_stack")

    def __init__(self, roots: tuple[SnapshotRoot, ...]) -> None:
        self._roots = roots
        self._stack = ExitStack()

    def __enter__(self) -> tuple[BoundSnapshotRoot, ...]:
        """Bind all roots before returning any descriptor to the scanner."""
        prepared = _preflight_roots(self._roots)
        try:
            bound = tuple(
                BoundSnapshotRoot(
                    item,
                    self._stack.enter_context(bind_directory_path(path)),
                )
                for item, path in prepared
            )
            _require_physical_nonoverlap(bound)
            return bound
        except IntegritySnapshotError:
            self._stack.close()
            raise
        except (IntegrityPathBindingError, OSError, NotImplementedError) as exc:
            self._stack.close()
            raise IntegritySnapshotError(f"cannot bind snapshot roots: {exc}") from exc

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """Re-prove on success and close all held root descriptors."""
        _ = self._stack.__exit__(exc_type, exc_value, traceback)
        return False


def bind_snapshot_roots(roots: tuple[SnapshotRoot, ...]) -> SnapshotRootBindings:
    """Return the resource owner for a physically nonoverlapping root set."""
    return SnapshotRootBindings(roots)


def require_snapshot_roots(roots: tuple[BoundSnapshotRoot, ...]) -> None:
    """Re-prove every root binding held by one snapshot operation."""
    for root in roots:
        root.binding.require_current()


def protected_root_identities(
    roots: tuple[BoundSnapshotRoot, ...],
) -> frozenset[tuple[int, int]]:
    """Return the final directory identity of every held protected root."""
    return frozenset(root.binding.identity_chain()[-1] for root in roots)


def _preflight_roots(
    roots: tuple[SnapshotRoot, ...],
) -> tuple[tuple[SnapshotRoot, Path], ...]:
    if not roots:
        raise IntegritySnapshotError("at least one root is required")
    labels: set[str] = set()
    paths: list[Path] = []
    prepared: list[tuple[SnapshotRoot, Path]] = []
    for item in roots:
        _require_external_text(item)
        if not item.label or item.label in labels:
            raise IntegritySnapshotError("root labels must be unique and nonempty")
        labels.add(item.label)
        path = Path(os.path.abspath(item.path.expanduser()))
        if any(
            path == previous
            or path.is_relative_to(previous)
            or previous.is_relative_to(path)
            for previous in paths
        ):
            raise IntegritySnapshotError("snapshot roots overlap")
        paths.append(path)
        prepared.append((item, path))
    return tuple(prepared)


def _require_external_text(item: SnapshotRoot) -> None:
    try:
        require_utf8_text(item.label, "snapshot root label")
        require_utf8_text(str(item.path), "snapshot root path")
    except IntegrityUtf8Error as exc:
        raise IntegritySnapshotError(str(exc)) from exc


def _require_physical_nonoverlap(roots: tuple[BoundSnapshotRoot, ...]) -> None:
    chains: list[tuple[tuple[int, int], ...]] = []
    for root in roots:
        chain = root.binding.identity_chain()
        if any(chain[-1] in previous or previous[-1] in chain for previous in chains):
            raise IntegritySnapshotError("snapshot roots physically overlap")
        chains.append(chain)


__all__ = (
    "BoundSnapshotRoot",
    "SnapshotRootBindings",
    "bind_snapshot_roots",
    "protected_root_identities",
    "require_snapshot_roots",
)

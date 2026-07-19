"""Lexical and physical path protection for integrity outputs."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import override

from .description_cache_retained_binding import BoundActiveCache
from .description_cache_retained_siblings import capture_relevant_siblings
from .integrity_path_binding import (
    BoundDirectoryPath,
    IntegrityPathBindingError,
    bind_directory_path,
)
from .integrity_output_naming import (
    is_reserved_output_name,
    probe_filesystem_naming,
)
from .integrity_report_history import INTEGRITY_HISTORY_ROOT_NAME
from .integrity_snapshot_binding import (
    BoundSnapshotRoot,
    protected_root_identities,
    require_snapshot_roots,
)
from .integrity_utf8 import IntegrityUtf8Error, require_utf8_text


class IntegrityOutputError(OSError):
    """An integrity output path crossed a protected physical boundary."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


def bind_snapshot_output_path(
    requested: Path,
    roots: tuple[BoundSnapshotRoot, ...],
) -> tuple[Path, BoundDirectoryPath, frozenset[tuple[int, int]]]:
    """Bind an output parent outside every continuously held snapshot root."""
    destination = _absolute_path(requested)
    require_snapshot_roots(roots)
    protected = protected_root_identities(roots)
    parent = _bind_parent(destination, protected)
    try:
        require_snapshot_roots(roots)
    except (IntegrityPathBindingError, OSError) as exc:
        parent.close()
        raise IntegrityOutputError(str(exc)) from exc
    return destination, parent, protected


def bind_retained_output_path(
    requested: Path,
    active: BoundActiveCache,
) -> tuple[Path, BoundDirectoryPath, frozenset[tuple[int, int]]]:
    """Bind outside the active root and every reserved retained sibling."""
    destination = _absolute_path(requested)
    active.require_current()
    siblings = capture_relevant_siblings(
        active.parent_descriptor,
        active.root.name,
    )
    protected = frozenset(
        (item.device, item.inode)
        for item in siblings
        if item.device is not None and item.inode is not None
    )
    parent = _bind_parent(destination, protected)
    try:
        active.require_current()
        if (
            capture_relevant_siblings(
                active.parent_descriptor,
                active.root.name,
            )
            != siblings
        ):
            raise IntegrityOutputError("reserved cache namespace changed")
        _require_destination_not_reserved(
            destination,
            parent,
            active,
            protected,
        )
    except (IntegrityOutputError, IntegrityPathBindingError, OSError) as exc:
        parent.close()
        raise IntegrityOutputError(str(exc)) from exc
    return destination, parent, protected


def _bind_parent(
    destination: Path,
    protected: frozenset[tuple[int, int]],
) -> BoundDirectoryPath:
    if not destination.name or destination.name in {".", ".."}:
        raise IntegrityOutputError("output must name a file")
    if destination.name == INTEGRITY_HISTORY_ROOT_NAME:
        raise IntegrityOutputError("output uses the integrity history root name")
    try:
        parent = bind_directory_path(
            destination.parent,
            create=True,
            forbidden_ancestors=protected,
        )
    except IntegrityPathBindingError as exc:
        raise IntegrityOutputError(str(exc)) from exc
    if destination.name.casefold() != INTEGRITY_HISTORY_ROOT_NAME.casefold():
        return parent
    try:
        behavior = probe_filesystem_naming(parent.descriptor)
    except OSError as exc:
        parent.close()
        raise IntegrityOutputError(str(exc)) from exc
    if behavior.key(destination.name) == behavior.key(INTEGRITY_HISTORY_ROOT_NAME):
        parent.close()
        raise IntegrityOutputError("output aliases the integrity history root name")
    return parent


def _require_destination_not_reserved(
    destination: Path,
    parent: BoundDirectoryPath,
    active: BoundActiveCache,
    protected: frozenset[tuple[int, int]],
) -> None:
    if parent.identity_chain()[-1] != active.parent_identity:
        return
    if is_reserved_output_name(
        parent.descriptor,
        destination.name,
        active.root.name,
    ):
        raise IntegrityOutputError("output uses a reserved cache publication name")
    try:
        details = os.stat(
            destination.name,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    identity = details.st_dev, details.st_ino
    if identity in protected or stat.S_ISDIR(details.st_mode):
        raise IntegrityOutputError("output aliases a reserved cache object")


def _absolute_path(path: Path) -> Path:
    try:
        require_utf8_text(str(path), "integrity output path")
    except IntegrityUtf8Error as exc:
        raise IntegrityOutputError(str(exc)) from exc
    return Path(os.path.abspath(path.expanduser()))


__all__ = (
    "IntegrityOutputError",
    "bind_retained_output_path",
    "bind_snapshot_output_path",
)

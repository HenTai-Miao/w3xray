"""Lexical and physical path protection for integrity outputs."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import unicodedata
from typing import override

from .description_cache_retained_binding import BoundActiveCache
from .description_cache_retained_siblings import (
    BACKUP_PREFIX,
    RETAINED_PREFIX,
    STAGE_PREFIX,
    capture_relevant_siblings,
)
from .integrity_path_binding import (
    BoundDirectoryPath,
    IntegrityPathBindingError,
    bind_directory_path,
)
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
) -> tuple[Path, BoundDirectoryPath]:
    """Bind an output parent outside every continuously held snapshot root."""
    destination = _absolute_path(requested)
    if any(_canonically_contained(destination, root.binding.path) for root in roots):
        raise IntegrityOutputError("output is inside a snapshot root")
    require_snapshot_roots(roots)
    parent = _bind_parent(destination, protected_root_identities(roots))
    try:
        require_snapshot_roots(roots)
    except (IntegrityPathBindingError, OSError) as exc:
        parent.close()
        raise IntegrityOutputError(str(exc)) from exc
    return destination, parent


def bind_retained_output_path(
    requested: Path,
    active: BoundActiveCache,
) -> tuple[Path, BoundDirectoryPath]:
    """Bind outside the active root and every reserved retained sibling."""
    destination = _absolute_path(requested)
    active.require_current()
    siblings = capture_relevant_siblings(
        active.parent_descriptor,
        active.root.name,
    )
    if _retained_path_error(destination, active.root) is not None:
        raise IntegrityOutputError(_retained_path_error(destination, active.root) or "")
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
    return destination, parent


def _bind_parent(
    destination: Path,
    protected: frozenset[tuple[int, int]],
) -> BoundDirectoryPath:
    if not destination.name or destination.name in {".", ".."}:
        raise IntegrityOutputError("output must name a file")
    try:
        return bind_directory_path(
            destination.parent,
            create=True,
            forbidden_ancestors=protected,
        )
    except IntegrityPathBindingError as exc:
        raise IntegrityOutputError(str(exc)) from exc


def _retained_path_error(destination: Path, active: Path) -> str | None:
    if _canonically_contained(destination, active):
        return "output is inside the active cache"
    relative = _canonical_relative(destination, active.parent)
    if relative and _reserved_name(relative[0], active.name):
        return "output uses a reserved cache publication name"
    return None


def _require_destination_not_reserved(
    destination: Path,
    parent: BoundDirectoryPath,
    active: BoundActiveCache,
    protected: frozenset[tuple[int, int]],
) -> None:
    if parent.identity_chain()[-1] != active.parent_identity:
        return
    if _reserved_name(destination.name, active.root.name):
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


def _reserved_name(name: str, active_name: str) -> bool:
    normalized = _canonical_name(name)
    return normalized == _canonical_name(active_name) or normalized.startswith(
        tuple(
            _canonical_name(value)
            for value in (RETAINED_PREFIX, STAGE_PREFIX, BACKUP_PREFIX)
        )
    )


def _canonically_contained(path: Path, root: Path) -> bool:
    relative = _canonical_relative(path, root)
    return relative is not None


def _canonical_relative(path: Path, root: Path) -> tuple[str, ...] | None:
    path_parts = tuple(_canonical_name(value) for value in path.parts)
    root_parts = tuple(_canonical_name(value) for value in root.parts)
    if len(path_parts) < len(root_parts) or path_parts[: len(root_parts)] != root_parts:
        return None
    return path.parts[len(root_parts) :]


def _canonical_name(value: str) -> str:
    return unicodedata.normalize("NFD", value).casefold()


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

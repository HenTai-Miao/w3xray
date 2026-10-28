"""Portable input fixtures for codecs and pre-publication migration proofs.

These helpers never claim POSIX anchoring or atomic publication on Windows.
Migration decisions come from the real controller; a sentinel observes them
before the retired publisher runs. Report inputs are explicit typed proofs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import stat
from types import TracebackType
from typing import Never

import pytest

from gametool import description_cache_migration as migration
from gametool.anchored_source import (
    AnchoredRead,
    AnchoredSourceError,
    AnchoredSourceNotFoundError,
)
from gametool.bounded_file import read_bounded_regular_file
from gametool.description_cache_migration_exports import format_migration_payloads
from gametool.description_cache_migration_models import (
    DescriptionCacheMigrationOptions,
    DescriptionCacheRejection,
    ProvenDescriptionCandidate,
)
from gametool.description_cache_models import DescriptionCache
from gametool.description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_MANIFEST,
    TRUSTED_DESCRIPTION_CACHE_MARKER,
    TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY,
    TRUSTED_DESCRIPTION_CACHE_SCHEMA,
    TrustedCacheArtifact,
    TrustedCacheManifest,
    format_trusted_cache_manifest,
    format_trusted_cache_marker,
    trusted_content_sha256,
)
from gametool.description_cache_retained_classification import _classify_proof
from gametool.description_cache_retained_integrity_models import (
    DESCRIPTION_CACHE_RETENTION_SCHEMA,
    CacheArtifactKind,
    DescriptionCacheRetentionReport,
    MalformedDescriptionCacheArtifact,
    RetainedDescriptionCacheArtifact,
    RetainedTreeProof,
    RetentionArtifactReason,
    SiblingState,
    TransientDescriptionCacheArtifact,
    TreeEntryState,
    TreeProofStatus,
)
from gametool.description_cache_retained_report import (
    format_description_cache_retention_report,
    parse_description_cache_retention_report,
)
from gametool.description_cache_retained_set_scan import (
    _classify_stage_or_backup,
    _malformed,
)
from gametool.description_cache_retained_siblings import (
    RETAINED_PREFIX,
    kind_from_mode,
    parse_retained_name,
)
from gametool.description_cache_retained_tree import retained_tree_sha256
from gametool.integrity_snapshot import (
    INTEGRITY_SNAPSHOT_SCHEMA,
    IntegrityEntry,
    IntegrityRoot,
    IntegritySnapshot,
    SnapshotRoot,
    format_integrity_snapshot,
    parse_integrity_snapshot,
    tree_sha256,
)
from gametool.trusted_description_cache import load_trusted_description_cache
from gametool.windows_output_paths import native_output_path


def _file_state(path: Path) -> tuple[int, int, int, int, int, int]:
    details = path.lstat()
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


class _PortableMigrationSource:
    """Real temporary-file reads, without pretending to hold POSIX dir-fds."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.identity = _file_state(path)[:2]

    @classmethod
    def open(cls, path: Path) -> _PortableMigrationSource:
        return cls(path)

    def __enter__(self) -> _PortableMigrationSource:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self, relative: PurePosixPath, maximum: int | None = None) -> AnchoredRead:
        path = self.path.joinpath(*relative.parts)
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            raise AnchoredSourceError(path, "fixture source escapes its root")
        try:
            if _file_state(self.path)[:2] != self.identity:
                raise AnchoredSourceError(path, "fixture source-root identity changed")
            cursor = self.path
            for part in relative.parts:
                cursor /= part
                if cursor.is_symlink():
                    raise AnchoredSourceError(path, "fixture source is a symlink")
            before = _file_state(path)
            first, identity = read_bounded_regular_file(path, maximum)
            second, _ = read_bounded_regular_file(path, maximum, expected=identity)
            if first != second or _file_state(path) != before:
                raise AnchoredSourceError(path, "fixture source changed while reading")
            return AnchoredRead(first, identity)
        except FileNotFoundError as error:
            raise AnchoredSourceNotFoundError(path, str(error)) from error


@dataclass(frozen=True, slots=True)
class MigrationProofObservation:
    """Actual controller decisions plus independently parsed fixture payloads."""

    cache: DescriptionCache
    proven: tuple[ProvenDescriptionCandidate, ...]
    rejections: tuple[DescriptionCacheRejection, ...]
    output: Path

    @property
    def accepted_count(self) -> int:
        return len(self.cache.entries)

    @property
    def rejected_count(self) -> int:
        return len(self.rejections)


class _MigrationProofReached(Exception):
    def __init__(self, observation: MigrationProofObservation) -> None:
        super().__init__("pre-publication proof boundary reached")
        self.observation = observation


def _materialize_proof_payloads(
    source_root: Path,
    output: Path,
    proven: Sequence[ProvenDescriptionCandidate],
    rejections: Sequence[DescriptionCacheRejection],
) -> Never:
    """Write genuine codec inputs and stop before any atomic-publication claim."""
    payloads = format_migration_payloads(proven, rejections)
    artifacts = tuple(
        sorted(
            (
                TrustedCacheArtifact(
                    name,
                    len(text.encode("utf-8")),
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
                for name, text in payloads.items()
            ),
            key=lambda item: item.name.casefold(),
        )
    )
    manifest = TrustedCacheManifest(
        TRUSTED_DESCRIPTION_CACHE_SCHEMA,
        str(source_root),
        artifacts,
        trusted_content_sha256(artifacts),
    )
    manifest_text = format_trusted_cache_manifest(manifest)
    texts = {
        **payloads,
        TRUSTED_DESCRIPTION_CACHE_MANIFEST: manifest_text,
        TRUSTED_DESCRIPTION_CACHE_MARKER: format_trusted_cache_marker(
            hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
        ),
    }
    output.mkdir()
    for name in TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY:
        (output / name).write_text(texts[name], encoding="utf-8", newline="")
    verified = load_trusted_description_cache(output)
    raise _MigrationProofReached(
        MigrationProofObservation(
            verified.cache, tuple(proven), tuple(rejections), output
        )
    )


def observe_migration_proof(
    options: DescriptionCacheMigrationOptions,
) -> MigrationProofObservation:
    """Exercise the real preflight/proof/conflict controller up to publication."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(migration, "AnchoredSourceRoot", _PortableMigrationSource)
        patch.setattr(
            migration, "publish_description_cache", _materialize_proof_payloads
        )
        try:
            migration.migrate_description_cache(options)
        except _MigrationProofReached as reached:
            return reached.observation
    raise AssertionError("the real controller did not reach its proof observation")


def snapshot_fixture(roots: tuple[SnapshotRoot, ...]) -> IntegritySnapshot:
    """Construct typed codec inputs from ordinary private files and real metadata."""
    values = []
    for requested in roots:
        root = requested.path.resolve()
        entries = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            payload = path.read_bytes()
            details = path.stat()
            entries.append(
                IntegrityEntry(
                    path.relative_to(root).as_posix(),
                    len(payload),
                    details.st_mtime_ns,
                    hashlib.sha256(payload).hexdigest(),
                )
            )
        ordered = tuple(entries)
        values.append(
            IntegrityRoot(
                requested.label,
                str(root),
                ordered,
                sum(entry.size for entry in ordered),
                tree_sha256(ordered),
            )
        )
    snapshot = IntegritySnapshot(
        INTEGRITY_SNAPSHOT_SCHEMA, tuple(sorted(values, key=lambda item: item.label))
    )
    if parse_integrity_snapshot(format_integrity_snapshot(snapshot)) != snapshot:
        raise AssertionError("portable snapshot fixture did not round-trip")
    return snapshot


def _sibling(path: Path) -> SiblingState:
    details = path.lstat()
    return SiblingState(
        path.name,
        kind_from_mode(details.st_mode),
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def _ordinary_tree_proof(path: Path) -> RetainedTreeProof:
    entries = []
    payloads = []
    path_io = Path(native_output_path(str(path)))
    for child in sorted(path_io.rglob("*")):
        details = child.lstat()
        kind = kind_from_mode(details.st_mode)
        payload = child.read_bytes() if kind is CacheArtifactKind.REGULAR_FILE else None
        relative = child.relative_to(path_io).as_posix()
        entries.append(
            TreeEntryState(
                relative,
                kind,
                details.st_dev,
                details.st_ino,
                details.st_size,
                details.st_mtime_ns,
                details.st_ctime_ns,
                details.st_mode,
                None if payload is None else hashlib.sha256(payload).hexdigest(),
            )
        )
        if (
            payload is not None
            and relative in TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY
        ):
            payloads.append((relative, payload))
    ordered = tuple(entries)
    files = tuple(
        item for item in ordered if item.kind is CacheArtifactKind.REGULAR_FILE
    )
    return RetainedTreeProof(
        TreeProofStatus.COMPLETE,
        ordered,
        sum(item.size or 0 for item in files),
        len(files),
        len(ordered),
        retained_tree_sha256(ordered),
        None,
        tuple(payloads),
    )


def report_fixture(
    active: Path,
    paths: tuple[Path, ...] = (),
    *,
    unsafe_previous: Path | None = None,
    unsafe_sibling: Path | None = None,
    include_publication_names: bool = False,
) -> DescriptionCacheRetentionReport:
    """Classify real plain-file proofs or explicit unsafe typed proof inputs."""
    rows: list[RetainedDescriptionCacheArtifact] = []
    for path in paths:
        state = _sibling(path)
        parsed = parse_retained_name(path.name)
        if parsed is None:
            raise AssertionError("fixture retained name is invalid")
        if state.kind is CacheArtifactKind.DIRECTORY:
            proof = _ordinary_tree_proof(path)
        else:
            payload = path.read_bytes()
            proof = RetainedTreeProof(
                TreeProofStatus.COMPLETE,
                (),
                len(payload),
                1,
                0,
                hashlib.sha256(payload).hexdigest(),
                None,
            )
        rows.append(_classify_proof(path, *parsed, state, proof))
    if unsafe_previous is not None:
        parsed = parse_retained_name(unsafe_previous.name)
        if parsed is None:
            raise AssertionError("fixture previous name is invalid")
        proof = RetainedTreeProof(
            TreeProofStatus.UNSAFE, (), None, None, None, None, "nested/unsafe"
        )
        rows.append(
            _classify_proof(unsafe_previous, *parsed, _sibling(unsafe_previous), proof)
        )
    if unsafe_sibling is not None:
        parsed = parse_retained_name(unsafe_sibling.name)
        if parsed is None:
            raise AssertionError("fixture unsafe name is invalid")
        state = SiblingState(
            unsafe_sibling.name,
            CacheArtifactKind.SYMLINK,
            1,
            2,
            0,
            0,
            0,
            stat.S_IFLNK,
        )
        proof = RetainedTreeProof(
            TreeProofStatus.UNSAFE, (), None, None, None, None, None
        )
        rows.append(_classify_proof(unsafe_sibling, *parsed, state, proof))
    transient: list[TransientDescriptionCacheArtifact] = []
    malformed: list[MalformedDescriptionCacheArtifact] = []
    if include_publication_names:
        for path in active.parent.iterdir():
            if not path.name.startswith(".gamexray-description-cache-"):
                continue
            state = _sibling(path)
            if state.name.startswith(RETAINED_PREFIX):
                malformed.append(
                    _malformed(
                        active,
                        state,
                        RETAINED_PREFIX,
                        RetentionArtifactReason.MALFORMED_RETAINED_NAME,
                    )
                )
            else:
                _classify_stage_or_backup(active, state, transient, malformed)
    active_details = active.stat()
    report = DescriptionCacheRetentionReport(
        DESCRIPTION_CACHE_RETENTION_SCHEMA,
        active,
        active_details.st_dev,
        active_details.st_ino,
        tuple(
            sorted(
                rows,
                key=lambda item: (
                    item.path.as_posix().encode("utf-8"),
                    item.role.value,
                ),
            )
        ),
        tuple(
            sorted(
                transient,
                key=lambda item: (
                    item.path.as_posix().encode("utf-8"),
                    item.reason.value,
                ),
            )
        ),
        tuple(
            sorted(
                malformed,
                key=lambda item: (
                    item.path.as_posix().encode("utf-8"),
                    item.reason.value,
                ),
            )
        ),
    )
    # Negative tests must start from a report the real public codec accepts.
    parsed_report = parse_description_cache_retention_report(
        format_description_cache_retention_report(report)
    )
    if parsed_report != report:
        raise AssertionError("portable report fixture did not round-trip")
    return report

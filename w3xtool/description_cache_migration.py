"""Fail-closed migration boundary for historical description evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Final, assert_never

from .anchored_source import (
    AnchoredSourceError,
    AnchoredSourceNotFoundError,
    AnchoredSourceRoot,
)
from .bounded_file import read_bounded_regular_file
from .description_cache_migration_models import (
    DescriptionCacheMigrationError,
    DescriptionCacheMigrationOptions,
    DescriptionCacheMigrationResult,
    DescriptionCacheRejection,
    DescriptionCacheRejectionReason,
    LegacySourceReport,
    LegacyStateResult,
    ProvenDescriptionCandidate,
)
from .description_cache_migration_rows import (
    parse_legacy_cache,
    parse_legacy_report,
    prove_candidate,
)
from .description_cache_migration_state import parse_legacy_state
from .description_cache_publication import publish_description_cache


_STATE_NAME: Final = "批量提取状态.json"
_REPORT_NAME: Final = "对象描述.tsv"
_MAX_STATE_BYTES: Final = 64 * 1024 * 1024
_MAX_CACHE_BYTES: Final = 512 * 1024 * 1024
_MAX_REPORT_BYTES: Final = 512 * 1024 * 1024


def migrate_description_cache(
    options: DescriptionCacheMigrationOptions,
) -> DescriptionCacheMigrationResult:
    """Migrate only evidence proven by exact historical state and reports."""
    legacy_root, cache_path, output = _preflight_paths(options)
    try:
        with AnchoredSourceRoot.open(legacy_root) as source_root:
            return _migrate_from_source(source_root, legacy_root, cache_path, output)
    except AnchoredSourceError as exc:
        raise DescriptionCacheMigrationError(
            f"cannot read stable source input: {exc}"
        ) from exc


def _migrate_from_source(
    source_root: AnchoredSourceRoot,
    legacy_root: Path,
    cache_path: Path,
    output: Path,
) -> DescriptionCacheMigrationResult:
    state_payload = source_root.read(
        PurePosixPath(_STATE_NAME),
        _MAX_STATE_BYTES,
    ).payload
    results = parse_legacy_state(state_payload)
    reports = _load_reports(source_root, legacy_root, results)
    cache_payload = _read_stable(cache_path, _MAX_CACHE_BYTES)
    candidates = parse_legacy_cache(cache_payload, str(cache_path))
    accepted: list[ProvenDescriptionCandidate] = []
    rejections: list[DescriptionCacheRejection] = []
    for candidate in candidates:
        match prove_candidate(candidate, reports):
            case ProvenDescriptionCandidate() as proven:
                accepted.append(proven)
            case DescriptionCacheRejection() as rejection:
                rejections.append(rejection)
            case unreachable:
                assert_never(unreachable)
    grouped: dict[
        tuple[str, str, str, int | None], list[ProvenDescriptionCandidate]
    ] = {}
    for item in accepted:
        key = (
            item.candidate.category,
            item.candidate.base_id,
            item.candidate.role,
            item.level,
        )
        grouped.setdefault(key, []).append(item)
    conflicts = {
        key
        for key, values in grouped.items()
        if len({item.candidate.raw_value for item in values}) > 1
    }
    retained: list[ProvenDescriptionCandidate] = []
    for item in accepted:
        key = (
            item.candidate.category,
            item.candidate.base_id,
            item.candidate.role,
            item.level,
        )
        if key not in conflicts:
            retained.append(item)
            continue
        candidate = item.candidate
        reason = DescriptionCacheRejectionReason.CONFLICTING_VALUE
        rejections.append(
            DescriptionCacheRejection(
                candidate.row_number,
                candidate.category,
                candidate.base_id,
                candidate.role,
                candidate.level_text,
                candidate.raw_value,
                candidate.readable_value,
                candidate.source_map_sha256,
                candidate.source_path,
                reason,
                reason.value,
            )
        )
    rejections.sort(key=lambda row: row.row_number)
    publication = publish_description_cache(legacy_root, output, retained, rejections)
    return DescriptionCacheMigrationResult.from_publication(
        publication,
        rejections,
        output,
    )


def _preflight_paths(
    options: DescriptionCacheMigrationOptions,
) -> tuple[Path, Path, Path]:
    legacy_root = _canonical_directory(options.legacy_output, "legacy output")
    cache_path = _canonical_file(options.legacy_cache, "legacy cache")
    output_parent = _canonical_directory(options.output.parent, "output parent")
    output_name = options.output.name
    if not output_name or output_name in {".", ".."}:
        raise DescriptionCacheMigrationError("output path is unsafe")
    output = output_parent / output_name
    if output.is_symlink():
        raise DescriptionCacheMigrationError("output path is unsafe")
    if _overlaps(output, legacy_root) or _overlaps(output, cache_path):
        raise DescriptionCacheMigrationError("migration input and output overlap")
    return legacy_root, cache_path, output


def _canonical_directory(path: Path, label: str) -> Path:
    absolute = path.expanduser().absolute()
    if absolute.is_symlink() or not absolute.is_dir():
        raise DescriptionCacheMigrationError(f"{label} is not a regular directory")
    resolved = absolute.resolve(strict=True)
    if resolved != absolute:
        raise DescriptionCacheMigrationError(f"{label} traverses a symlink")
    return resolved


def _canonical_file(path: Path, label: str) -> Path:
    absolute = path.expanduser().absolute()
    if absolute.is_symlink() or not absolute.is_file():
        raise DescriptionCacheMigrationError(f"{label} is not a regular file")
    resolved = absolute.resolve(strict=True)
    if resolved != absolute:
        raise DescriptionCacheMigrationError(f"{label} traverses a symlink")
    return resolved


def _overlaps(first: Path, second: Path) -> bool:
    return (
        first == second or first.is_relative_to(second) or second.is_relative_to(first)
    )


def _read_stable(path: Path, maximum: int) -> bytes:
    try:
        first, identity = read_bounded_regular_file(path, maximum)
        second, _repeated = read_bounded_regular_file(
            path,
            maximum,
            expected=identity,
        )
    except OSError as exc:
        raise DescriptionCacheMigrationError(
            f"cannot read stable input {path}: {exc}"
        ) from exc
    if first != second:
        raise DescriptionCacheMigrationError(f"input changed while reading: {path}")
    return first


def _load_reports(
    source_root: AnchoredSourceRoot,
    root: Path,
    results: tuple[LegacyStateResult, ...],
) -> tuple[LegacySourceReport, ...]:
    reports: list[LegacySourceReport] = []
    report_identities: set[tuple[int, int]] = set()
    for state in results:
        relative = PurePosixPath(state.output_directory) / _REPORT_NAME
        path = root.joinpath(*relative.parts)
        try:
            anchored = source_root.read(relative, _MAX_REPORT_BYTES)
        except AnchoredSourceNotFoundError:
            reports.append(LegacySourceReport(state, path, None, ()))
            continue
        except AnchoredSourceError:
            raise
        identity = anchored.identity.device, anchored.identity.inode
        if identity in report_identities:
            raise DescriptionCacheMigrationError(
                "duplicate legacy source report identity"
            )
        report_identities.add(identity)
        payload = anchored.payload
        rows = parse_legacy_report(payload, str(path))
        reports.append(
            LegacySourceReport(
                state,
                path,
                hashlib.sha256(payload).hexdigest(),
                rows,
            )
        )
    return tuple(reports)


__all__ = (
    "DescriptionCacheMigrationError",
    "DescriptionCacheMigrationOptions",
    "DescriptionCacheMigrationResult",
    "DescriptionCacheRejection",
    "DescriptionCacheRejectionReason",
    "migrate_description_cache",
)

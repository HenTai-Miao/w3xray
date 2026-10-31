"""Recover archive file names from embedded resource references."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
import hashlib
from itertools import chain
import json
import os
import re
import struct
from typing import Final, Protocol

from . import mpq_resource_hints
from .mpq import HASH_NAME_A, HASH_NAME_B, _hash as _hash, guess_extension
from .mpq_crypto import hash_name_bytes
from .mpq_names import HashEntry, encoded_name_candidates
from .safe_output import (
    SafeWriteStatus,
    safe_destination,
    safe_relative_path,
    write_bytes_safely,
    write_text_safely,
)
from .windows_output_paths import native_output_path
from .war3_encoding import default_legacy_codecs

_RESOURCE_NAME_RE = re.compile(
    rb"(?i)(?<![A-Za-z0-9_ .()\\/\-\x80-\xff])([A-Za-z0-9_ .()\\/\-\x80-\xff]+\."
    rb"(?:blp|mdx|mdl|wav|mp3|ogg|tga|dds|txt|slk|ttf|j|lua|doo|wtg|wct|"
    rb"w3u|w3t|w3a|w3q|w3b|w3d|w3h|w3r|w3c|w3s|wgc))"
)
_MAX_RECOVERY_SCAN_BYTES: Final[int | None] = None
_MAX_RECOVERY_EXPORT_BYTES: Final[int | None] = None


class _RecoveryBlock(Protocol):
    file_size: int
    flags: int


class RecoveryArchive(Protocol):
    block_table: Sequence[_RecoveryBlock]
    hash_table: Sequence[HashEntry | tuple[int, int, int, int, int]]

    def list_files(self) -> list[str]: ...

    def read_file_entry(self, name: str, entry: HashEntry) -> bytes: ...

    def block_index_of(self, name: str) -> int | None: ...

    def iter_blocks(self) -> Iterable[tuple[int, _RecoveryBlock]]: ...

    def read_block_anon(self, block) -> bytes | None: ...


def _export_recovered_named_files(
    archive: RecoveryArchive,
    out_dir: str,
    exported_blocks: set[int],
    *,
    name_hints: Iterable[str] = (),
    published_names: Mapping[int, str] | None = None,
) -> int:
    """Recover exact entries; retain other locales in separate output files."""
    # Keep the catalog's exact spellings alongside derived filename hints.
    # Neither path normalization nor membership in a stock-name catalog proves
    # an archive member: the existing indexed hash lookup and exact entry read do.
    catalog_candidates = set(mpq_resource_hints.RESOURCE_NAME_HINTS)
    for name in mpq_resource_hints.RESOURCE_NAME_HINTS:
        catalog_candidates.update(_resource_name_variants(name))
    candidates = set(catalog_candidates)
    legacy_codecs = getattr(archive, "legacy_codecs", None)
    for name in chain(archive.list_files() or (), name_hints):
        candidates.update(_resource_name_variants(name))
    scanned_blocks: set[int] = set()
    scanned_bytes = 0
    for index, block in archive.iter_blocks():
        remaining = _remaining(_MAX_RECOVERY_SCAN_BYTES, scanned_bytes)
        if remaining is not None and remaining <= 0:
            break
        declared = max(1, block.file_size)
        if remaining is not None and declared > remaining:
            continue
        data = archive.read_block_anon(block)
        scanned_bytes += max(declared, len(data) if data is not None else 0)
        if data is None or (remaining is not None and len(data) > remaining):
            continue
        scanned_blocks.add(index)
        candidates.update(_resource_name_candidates(data, legacy_codecs=legacy_codecs))

    entries: dict[tuple[int, int], list[tuple[int, HashEntry]]] = {}
    seen_entries: set[HashEntry] = set()
    raw_entries: Sequence[HashEntry | tuple[int, int, int, int, int]] = getattr(
        archive, "hash_table", ()
    )
    for hash_index, raw_entry in enumerate(raw_entries):
        entry = HashEntry(*raw_entry)
        if (
            not 0 <= entry.block_index < len(archive.block_table)
            or entry in seen_entries
        ):
            continue
        seen_entries.add(entry)
        entries.setdefault((entry.name_a, entry.name_b), []).append((hash_index, entry))

    pending = deque(sorted(candidates, key=_candidate_order))
    queued = set(pending)
    manifest: list[str] = []
    published = {index: (name, name) for index, name in (published_names or {}).items()}
    count = exported_bytes = 0
    while pending:
        name = pending.popleft()
        pairs = {
            (hash_name_bytes(raw, HASH_NAME_A), hash_name_bytes(raw, HASH_NAME_B))
            for raw in encoded_name_candidates(name, legacy_codecs)
        }
        for pair in sorted(pairs):
            for hash_index, entry in entries.get(pair, ()):
                index = entry.block_index
                already_exported = index in exported_blocks
                declared = max(1, archive.block_table[index].file_size)
                remaining = (
                    _remaining(_MAX_RECOVERY_SCAN_BYTES, scanned_bytes)
                    if already_exported
                    else _remaining(_MAX_RECOVERY_EXPORT_BYTES, exported_bytes)
                )
                identity = (
                    f"block={index}\tlocale={entry.locale}\tplatform={entry.platform}"
                    f"\thash_index={hash_index}\tname={json.dumps(name, ensure_ascii=False)}"
                )
                if name in catalog_candidates:
                    identity += "\thint_catalog=" + json.dumps(
                        mpq_resource_hints.CATALOG_ID
                    )
                if remaining is not None and declared > remaining:
                    manifest.append(f"SKIP\t{identity}\treason=size-limit")
                    continue
                try:
                    data = archive.read_file_entry(name, entry)
                except (KeyError, OSError, ValueError) as error:
                    if already_exported:
                        scanned_bytes += declared
                    else:
                        exported_bytes += declared
                    manifest.append(
                        f"FAIL\t{identity}\treason=entry-read-{type(error).__name__}"
                    )
                    continue
                consumed = max(declared, len(data))
                if already_exported:
                    scanned_bytes += consumed
                else:
                    exported_bytes += consumed
                if remaining is not None and len(data) > remaining:
                    manifest.append(f"SKIP\t{identity}\treason=size-limit")
                    continue
                if index not in scanned_blocks:
                    for candidate in sorted(
                        _resource_name_candidates(data, legacy_codecs=legacy_codecs),
                        key=_candidate_order,
                    ):
                        if candidate not in queued:
                            pending.append(candidate)
                            queued.add(candidate)
                    scanned_blocks.add(index)
                if already_exported:
                    previous = published.get(index)
                    path = (
                        ""
                        if previous is None
                        else f"\tpath={json.dumps(previous[0], ensure_ascii=False)}"
                    )
                    reason = (
                        "verified-alternative-name-for-same-block"
                        if previous is not None and name != previous[1]
                        else "verified-entry-for-exported-block"
                    )
                    manifest.append(
                        f"ALIAS\t{identity}{path}\tsize={len(data)}"
                        f"\tsha256={hashlib.sha256(data).hexdigest()}\treason={reason}"
                    )
                    continue
                destination = _recovered_destination(
                    archive, out_dir, name, entry, data
                )
                if destination is None:
                    manifest.append(f"UNSAFE\t{identity}")
                    continue
                result = write_bytes_safely(out_dir, destination, data)
                if result.status is not SafeWriteStatus.WRITTEN:
                    manifest.append(f"{result.status.name}\t{identity}")
                    continue
                exported_blocks.add(index)
                published[index] = destination, name
                manifest.append(
                    f"OK\t{identity}\tpath={json.dumps(destination, ensure_ascii=False)}"
                    f"\tsize={len(data)}\ttype={guess_extension(data)}"
                    f"\tsha256={hashlib.sha256(data).hexdigest()}"
                )
                count += 1
    _export_name_hint_catalog(out_dir)
    if manifest:
        destination = _unused_destination(out_dir, "RecoveredNames/manifest.tsv")
        if destination is not None:
            write_text_safely(out_dir, destination, "\n".join(manifest) + "\n")
    return count


def _export_name_hint_catalog(out_dir: str) -> None:
    """Record candidate provenance separately from verified member records."""
    destination = _unused_destination(out_dir, "RecoveredNames/name-hint-catalog.json")
    if destination is None:
        return
    provenance = {
        "schema_version": mpq_resource_hints.CATALOG_SCHEMA_VERSION,
        "catalog_id": mpq_resource_hints.CATALOG_ID,
        "candidate_only": True,
        "game_version": None,
        "hint_count": mpq_resource_hints.RESOURCE_NAME_COUNT,
        "ordered_names_sha256": mpq_resource_hints.RESOURCE_NAMES_SHA256,
        "source_repository": mpq_resource_hints.SOURCE_REPOSITORY,
        "source_commit": mpq_resource_hints.SOURCE_COMMIT,
        "source_file": mpq_resource_hints.SOURCE_FILE,
        "source_file_sha256": mpq_resource_hints.SOURCE_FILE_SHA256,
        "source_document": mpq_resource_hints.SOURCE_DOCUMENT,
        "source_document_sha256": mpq_resource_hints.SOURCE_DOCUMENT_SHA256,
        "source_declared_inputs": [
            {"name": name, "sha256": digest}
            for name, digest in mpq_resource_hints.SOURCE_REFERENCE_SHA256
        ],
        "confirmation": "MPQ hash probe-chain membership and exact entry read",
    }
    write_text_safely(
        out_dir,
        destination,
        json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def _remaining(limit: int | None, consumed: int) -> int | None:
    return None if limit is None else limit - consumed


def _candidate_order(name: str) -> tuple[bool, int, str, str]:
    return name.lower().startswith("war3mapimported\\"), len(name), name.lower(), name


def _recovered_destination(
    archive: RecoveryArchive,
    root: str,
    name: str,
    entry: HashEntry,
    data: bytes,
) -> str | None:
    destination = safe_destination(root, name)
    if destination is None:
        return None
    if archive.block_index_of(name) == entry.block_index and not os.path.lexists(
        native_output_path(destination)
    ):
        return name
    variant = (
        f"RecoveredNames/blocks/block_{entry.block_index:06d}"
        f"-locale_{entry.locale:04x}-platform_{entry.platform:02x}.{guess_extension(data)}"
    )
    return _unused_destination(root, variant)


def _unused_destination(root: str, name: str) -> str | None:
    """Keep existing files, including map members in the report namespace."""
    relative = safe_relative_path(name)
    if relative is None:
        return None
    attempt = 1
    while True:
        candidate = (
            str(relative)
            if attempt == 1
            else str(relative.with_name(f"{relative.stem}-{attempt}{relative.suffix}"))
        )
        destination = safe_destination(root, candidate)
        if destination is None:
            return None
        if not os.path.lexists(native_output_path(destination)):
            return candidate
        attempt += 1


def _resource_name_variants(name: str) -> set[str]:
    exact = name
    name = name.strip().strip("\"'")
    if not name:
        return set()
    relative = safe_relative_path(name)
    if relative is None:
        return set()
    normalized = "\\".join(relative.parts)
    # Slash and backslash spellings have different MPQ hashes. Filesystem-safe
    # normalization supplies another candidate; it must never replace the exact
    # source spelling, including model-to-MDX and portrait-derived candidates.
    names = {name, normalized}
    if safe_relative_path(exact) is not None:
        names.add(exact)
    for candidate in tuple(names):
        lower = candidate.lower()
        if lower in ("war3map.j", "war3map.lua"):
            names.add("scripts\\" + candidate)
        if lower.endswith(".mdl"):
            names.add(candidate[:-4] + ".mdx")
        if lower.endswith((".mdl", ".mdx")) and not lower[:-4].endswith("_portrait"):
            names.add(candidate[:-4] + "_Portrait.mdx")
    for candidate in tuple(names):
        if not candidate.lower().startswith("war3mapimported\\"):
            names.add("war3mapImported\\" + candidate)
    return names


def _resource_name_candidates(
    data: bytes, *, legacy_codecs: tuple[str, ...] | None = None
) -> set[str]:
    names: set[str] = set()
    for match in _RESOURCE_NAME_RE.finditer(data):
        raw = match.group(1)
        for decoded in _decoded_name_hints(raw, legacy_codecs):
            # Script string literals escape a path separator as two backslashes.
            # A leading pair remains an unsafe UNC name and is never stripped.
            names.update(_resource_name_variants(decoded))
            if not decoded.startswith("\\\\"):
                names.update(_resource_name_variants(decoded.replace("\\\\", "\\")))
    if data.startswith(b"MDLX"):
        offset = 4
        while offset + 8 <= len(data):
            chunk, length = struct.unpack_from("<4sI", data, offset)
            start = offset + 8
            if length > len(data) - start:
                break
            if chunk == b"MODL" and length >= 80:
                raw = data[start : start + 80].split(b"\0", 1)[0]
                for model in _decoded_name_hints(raw, legacy_codecs):
                    if not model.lower().endswith((".mdl", ".mdx")):
                        model += ".mdx"
                    names.update(_resource_name_variants(model))
            offset = start + length
    return names


def _decoded_name_hints(raw: bytes, legacy_codecs: tuple[str, ...] | None) -> set[str]:
    """Keep strict decoding alternatives until the archive proves a byte name."""
    names: set[str] = set()
    codecs = default_legacy_codecs() if legacy_codecs is None else legacy_codecs
    for codec in ("utf-8", *codecs):
        try:
            name = raw.decode(codec)
            if name.encode(codec) == raw:
                names.add(name)
        except LookupError, UnicodeError:
            continue
    return names

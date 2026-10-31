"""Minimal local CASC data source for unencrypted BLTE payloads."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from dataclasses import dataclass
import hashlib
import os
from typing import final, override
import zlib

from .game_data_inventory import (
    GameDataEntry,
    GameDataInventoryView,
    inventory_name_matches,
    known_path_entry,
)

_PATH_MAP_NAMES = (
    "gamexray-casc-paths.tsv",
    ".gamexray-casc-paths.tsv",
    "Data/gamexray-casc-paths.tsv",
)


@dataclass(frozen=True, slots=True)
class CascIndexEntry:
    archive_index: int
    offset: int
    size: int


@dataclass(frozen=True, slots=True)
class CascUnsupportedError(Exception):
    feature: str

    @override
    def __str__(self) -> str:
        return f"unsupported CASC feature: {self.feature}"


@final
class CascDataSource:
    """Read files from a local CASC install when a path-to-encoding-key map exists."""

    inventory_view = GameDataInventoryView.KNOWN_PATHS

    def __init__(self, root: str):
        self.root = root
        self.data_dir = os.path.join(root, "Data", "data")
        self._path_to_key, self._display_names = _read_path_map(root)
        if not self._path_to_key:
            raise FileNotFoundError("missing gamexray-casc-paths.tsv")
        self._index = _read_indexes(self.data_dir)
        if not self._index:
            raise FileNotFoundError("missing readable CASC .idx entries")

    def has_file(self, name: str) -> bool:
        key = _encoding_key_for(self._path_to_key, name)
        return key is not None and key[:9] in self._index

    def read_file(self, name: str) -> bytes:
        key = _encoding_key_for(self._path_to_key, name)
        if key is None:
            raise FileNotFoundError(name)
        entry = self._index.get(key[:9])
        if entry is None:
            raise FileNotFoundError(name)
        return _read_data_block(self.data_dir, entry)

    def has_exact_file(self, name: str) -> bool:
        key = self._path_to_key.get(_norm(name))
        return key is not None and key[:9] in self._index

    def read_exact_file(self, name: str) -> bytes:
        key = self._path_to_key.get(_norm(name))
        if key is None:
            raise FileNotFoundError(name)
        entry = self._index.get(key[:9])
        if entry is None:
            raise FileNotFoundError(name)
        return _read_data_block(self.data_dir, entry)

    def iter_entries(
        self,
        mask: str = "*",
        listfile: str | None = None,
    ) -> Generator[GameDataEntry, None, None]:
        """Yield path-map names without inventing native Root identities."""
        _ = listfile
        for key, name in sorted(self._display_names.items(), key=lambda item: item[0]):
            if not inventory_name_matches(name, mask):
                continue
            encoding_key = self._path_to_key[key]
            yield known_path_entry(
                name,
                size=None,
                is_local=encoding_key[:9] in self._index,
            )

    def close(self) -> None:
        """Release no resources because CASC files are opened per read."""


def has_casc_path_map(root: str) -> bool:
    """Return whether the CASC directory has a path-to-encoding-key map."""
    return any(os.path.isfile(os.path.join(root, name)) for name in _PATH_MAP_NAMES)


def decode_blte(data: bytes) -> bytes:
    """Decode unencrypted BLTE chunks."""
    if data[:4] != b"BLTE" or len(data) < 9:
        raise CascUnsupportedError("missing BLTE header")
    header_size = int.from_bytes(data[4:8], "big")
    if header_size == 0:
        return _decode_chunk(data[8:])
    if len(data) < header_size:
        raise CascUnsupportedError("truncated BLTE header")
    count, table_pos = _chunk_count(data)
    if not count or header_size != table_pos + count * 24:
        raise CascUnsupportedError("BLTE chunk count does not match complete header")
    chunks: list[bytes] = []
    payload_pos = header_size
    for index in range(count):
        entry_pos = table_pos + index * 24
        comp_size = int.from_bytes(data[entry_pos : entry_pos + 4], "big")
        decoded_size = int.from_bytes(data[entry_pos + 4 : entry_pos + 8], "big")
        chunk = data[payload_pos : payload_pos + comp_size]
        if not comp_size or len(chunk) != comp_size:
            raise CascUnsupportedError("truncated BLTE chunk")
        expected_hash = data[entry_pos + 8 : entry_pos + 24]
        if any(expected_hash) and hashlib.md5(chunk).digest() != expected_hash:
            raise CascUnsupportedError("BLTE chunk checksum mismatch")
        decoded = _decode_chunk(chunk, expected_size=decoded_size)
        if len(decoded) != decoded_size:
            raise CascUnsupportedError("BLTE decoded chunk size mismatch")
        chunks.append(decoded)
        payload_pos += comp_size
    if payload_pos != len(data):
        raise CascUnsupportedError("unaccounted bytes after BLTE chunks")
    return b"".join(chunks)


def _read_path_map(root: str) -> tuple[dict[str, bytes], dict[str, str]]:
    for name in _PATH_MAP_NAMES:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        result: dict[str, bytes] = {}
        display_names: dict[str, str] = {}
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                cleaned = line.strip()
                if not cleaned or cleaned.startswith("#"):
                    continue
                parts = cleaned.rsplit(None, 1)
                if len(parts) == 2:
                    display = parts[0].replace("/", "\\").lstrip("\\")
                    key = _norm(display)
                    result[key] = bytes.fromhex(parts[1])
                    _ = display_names.setdefault(key, display)
        return result, display_names
    return {}, {}


def _encoding_key_for(paths: Mapping[str, bytes], name: str) -> bytes | None:
    query = _norm(name)
    direct = paths.get(query)
    if direct is not None:
        return direct
    suffixes = tuple(path for path in paths if path.endswith("/" + query))
    if not suffixes:
        return None
    selected = min(suffixes, key=lambda path: (len(path), path))
    return paths[selected]


def _read_indexes(data_dir: str) -> dict[bytes, CascIndexEntry]:
    result: dict[bytes, CascIndexEntry] = {}
    for filename in sorted(os.listdir(data_dir)):
        if not filename.lower().endswith(".idx"):
            continue
        with open(os.path.join(data_dir, filename), "rb") as handle:
            data = handle.read()
        for key, entry in _parse_idx_entries(data).items():
            result[key] = entry
    return result


def _parse_idx_entries(data: bytes) -> dict[bytes, CascIndexEntry]:
    result: dict[bytes, CascIndexEntry] = {}
    start = _idx_rows_start(data)
    for pos in range(start, len(data) - 17, 18):
        row = data[pos : pos + 18]
        key = row[:9]
        if key == b"\0" * 9:
            continue
        high = row[9]
        low = int.from_bytes(row[10:14], "big")
        archive_index = (high << 2) | (low >> 30)
        offset = low & 0x3FFFFFFF
        size = int.from_bytes(row[14:18], "little")
        result[key] = CascIndexEntry(archive_index, offset, size)
    return result


def _idx_rows_start(data: bytes) -> int:
    if len(data) % 18 == 0:
        return 0
    if len(data) >= 16:
        candidate = (8 + int.from_bytes(data[4:8], "little") + 15) & ~15
        if candidate < len(data) and (len(data) - candidate) % 18 == 0:
            return candidate
    return 0


def _read_data_block(data_dir: str, entry: CascIndexEntry) -> bytes:
    path = os.path.join(data_dir, f"data.{entry.archive_index:03d}")
    with open(path, "rb") as handle:
        _ = handle.seek(entry.offset)
        raw = handle.read(entry.size + 30)
    if raw[:4] == b"BLTE":
        if len(raw) < entry.size:
            raise CascUnsupportedError("truncated data block")
        return decode_blte(raw[: entry.size])
    if len(raw) < 30:
        raise CascUnsupportedError("truncated data block")
    size = int.from_bytes(raw[16:20], "little")
    if size < 30 or size > len(raw):
        raise CascUnsupportedError("truncated or invalid data block size")
    payload = raw[30:size]
    return decode_blte(payload)


def _chunk_count(data: bytes) -> tuple[int, int]:
    if len(data) < 12:
        raise CascUnsupportedError("truncated BLTE chunk table")
    if data[8] != 0x0F:
        raise CascUnsupportedError("invalid BLTE chunk table marker")
    return int.from_bytes(data[9:12], "big"), 12


def _decode_chunk(chunk: bytes, *, expected_size: int | None = None) -> bytes:
    if not chunk:
        raise CascUnsupportedError("missing BLTE chunk mode")
    mode = chunk[:1]
    payload = chunk[1:]
    if mode == b"N":
        return payload
    if mode == b"Z":
        for window in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                decoder = zlib.decompressobj(window)
                decoded = decoder.decompress(
                    payload, 0 if expected_size is None else expected_size + 1
                )
            except zlib.error:
                continue
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise CascUnsupportedError(
                    "incomplete or trailing BLTE compressed data"
                )
            return decoded
        raise CascUnsupportedError("invalid BLTE compressed data")
    if mode == b"E":
        raise CascUnsupportedError("encrypted BLTE chunk")
    raise CascUnsupportedError(f"BLTE mode {mode!r}")


def _norm(name: str) -> str:
    return name.replace("\\", "/").lstrip("/").lower()

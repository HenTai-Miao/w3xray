"""Warcraft III MPQ archive lookup and compatibility facade."""
from __future__ import annotations

import struct

from .explode import explode as explode
from .mpq_block_reader import (
    DERIVE_KEY as _DERIVE_KEY,
    decompress_mpq_block,
    decompress_unencrypted_block,
    parse_sector_offsets as _parse_sector_offsets,  # noqa: F401 - compatibility export
    peek_mpq_block,
    read_mpq_block,
    read_mpq_block_anonymous,
    recover_mpq_block_key,
)
from .mpq_compression import (
    COMP_LZMA as COMP_LZMA,
    MPQ_COMPRESSION_LZMA as MPQ_COMPRESSION_LZMA,
    decompress_mpq_sector,
    sparse_decompress,
)
from .mpq_constants import (
    COMP_ADPCM_MONO as COMP_ADPCM_MONO,
    COMP_ADPCM_STEREO as COMP_ADPCM_STEREO,
    COMP_BZIP2 as COMP_BZIP2,
    COMP_HUFFMAN as COMP_HUFFMAN,
    COMP_PKWARE as COMP_PKWARE,
    COMP_SPARSE as COMP_SPARSE,
    COMP_ZLIB as COMP_ZLIB,
    FLAG_COMPRESS as FLAG_COMPRESS,
    FLAG_ENCRYPTED as FLAG_ENCRYPTED,
    FLAG_EXISTS as FLAG_EXISTS,
    FLAG_FIX_KEY as FLAG_FIX_KEY,
    FLAG_IMPLODE as FLAG_IMPLODE,
    FLAG_SECTOR_CRC as FLAG_SECTOR_CRC,
    FLAG_SINGLE_UNIT as FLAG_SINGLE_UNIT,
    HASH_FILE_KEY as HASH_FILE_KEY,
    HASH_NAME_A as HASH_NAME_A,
    HASH_NAME_B as HASH_NAME_B,
    HASH_TABLE_OFFSET as HASH_TABLE_OFFSET,
)
from .mpq_crypto import (
    CRYPT_TABLE as _CRYPT,  # noqa: F401 - compatibility export
    _decrypt as _decrypt,
    _detect_offtable_key as _detect_offtable_key,
    _hash as _hash,
    hash_name_bytes,
)
from .huffman import huff_decompress as huff_decompress
from .mpq_file_types import guess_extension as guess_extension
from .mpq_files import STATIC_MAP_FILES as STATIC_MAP_FILES, list_archive_files
from .mpq_layout import (
    MPQLayout as MPQLayout,
    _Block as _Block,
    locate_mpq_layout as locate_mpq_layout,
    read_mpq_tables,
)
from .mpq_names import HashEntry, encoded_name_candidates, select_hash_entry
from .mpq_storage import MPQBackingStore, open_mpq_backing

_decompress_sector = decompress_mpq_sector
_sparse_decompress = sparse_decompress


class MPQArchive:
    def __init__(
        self,
        path: str,
        *,
        locale_id: int = 0,
        legacy_codecs: tuple[str, ...] | None = None,
    ):
        self.path = path
        self.locale_id = locale_id & 0xFFFF
        self.platform = (locale_id >> 16) & 0xFF
        self.legacy_codecs = legacy_codecs
        encoded_name_candidates("", legacy_codecs=legacy_codecs)
        self._backing: MPQBackingStore = open_mpq_backing(path)
        self._sync_backing()
        initialized = False
        try:
            self._parse_header()
            self._read_tables()
            self._names = None
            initialized = True
        finally:
            if not initialized:
                self.close()

    # ---- 资源释放：关闭文件句柄/mmap、删除大图独占时的临时副本 ----
    def close(self) -> None:
        """Release the owned backing store; repeated calls are harmless."""
        self._backing.close()
        self._sync_backing()

    def _sync_backing(self) -> None:
        self._data = self._backing.data
        self._file = self._backing.handle
        self._tmp = self._backing.temporary_path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- 头与表 ----
    def _parse_header(self):
        layout = locate_mpq_layout(self._data)
        self.archive_offset = layout.archive_offset
        self.header_size = layout.header_size
        self.archive_size = struct.unpack_from("<I", self._data, layout.archive_offset + 8)[0]
        self.format_version = layout.format_version
        self.sector_size_shift = layout.sector_shift
        self.sector_size = 512 << self.sector_size_shift
        self.hash_table_pos = layout.hash_table_offset
        self.block_table_pos = layout.block_table_offset
        self.hash_count = layout.hash_count
        self.block_count = layout.block_count
        self._layout = layout

    def _read_tables(self):
        self.hash_table, self.block_table = read_mpq_tables(self._data, self._layout)

    # ---- 查找 ----
    def _find_hash_entry(self, name: str):
        match = self._find_hash_match(name)
        return match[0] if match is not None else None

    def _find_hash_match(self, name: str):
        legacy_codecs = getattr(self, "legacy_codecs", None)
        locale_id = getattr(self, "locale_id", 0)
        platform = getattr(self, "platform", 0)
        for candidate in encoded_name_candidates(name, legacy_codecs):
            entries = self._matching_hash_entries(candidate)
            entry = select_hash_entry(
                entries, locale_id=locale_id, platform=platform
            )
            if entry is not None:
                return entry, candidate
        return None

    def _matching_hash_entries(self, name: bytes) -> tuple[HashEntry, ...]:
        index = hash_name_bytes(name, HASH_TABLE_OFFSET) & (self.hash_count - 1)
        name_a = hash_name_bytes(name, HASH_NAME_A)
        name_b = hash_name_bytes(name, HASH_NAME_B)
        matches: list[HashEntry] = []
        for count in range(self.hash_count):
            raw_entry = self.hash_table[(index + count) & (self.hash_count - 1)]
            entry = raw_entry if isinstance(raw_entry, HashEntry) else HashEntry(*raw_entry)
            if entry.block_index == 0xFFFFFFFF:
                break
            if (
                entry.name_a == name_a
                and entry.name_b == name_b
                and entry.block_index != 0xFFFFFFFE
            ):
                matches.append(entry)
        return tuple(matches)

    def _resolve_match(self, name: str):
        match = self._find_hash_match(name)
        if match is not None:
            return match[0], name, match[1]
        alternate = "scripts\\" + name
        match = self._find_hash_match(alternate)
        if match is not None:
            return match[0], alternate, match[1]
        return None, name, None

    def _resolve_entry(self, name: str):
        """先按原名找，找不到再试 scripts\\ 子目录（部分地图把文件放那里）。"""
        entry, real_name, _candidate = self._resolve_match(name)
        return entry, real_name

    def has_file(self, name: str) -> bool:
        return self._resolve_entry(name)[0] is not None

    # ---- 读取文件 ----
    def read_file(self, name: str) -> bytes:
        entry, real, candidate = self._resolve_match(name)
        if entry is None:
            raise KeyError(name)
        bi = entry.block_index
        if bi >= len(self.block_table):       # 块表被截断/索引越界
            raise KeyError(name)
        block = self.block_table[bi]
        return self._read_block(block, real, name_bytes=candidate)

    def declared_file_size(self, name: str) -> int | None:
        try:
            block_index = self.block_index_of(name)
        except AttributeError:
            return None
        if block_index is None:
            return None
        return self.block_table[block_index].file_size

    def _read_block(
        self,
        block: _Block,
        name: str,
        key: int | None = _DERIVE_KEY,
        *,
        name_bytes: bytes | None = None,
    ) -> bytes:
        encoded = name.encode("utf-8") if name_bytes is None else name_bytes
        try:
            return read_mpq_block(self, block, encoded, key)
        except KeyError:
            raise KeyError(name) from None

    def _decomp(self, buf: bytes, out_size: int, flags: int) -> bytes:
        return decompress_mpq_block(buf, out_size, flags)

    def decompress_block(self, block: _Block) -> bytes | None:
        return decompress_unencrypted_block(self, block)

    def recover_block_key(self, block: _Block) -> int | None:
        """无文件名时由扇区偏移表反推加密块密钥。"""
        return recover_mpq_block_key(self, block)

    def read_block_anon(self, block: _Block) -> bytes | None:
        """读取无名块，加密块先由内容反推密钥。"""
        return read_mpq_block_anonymous(self, block)

    def iter_blocks(self):
        """枚举块表里实际存在的 (索引, _Block)。"""
        for idx, block in enumerate(self.block_table):
            if block.flags & FLAG_EXISTS:
                yield idx, block

    def block_index_of(self, name: str):
        """文件名 → 块索引（用于把"已具名导出"的块从无名导出里排除）。"""
        entry, _ = self._resolve_entry(name)
        if entry is None:
            return None
        bi = entry[4]
        return bi if bi < len(self.block_table) else None

    def peek_block(self, block: _Block, n: int = 64) -> bytes:
        """只解压头部少量字节，用于快速判断文件类型（避免整块解压大文件）。"""
        return peek_mpq_block(self, block, n)

    # ---- 文件名列举 ----
    def list_files(self):
        """并集枚举 listfile、内置固定名单和导入清单。"""
        if self._names is not None:
            return self._names
        self._names = list_archive_files(self)
        return self._names

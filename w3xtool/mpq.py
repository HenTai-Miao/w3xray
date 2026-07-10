"""MPQ 压缩包读取（够用版，覆盖魔兽 III .w3x/.w3m/.w3n）。

支持：
- HM3W 头自动跳过、MPQ 头定位（512 对齐扫描）
- hash/block 表解密、按文件名查找
- 扇区式与单块(SINGLE_UNIT)文件读取
- 解压：zlib(0x02)、bzip2(0x10)、PKWARE explode(0x08)、稀疏(0x20)、以及 IMPLODE 标志
- 文件加密(ENCRYPTED/FIX_KEY)
- (listfile) 列举文件名
"""
from __future__ import annotations

import bz2
import struct
import zlib

from .explode import explode
from .huffman import huff_decompress
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
    CRYPT_TABLE as _CRYPT,
    _decrypt as _decrypt,
    _detect_offtable_key,
    _hash as _hash,
    hash_name_bytes,
)
from .mpq_files import STATIC_MAP_FILES as STATIC_MAP_FILES, list_archive_files
from .mpq_layout import MPQLayout as MPQLayout, _Block as _Block
from .mpq_layout import locate_mpq_layout as locate_mpq_layout
from .mpq_layout import read_mpq_tables
from .mpq_names import HashEntry, encoded_name_candidates, select_hash_entry

_DERIVE_KEY = -1                  # _read_block 的哨兵：区分"按名派生密钥"与"key=None(不加密)"


def _decompress_sector(data: bytes, out_size: int) -> bytes:
    """对单个压缩扇区解压（FLAG_COMPRESS：首字节是压缩掩码）。

    out_size 是该扇区声明的原始大小；合法地图正好解出这么多字节。
    各解压分支都以 out_size 为硬上限，防止恶意小扇区解出巨量数据（解压炸弹/OOM）。
    """
    if not data:
        return data
    # 合法扇区正好解出 out_size 字节，以此为硬上限
    limit = max(0, out_size)
    mask = data[0]
    payload = data[1:]
    # 可能是多种压缩叠加，按约定顺序处理（实际魔兽地图基本单一压缩）。
    # 损坏/被篡改的压缩流会让底层编解码器抛 zlib.error / OSError(bz2) 等五花八门
    # 的异常；统一收敛成 ValueError，使 read_file 的失败契约单一可预期（与 explode、
    # 不支持掩码两个分支一致），调用方只需 catch 一种。
    try:
        if mask & COMP_BZIP2:
            payload = bz2.BZ2Decompressor().decompress(payload, max_length=limit)
        elif mask & COMP_PKWARE:
            payload = explode(payload, max_output=limit)
        elif mask & COMP_ZLIB:
            payload = zlib.decompressobj().decompress(payload, limit)
        elif mask & COMP_SPARSE:
            payload = _sparse_decompress(payload, max_output=limit)
        elif mask & COMP_HUFFMAN:
            payload = huff_decompress(payload, limit)
        elif mask == 0:
            pass
        else:
            raise ValueError("不支持的压缩掩码 0x%02X" % mask)
    except ValueError:
        raise
    except Exception as e:               # zlib.error / OSError(bz2) / 编解码器内部异常
        raise ValueError("扇区解压失败(掩码 0x%02X): %s" % (mask, e)) from e
    return payload


def _sparse_decompress(data: bytes, max_output: int | None = None) -> bytes:
    """MPQ 稀疏(0x20)解压。max_output 为输出上限，达到即停（防解压炸弹）。"""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        if max_output is not None and len(out) >= max_output:
            break
        ctrl = data[i]
        i += 1
        if ctrl & 0x80:
            count = (ctrl & 0x7F) + 1
            out.extend(data[i:i + count])
            i += count
        else:
            count = (ctrl & 0x7F) + 3
            out.extend(b"\x00" * count)
    if max_output is not None:
        return bytes(out[:max_output])
    return bytes(out)


def guess_extension(data: bytes) -> str:
    """按文件头(magic)猜扩展名，用于给无名导入资源起个可识别的名字。"""
    if len(data) < 4:
        return "bin"
    h = data[:4]
    if h in (b"BLP1", b"BLP2"):
        return "blp"
    if h == b"MDLX":
        return "mdx"
    if h == b"DDS ":
        return "dds"
    if h == b"RIFF":
        return "wav"
    if h[:3] == b"ID3" or h[:2] == b"\xff\xfb":
        return "mp3"
    if h == b"OggS":
        return "ogg"
    if h in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return "ttf"
    if h[:3] == b"ID;":
        return "slk"
    if h == b"HM3W":
        return "w3m"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if h[:2] == b"\xff\xd8":
        return "jpg"
    if h[:2] == b"BM":
        return "bmp"
    sample = data[:512]
    try:
        sample.decode("ascii")
        s = sample.lstrip().lower()
        if s[:7] == b"version" or s[:2] == b"//" or s[:8] == b"function" or s[:6] == b"global":
            return "mdl"               # 文本模型/脚本
        return "txt"
    except UnicodeDecodeError:
        pass
    if len(data) > 18 and data[2] in (1, 2, 3, 9, 10, 11):
        return "tga"                   # TGA 无 magic，靠 image-type 字节判断
    return "bin"


def _parse_sector_offsets(raw: bytes, count: int, key) -> list:
    """从扇区数据头部解析并校验 count 个 uint32 扇区偏移。

    raw 为该 block 读入内存的(压缩)数据，偏移表在最前面 count*4 字节。
    key 不为 None 时先按该密钥解密偏移表。

    偏移必须单调不减、且全部落在 raw 之内——否则该文件已损坏/被篡改：
    旧实现直接对越界/逆序偏移做切片会得到空段并被静默接受，产出错误数据。
    这里改为抛出清晰 ValueError，杜绝静默错误结果。
    """
    need = count * 4
    off_raw = raw[:need]
    if len(off_raw) < need:
        raise ValueError("扇区偏移表损坏：偏移表被截断")
    if key is not None:
        off_raw = _decrypt(off_raw, key)
    offsets = list(struct.unpack("<%dI" % count, off_raw))
    raw_len = len(raw)
    for i in range(count - 1):
        if offsets[i] > offsets[i + 1] or offsets[i + 1] > raw_len:
            raise ValueError("扇区偏移表损坏：偏移非单调或越界")
    return offsets


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
        self._file = None
        self._tmp = None
        try:
            self._open(path)
        except (PermissionError, OSError):
            # 文件被独占(例如正在被游戏/平台占用) → 复制到临时目录再读
            import tempfile, shutil, os
            fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(path)[1] or ".w3x")
            os.close(fd)
            shutil.copyfile(path, tmp)   # 只读复制，源文件被独占也能复制
            self._tmp = tmp
            self._open(tmp)
        # 小图已整块读入内存，临时副本可立即删除
        if self._tmp and self._file is None:
            try:
                import os
                os.remove(self._tmp)
                self._tmp = None
            except OSError:
                pass
        self._parse_header()
        self._read_tables()
        self._names = None

    # ---- 资源释放：关闭文件句柄/mmap、删除大图独占时的临时副本 ----
    def close(self):
        """释放底层文件句柄与 mmap，并删除复制出来的临时副本。可重复调用。

        大图用 mmap 会一直持有文件句柄(Windows 上锁住源文件)；独占大图还会留下
        临时副本 self._tmp。不显式关闭就只能等 GC，期间句柄/磁盘不释放。
        """
        import mmap as _mmap
        data = getattr(self, "_data", None)
        if isinstance(data, _mmap.mmap):
            try:
                data.close()
            except (BufferError, OSError, ValueError):
                pass
        self._data = b""
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        if self._tmp:
            try:
                import os
                os.remove(self._tmp)
            except OSError:
                pass
            self._tmp = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _open(self, path: str):
        import os
        size = os.path.getsize(path)
        # 以"读 + 允许他人读写"方式打开，尽量不与运行中的游戏冲突
        self._file = open(path, "rb")
        if size > 40 * 1024 * 1024:
            import mmap
            self._data = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        else:
            self._data = self._file.read()
            self._file.close()
            self._file = None

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

    def _read_block(
        self,
        block: _Block,
        name: str,
        key=_DERIVE_KEY,
        *,
        name_bytes: bytes | None = None,
    ) -> bytes:
        data = self._data
        start = self.archive_offset + block.file_pos
        if start < 0 or start > len(data):
            # block 指向文件外（损坏/被剥离的保护图）——视为文件不存在，
            # 而非静默返回空字节。
            raise KeyError(name)
        raw = data[start:start + block.comp_size]
        flags = block.flags

        if key == _DERIVE_KEY:           # 默认：由文件名派生密钥（无名块则由调用方显式传入）
            key = None                   # None=不加密
            if flags & FLAG_ENCRYPTED:
                encoded_name = name.encode("utf-8") if name_bytes is None else name_bytes
                base = encoded_name.replace(b"/", b"\\").rsplit(b"\\", 1)[-1]
                key = hash_name_bytes(base, HASH_FILE_KEY)
                if flags & FLAG_FIX_KEY:
                    key = (key + block.file_pos) ^ block.file_size
                    key &= 0xFFFFFFFF

        compressed = bool(flags & (FLAG_COMPRESS | FLAG_IMPLODE))

        if flags & FLAG_SINGLE_UNIT:
            buf = raw
            if key is not None:
                buf = _decrypt(buf, key)
            if compressed and block.comp_size < block.file_size:
                buf = self._decomp(buf, block.file_size, flags)
            return buf[:block.file_size]

        # 未压缩多扇区文件：没有扇区偏移表，数据连续
        if not compressed:
            if key is None:
                return raw[:block.file_size]
            out = bytearray()
            ss = self.sector_size
            nsec = (block.file_size + ss - 1) // ss
            for i in range(nsec):
                seg = raw[i * ss:i * ss + min(ss, block.file_size - i * ss)]
                seg = _decrypt(seg, (key + i) & 0xFFFFFFFF)
                out.extend(seg)
            return bytes(out[:block.file_size])

        # 扇区式
        sector_size = self.sector_size
        num_sectors = (block.file_size + sector_size - 1) // sector_size
        # 扇区偏移表：num_sectors+1 个 uint32（含可能的 CRC 扇区）
        count = num_sectors + 1
        if flags & FLAG_SECTOR_CRC:
            count += 1
        off_key = (key - 1) & 0xFFFFFFFF if key is not None else None
        offsets = _parse_sector_offsets(raw, count, off_key)

        out = bytearray()
        for i in range(num_sectors):
            s_start = offsets[i]
            s_end = offsets[i + 1]
            sdata = raw[s_start:s_end]
            if key is not None:
                sdata = _decrypt(sdata, (key + i) & 0xFFFFFFFF)
            # 该扇区原始大小
            this_size = min(sector_size, block.file_size - i * sector_size)
            if compressed and len(sdata) < this_size:
                if flags & FLAG_IMPLODE and not (flags & FLAG_COMPRESS):
                    sdata = explode(sdata, max_output=this_size)
                else:
                    sdata = _decompress_sector(sdata, this_size)
            out.extend(sdata)
        return bytes(out[:block.file_size])

    def _decomp(self, buf: bytes, out_size: int, flags: int) -> bytes:
        if flags & FLAG_IMPLODE and not (flags & FLAG_COMPRESS):
            return explode(buf, max_output=out_size)
        return _decompress_sector(buf, out_size)

    # ---- 按块直接解压（无需文件名，跳过加密块）----
    def decompress_block(self, block: "_Block"):
        if block.flags & FLAG_ENCRYPTED:
            return None
        try:
            return self._read_block(block, "")
        except Exception:
            return None

    def recover_block_key(self, block: "_Block"):
        """无文件名时由内容反推加密块的解密密钥（仅扇区式压缩文件）。

        保护图把导入资源的名字从 (listfile) 删光，密钥又是文件名派生的——但扇区偏移表
        头两个 uint32 是已知明文，据此可反解出密钥（见 _detect_offtable_key）。
        返回文件密钥；单块(SINGLE_UNIT，无偏移表)或反推失败返回 None。
        """
        flags = block.flags
        if not (flags & FLAG_ENCRYPTED):
            return None
        if flags & FLAG_SINGLE_UNIT:
            return None                    # 无扇区偏移表，无已知明文可依
        if not (flags & (FLAG_COMPRESS | FLAG_IMPLODE)):
            return None                    # 未压缩多扇区：偏移表不存在，同样无依据
        start = self.archive_offset + block.file_pos
        raw = self._data[start:start + block.comp_size]
        if len(raw) < 8:
            return None
        e0, e1 = struct.unpack_from("<II", raw, 0)
        nsec = (block.file_size + self.sector_size - 1) // self.sector_size
        for crc in (0, 1):                 # 偏移表可能多一个 CRC 扇区项
            count = nsec + 1 + crc
            off0 = count * 4
            k = _detect_offtable_key(e0, e1, off0, len(raw))
            if k is None:
                continue
            try:
                _parse_sector_offsets(raw, count, k)
            except ValueError:
                continue
            return (k + 1) & 0xFFFFFFFF   # 偏移表用 key-1 解，故文件密钥 = k+1
        return None

    def read_block_anon(self, block: "_Block"):
        """读取一个块而不依赖文件名：加密块先由内容反推密钥。失败返回 None。

        用于"完整提取"——保护图里删了名、只存在于块表里的导入资源(模型/贴图/音效)。
        恢复出的密钥会被扇区偏移表单调性校验 + 解压成功 二次把关，错误密钥基本会被挡下。
        """
        flags = block.flags
        try:
            if flags & FLAG_ENCRYPTED:
                key = self.recover_block_key(block)
                if key is None:
                    return None
                return self._read_block(block, "", key=key)
            return self._read_block(block, "")
        except Exception:
            return None

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

    def peek_block(self, block: "_Block", n: int = 64):
        """只解压头部少量字节，用于快速判断文件类型（避免整块解压大文件）。"""
        if block.flags & FLAG_ENCRYPTED:
            return b""
        data = self._data
        start = self.archive_offset + block.file_pos
        raw = data[start:start + block.comp_size]
        flags = block.flags
        compressed = bool(flags & (FLAG_COMPRESS | FLAG_IMPLODE))
        try:
            if flags & FLAG_SINGLE_UNIT:
                buf = raw
                if compressed and block.comp_size < block.file_size:
                    buf = self._decomp(buf, block.file_size, flags)
                return buf[:n]
            # 扇区式：只解第 0 扇区
            ss = self.sector_size
            num_sectors = (block.file_size + ss - 1) // ss
            count = num_sectors + 1
            if flags & FLAG_SECTOR_CRC:
                count += 1
            offsets = _parse_sector_offsets(raw, count, None)
            sdata = raw[offsets[0]:offsets[1]]
            this_size = min(ss, block.file_size)
            if compressed and len(sdata) < this_size:
                if flags & FLAG_IMPLODE and not (flags & FLAG_COMPRESS):
                    sdata = explode(sdata, max_output=this_size)
                else:
                    sdata = _decompress_sector(sdata, this_size)
            return sdata[:n]
        except Exception:
            return b""

    # ---- 文件名列举 ----
    def list_files(self):
        """三层并集枚举：(listfile) + 内置固定名单 + war3map.imp 导入清单。

        保护图常删/伪造 (listfile)，单靠它会漏掉固定名地图文件与导入资源。
        固定名/导入名只在 has_file 验证存在时才收，按小写去重。(借鉴 w3x2lni
        三层 searcher，见 core/map-builder/load.lua)。"""
        if self._names is not None:
            return self._names
        self._names = list_archive_files(self)
        return self._names

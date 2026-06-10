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
from dataclasses import dataclass

from .explode import explode
from .huffman import huff_decompress

# ---- 文件标志 ----
FLAG_IMPLODE = 0x00000100      # 整文件 PKWARE 压缩（无掩码字节）
FLAG_COMPRESS = 0x00000200     # 多压缩（每扇区首字节为压缩掩码）
FLAG_ENCRYPTED = 0x00010000
FLAG_FIX_KEY = 0x00020000
FLAG_SINGLE_UNIT = 0x01000000
FLAG_SECTOR_CRC = 0x04000000
FLAG_EXISTS = 0x80000000

# ---- 压缩掩码位（用于 FLAG_COMPRESS）----
COMP_HUFFMAN = 0x01
COMP_ZLIB = 0x02
COMP_PKWARE = 0x08
COMP_BZIP2 = 0x10
COMP_SPARSE = 0x20
COMP_ADPCM_MONO = 0x40
COMP_ADPCM_STEREO = 0x80


def _make_crypt_table():
    table = [0] * 0x500
    seed = 0x00100001
    for index1 in range(0x100):
        index2 = index1
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp1 = (seed & 0xFFFF) << 0x10
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp2 = seed & 0xFFFF
            table[index2] = (temp1 | temp2) & 0xFFFFFFFF
            index2 += 0x100
    return table


_CRYPT = _make_crypt_table()

# hash 类型
HASH_TABLE_OFFSET = 0
HASH_NAME_A = 1
HASH_NAME_B = 2
HASH_FILE_KEY = 3


def _hash(name: str, hash_type: int) -> int:
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE
    for ch in name.upper():
        c = ord(ch)
        value = _CRYPT[(hash_type << 8) + (c & 0xFF)]
        seed1 = (value ^ ((seed1 + seed2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        seed2 = (c + seed1 + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
    return seed1


def _decrypt(data: bytes, key: int) -> bytes:
    n = len(data) // 4
    if n == 0:
        return data
    vals = list(struct.unpack("<%dI" % n, data[: n * 4]))
    seed1 = key & 0xFFFFFFFF
    seed2 = 0xEEEEEEEE
    for i in range(n):
        seed2 = (seed2 + _CRYPT[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
        value = (vals[i] ^ ((seed1 + seed2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        vals[i] = value
        seed1 = (((~seed1 & 0xFFFFFFFF) << 0x15) + 0x11111111 | (seed1 >> 0x0B)) & 0xFFFFFFFF
        seed2 = (value + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
    out = struct.pack("<%dI" % n, *vals)
    return out + data[n * 4:]


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
    # 可能是多种压缩叠加，按约定顺序处理（实际魔兽地图基本单一压缩）
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


@dataclass
class _Block:
    file_pos: int
    comp_size: int
    file_size: int
    flags: int


class MPQArchive:
    def __init__(self, path: str):
        self.path = path
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
        data = self._data
        # 在 512 对齐位置扫描 MPQ\x1a。某些打包/混淆工具(_w3p 等)会在真头前面
        # 放一个垃圾"诱饵"头来骗解析器，故不取第一个，而是取第一个**校验通过**的头。
        last_err = None
        pos = 0
        while pos + 32 <= len(data):
            if data[pos:pos + 4] == b"MPQ\x1a":
                try:
                    self._read_header_fields(pos)
                    self._validate_header()
                    return
                except (ValueError, struct.error) as e:
                    last_err = e          # 诱饵/垃圾头，继续找下一个
            pos += 512
        if last_err is not None:
            raise last_err
        raise ValueError("没找到 MPQ 头（不是有效的 .w3x/.w3n？）")

    def _read_header_fields(self, offset: int):
        data = self._data
        self.archive_offset = offset
        hdr = data[offset:offset + 32]
        (magic, self.header_size, self.archive_size, self.format_version,
         self.sector_size_shift, hash_pos, block_pos,
         self.hash_count, self.block_count) = struct.unpack("<4sIIHHIIII", hdr)
        self.sector_size = 512 << self.sector_size_shift
        self.hash_table_pos = offset + hash_pos
        self.block_table_pos = offset + block_pos

    def _validate_header(self):
        """拒绝非法/恶意的表大小，防止 range(hash_count) 跑数十亿次卡死(DoS)。

        合法 MPQ：hash 表大小是 2 的幂；hash/block 表都能放进文件内。
        """
        n = len(self._data)
        if self.hash_count <= 0 or (self.hash_count & (self.hash_count - 1)) != 0:
            raise ValueError("MPQ hash 表大小非法（应为 2 的幂）：%d" % self.hash_count)
        if self.block_count < 0:
            raise ValueError("MPQ block 表大小非法：%d" % self.block_count)
        if self.hash_table_pos < 0 or self.hash_table_pos + self.hash_count * 16 > n:
            raise ValueError("MPQ hash 表越界（文件损坏或非标准）")
        if self.block_table_pos < 0 or self.block_table_pos + self.block_count * 16 > n:
            raise ValueError("MPQ block 表越界（文件损坏或非标准）")

    def _read_tables(self):
        data = self._data
        # hash 表（容忍被保护/截断的表：只解析实际可用条目，其余补空）
        raw = data[self.hash_table_pos:self.hash_table_pos + self.hash_count * 16]
        raw = _decrypt(raw, _hash("(hash table)", HASH_FILE_KEY))
        avail = len(raw) // 16
        self.hash_table = []
        for i in range(self.hash_count):
            if i < avail:
                name1, name2, locale, platform, block_index = struct.unpack(
                    "<IIHHI", raw[i * 16:i * 16 + 16])
            else:
                name1 = name2 = 0
                locale = platform = 0
                block_index = 0xFFFFFFFF        # 空条目(查找时遇到即停)
            self.hash_table.append((name1, name2, locale, platform, block_index))
        # block 表（同样容忍截断）
        raw = data[self.block_table_pos:self.block_table_pos + self.block_count * 16]
        raw = _decrypt(raw, _hash("(block table)", HASH_FILE_KEY))
        avail = len(raw) // 16
        self.block_table = []
        for i in range(avail):
            fp, cs, fs, fl = struct.unpack("<IIII", raw[i * 16:i * 16 + 16])
            self.block_table.append(_Block(fp, cs, fs, fl))

    # ---- 查找 ----
    def _find_hash_entry(self, name: str):
        index = _hash(name, HASH_TABLE_OFFSET) & (self.hash_count - 1)
        name_a = _hash(name, HASH_NAME_A)
        name_b = _hash(name, HASH_NAME_B)
        count = 0
        i = index
        while count < self.hash_count:
            entry = self.hash_table[i]
            if entry[4] == 0xFFFFFFFF:  # 空块，结束
                return None
            if entry[0] == name_a and entry[1] == name_b and entry[4] != 0xFFFFFFFE:
                return entry
            i = (i + 1) & (self.hash_count - 1)
            count += 1
        return None

    def _resolve_entry(self, name: str):
        """先按原名找，找不到再试 scripts\\ 子目录（部分地图把文件放那里）。"""
        e = self._find_hash_entry(name)
        if e is not None:
            return e, name
        alt = "scripts\\" + name
        e = self._find_hash_entry(alt)
        if e is not None:
            return e, alt
        return None, name

    def has_file(self, name: str) -> bool:
        return self._resolve_entry(name)[0] is not None

    # ---- 读取文件 ----
    def read_file(self, name: str) -> bytes:
        entry, real = self._resolve_entry(name)
        if entry is None:
            raise KeyError(name)
        bi = entry[4]
        if bi >= len(self.block_table):       # 块表被截断/索引越界
            raise KeyError(name)
        block = self.block_table[bi]
        return self._read_block(block, real)

    def _read_block(self, block: _Block, name: str) -> bytes:
        data = self._data
        start = self.archive_offset + block.file_pos
        raw = data[start:start + block.comp_size]
        flags = block.flags

        key = None
        if flags & FLAG_ENCRYPTED:
            base = name.split("\\")[-1].split("/")[-1]
            key = _hash(base, HASH_FILE_KEY)
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
        off_raw = raw[:count * 4]
        if key is not None:
            off_raw = _decrypt(off_raw, (key - 1) & 0xFFFFFFFF)
        offsets = list(struct.unpack("<%dI" % count, off_raw))

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
                    sdata = explode(sdata)
                else:
                    sdata = _decompress_sector(sdata, this_size)
            out.extend(sdata)
        return bytes(out[:block.file_size])

    def _decomp(self, buf: bytes, out_size: int, flags: int) -> bytes:
        if flags & FLAG_IMPLODE and not (flags & FLAG_COMPRESS):
            return explode(buf)
        return _decompress_sector(buf, out_size)

    # ---- 按块直接解压（无需文件名，跳过加密块）----
    def decompress_block(self, block: "_Block"):
        if block.flags & FLAG_ENCRYPTED:
            return None
        try:
            return self._read_block(block, "")
        except Exception:
            return None

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
            offsets = list(struct.unpack_from("<%dI" % count, raw, 0))
            sdata = raw[offsets[0]:offsets[1]]
            this_size = min(ss, block.file_size)
            if compressed and len(sdata) < this_size:
                if flags & FLAG_IMPLODE and not (flags & FLAG_COMPRESS):
                    sdata = explode(sdata)
                else:
                    sdata = _decompress_sector(sdata, this_size)
            return sdata[:n]
        except Exception:
            return b""

    # ---- 文件名列举 ----
    def list_files(self):
        if self._names is not None:
            return self._names
        names = []
        if self.has_file("(listfile)"):
            try:
                raw = self.read_file("(listfile)").decode("utf-8", "replace")
                for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                    line = line.strip()
                    if line:
                        names.append(line)
            except Exception:
                pass
        self._names = names
        return names

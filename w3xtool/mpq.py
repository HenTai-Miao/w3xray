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

# ---- 魔兽地图/战役固定内部文件名（listfile 被删时据此枚举）----
# 借鉴 w3x2lni core/info.lua 的 impignore 清单；只有 has_file 验证存在的才会被收。
STATIC_MAP_FILES = [
    # 脚本 / 字符串
    "war3map.j", "war3map.lua", "war3map.wts",
    # 对象数据
    "war3map.w3u", "war3map.w3t", "war3map.w3a", "war3map.w3q",
    "war3map.w3b", "war3map.w3d", "war3map.w3h",
    # 触发器
    "war3map.wtg", "war3map.wct",
    # 地图信息 / 地形 / 预览
    "war3map.w3i", "war3map.w3e", "war3map.w3r", "war3map.w3c",
    "war3map.w3s", "war3map.shd", "war3map.wpm", "war3map.mmp",
    "war3map.imp", "war3mapMap.blp", "war3mapMap.tga", "war3mapPath.tga",
    "war3mapPreview.tga", "war3mapPreview.blp",
    "war3mapUnits.doo", "war3map.doo",
    # 文本档
    "war3mapExtra.txt", "war3mapMisc.txt", "war3mapSkin.txt", "war3map.txt.ini",
    # MPQ 内部表
    "(listfile)", "(attributes)", "(signature)",
    # 战役级
    "war3campaign.w3f", "war3campaign.imp", "war3campaign.wts",
    "war3campaign.w3u", "war3campaign.w3t", "war3campaign.w3a",
    "war3campaign.w3q", "war3campaign.w3b", "war3campaign.w3d", "war3campaign.w3h",
]


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

_DERIVE_KEY = -1                  # _read_block 的哨兵：区分"按名派生密钥"与"key=None(不加密)"

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


def _detect_offtable_key(e0: int, e1: int, off0: int, max_off1: int):
    """由内容反推扇区偏移表的解密密钥（无需文件名）。

    加密文件的密钥本由「文件名」派生；保护图删名后无法这样取。但扇区偏移表头两个
    uint32 是已知明文：第 0 个 = 偏移表自身字节数(off0)，第 1 个 = 第 0 扇区数据的结束
    偏移(在 (off0, off0+扇区大小] 内)。据此在 256 个候选里解出能让密文解成已知明文的密钥。
    这正是 MPQ Editor「查找未知文件」用的办法（StormLib DetectFileKeyBySectorSize）。

    返回的是「解密偏移表用的密钥」（= 文件密钥 - 1）；命中不到返回 None。
    """
    temp = ((e0 ^ off0) - 0xEEEEEEEE) & 0xFFFFFFFF
    for i in range(0x100):
        key1 = (temp - _CRYPT[0x400 + i]) & 0xFFFFFFFF
        key2 = (0xEEEEEEEE + _CRYPT[0x400 + (key1 & 0xFF)]) & 0xFFFFFFFF
        if (e0 ^ ((key1 + key2) & 0xFFFFFFFF)) == off0:
            k1 = (((~key1 & 0xFFFFFFFF) << 0x15) + 0x11111111 | (key1 >> 0x0B)) & 0xFFFFFFFF
            k2 = (off0 + key2 + (key2 << 5) + 3) & 0xFFFFFFFF
            k2 = (k2 + _CRYPT[0x400 + (k1 & 0xFF)]) & 0xFFFFFFFF
            if off0 < (e1 ^ ((k1 + k2) & 0xFFFFFFFF)) <= max_off1:
                return key1
    return None


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

        合法 MPQ：hash 表大小是 2 的幂、且整张表在文件内（这也把 hash_count 卡死在
        文件大小/16 以内，挡住 DoS）。block 表则容忍"尾部越界"——保护图常把 block_count
        注水、声明长度超过文件尾；StormLib 只读实际存在的条目即可加载，故这里只要求
        block 表起点在文件内，越界的尾部交给 _read_tables 自然截断（avail = 实际字节//16）。
        """
        n = len(self._data)
        # 扇区位移上限：真实地图恒为 3(4KB 扇区)左右。位移过大会让 512<<shift 溢出成
        # 天文数字、行为怪异；过大值也是诱饵头特征，一并拒绝。
        if self.sector_size_shift > 20:
            raise ValueError("MPQ 扇区大小非法：shift=%d" % self.sector_size_shift)
        if self.hash_count <= 0 or (self.hash_count & (self.hash_count - 1)) != 0:
            raise ValueError("MPQ hash 表大小非法（应为 2 的幂）：%d" % self.hash_count)
        if self.block_count < 0:
            raise ValueError("MPQ block 表大小非法：%d" % self.block_count)
        if self.hash_table_pos < 0 or self.hash_table_pos + self.hash_count * 16 > n:
            raise ValueError("MPQ hash 表越界（文件损坏或非标准）")
        if self.block_table_pos < 0 or self.block_table_pos > n:
            raise ValueError("MPQ block 表起点越界（文件损坏或非标准）")

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

    def _read_block(self, block: _Block, name: str, key=_DERIVE_KEY) -> bytes:
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
        names = []
        seen = set()

        def add(n, verify):
            if not n:
                return
            ln = n.lower()
            if ln in seen:
                return
            if verify and not self.has_file(n):
                return
            seen.add(ln)
            names.append(n)

        # 1) (listfile)：原样收（部分名可能并不真实存在，导出侧会再校验）
        if self.has_file("(listfile)"):
            try:
                raw = self.read_file("(listfile)").decode("utf-8", "replace")
                for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                    add(line.strip(), verify=False)
            except Exception:
                pass
        # 2) 内置固定名单：仅收实际存在的（补全被删 listfile 的图）
        for n in STATIC_MAP_FILES:
            add(n, verify=True)
        # 3) war3map.imp 导入清单：相对名直查不到时补 war3mapImported\ 前缀
        if self.has_file("war3map.imp"):
            try:
                from .imp import parse_imp
                for n in parse_imp(self.read_file("war3map.imp")):
                    if self.has_file(n):
                        add(n, verify=False)
                    else:
                        add("war3mapImported\\" + n, verify=True)
            except Exception:
                pass

        self._names = names
        return names

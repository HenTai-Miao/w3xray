"""PKWARE DCL (Data Compression Library) "explode" 解压。

MPQ 里压缩类型 0x08 用的就是 PKWARE DCL implode，Python 标准库没有，
这里移植自 zlib contrib 的 blast.c（Mark Adler，zlib 许可，公有逻辑）。
"""
from __future__ import annotations

MAXBITS = 13

# 长度码的基值与额外位（base[0]=3 ... base[15]=264，额外位最大 8 → 最大长度 519=结束标记）
_BASE = (3, 2, 4, 5, 6, 7, 8, 9, 10, 12, 16, 24, 40, 72, 136, 264)
_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8)

# 三张 Huffman 码表（紧凑游程表示：每字节 高4位+1=重复次数, 低4位=码长）
_LITLEN = bytes((
    11, 124, 8, 7, 28, 7, 188, 13, 76, 4, 10, 8, 12, 10, 12, 10, 8, 23, 8,
    9, 7, 6, 7, 8, 7, 6, 55, 8, 23, 24, 12, 11, 7, 9, 11, 12, 6, 7, 22, 5,
    7, 24, 6, 11, 9, 6, 7, 22, 7, 11, 38, 7, 9, 8, 25, 11, 8, 11, 9, 12,
    8, 12, 5, 38, 5, 38, 5, 11, 7, 5, 6, 21, 6, 10, 53, 8, 7, 24, 10, 27,
    44, 253, 253, 253, 252, 252, 252, 13, 12, 45, 12, 45, 12, 61, 12, 45,
    44, 173))
_LENLEN = bytes((2, 35, 36, 53, 38, 23))
_DISTLEN = bytes((2, 20, 53, 230, 247, 151, 248))


def _construct(rep: bytes):
    """由紧凑游程表生成 (count, symbol) 形式的规范 Huffman 表。"""
    length = []
    for b in rep:
        num = (b >> 4) + 1
        ln = b & 15
        length.extend([ln] * num)
    n = len(length)
    count = [0] * (MAXBITS + 1)
    for ln in length:
        count[ln] += 1
    offs = [0] * (MAXBITS + 2)
    for ln in range(1, MAXBITS + 1):
        offs[ln + 1] = offs[ln] + count[ln]
    symbol = [0] * n
    for sym in range(n):
        if length[sym] != 0:
            symbol[offs[length[sym]]] = sym
            offs[length[sym]] += 1
    return count, symbol


_LITCODE = _construct(_LITLEN)
_LENCODE = _construct(_LENLEN)
_DISTCODE = _construct(_DISTLEN)


class _State:
    __slots__ = ("inp", "incnt", "bitbuf", "bitcnt", "out")

    def __init__(self, data: bytes):
        self.inp = data
        self.incnt = 0
        self.bitbuf = 0
        self.bitcnt = 0
        self.out = bytearray()


def _bits(s: _State, need: int) -> int:
    val = s.bitbuf
    while s.bitcnt < need:
        val |= s.inp[s.incnt] << s.bitcnt
        s.incnt += 1
        s.bitcnt += 8
    s.bitbuf = val >> need
    s.bitcnt -= need
    return val & ((1 << need) - 1)


def _decode(s: _State, h) -> int:
    count, symbol = h
    code = first = index = 0
    length = 1
    while True:
        if s.bitcnt == 0:
            s.bitbuf = s.inp[s.incnt]
            s.incnt += 1
            s.bitcnt = 8
        bit = s.bitbuf & 1
        s.bitbuf >>= 1
        s.bitcnt -= 1
        code |= bit ^ 1            # DCL 码是反相的
        c = count[length]
        if code < first + c:
            return symbol[index + (code - first)]
        index += c
        first += c
        first <<= 1
        code <<= 1
        length += 1
        if length > MAXBITS:
            raise ValueError("explode: 无效的 Huffman 码")


def _copy_match(out: bytearray, start: int, length: int) -> None:
    """LZ77 回溯拷贝：把 out[start:] 起的 length 字节追加到 out 末尾。

    无重叠（回溯距离 ≥ length，即 len(out)-start ≥ length）时整段切片批量拷贝（快）；
    重叠（RLE，如 dist=1 重复末字节）时必须逐字节边写边读，故走慢路径。
    两条路径输出完全一致，仅前者更快。"""
    if len(out) - start >= length:
        out += out[start:start + length]
    else:
        for i in range(length):
            out.append(out[start + i])


def explode(data: bytes, max_output: int | None = None) -> bytes:
    """解压一段 PKWARE DCL 压缩数据，返回原始字节。

    max_output 为输出字节上限，达到即停（防解压炸弹）；None 表示不限。
    """
    s = _State(data)
    out = s.out
    # 输入耗尽时 _bits/_decode 会 s.inp[越界] 抛 IndexError；
    # 统一转成清晰的 ValueError（与 blast.c 输入耗尽返回错误码 2 对应），
    # 避免损坏的 PKWARE 流让上层收到莫名其妙的 IndexError。
    try:
        lit = _bits(s, 8)
        if lit > 1:
            raise ValueError("explode: 非法字面量标志 %d" % lit)
        dict_bits = _bits(s, 8)
        if dict_bits < 4 or dict_bits > 6:
            raise ValueError("explode: 非法字典大小 %d" % dict_bits)
        while True:
            if max_output is not None and len(out) >= max_output:
                break
            if _bits(s, 1):
                sym = _decode(s, _LENCODE)
                length = _BASE[sym] + _bits(s, _EXTRA[sym])
                if length == 519:      # 结束标记
                    break
                dist_bits = 2 if length == 2 else dict_bits
                dist = (_decode(s, _DISTCODE) << dist_bits) + _bits(s, dist_bits) + 1
                start = len(out) - dist
                if start < 0:
                    raise ValueError("explode: 距离越界")
                _copy_match(out, start, length)
            else:
                sym = _decode(s, _LITCODE) if lit else _bits(s, 8)
                out.append(sym & 0xFF)
    except IndexError:
        raise ValueError("explode: 输入数据不完整（损坏的 PKWARE 流）") from None
    if max_output is not None:
        return bytes(out[:max_output])
    return bytes(out)

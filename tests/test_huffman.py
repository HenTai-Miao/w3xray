"""验证 MPQ Huffman 解压（压缩掩码 0x01）。

若 腐朽之渊 地图存在，则读取其 war3map.j（用 Huffman 压缩）并断言解出真实 JASS。
地图不存在时跳过，保证无地图的 CI 也能通过。
"""
import os
import random
import unittest

from w3xtool.huffman import huff_decompress
from w3xtool.mpq import MPQArchive

# 可用环境变量指定 Huffman 测试地图；否则用默认本地路径（不存在则跳过该用例）
MAP_PATH = os.environ.get("W3X_HUFFMAN_MAP", r"C:/Users/zhongerbing/Downloads/腐朽之渊 Rpg v1416d.w3x")


class TestHuffmanSafety(unittest.TestCase):
    """无需外部地图的强制覆盖：解压炸弹封顶 + 任意输入不崩不卡死。"""

    def test_output_never_exceeds_cap(self):
        # 小输入也不得解出超过 out_size 的数据（防解压炸弹）
        for n in (0, 5, 16):
            data = bytes([0]) + bytes(n)            # data_type=0(稀疏) + 一堆 0 比特
            out = huff_decompress(data, 10)
            self.assertLessEqual(len(out), 10)

    def test_empty_input_returns_empty(self):
        self.assertEqual(huff_decompress(b"", 100), b"")

    def test_fuzz_random_bytes_bounded_and_no_crash(self):
        rnd = random.Random(20260610)
        for _ in range(300):
            data = bytes(rnd.randrange(256) for _ in range(rnd.randint(0, 40)))
            cap = rnd.randint(0, 200)
            out = huff_decompress(data, cap)           # 不得抛异常 / 不得卡死
            self.assertIsInstance(out, (bytes, bytearray))
            self.assertLessEqual(len(out), cap)        # 始终不超过硬上限


_GAME_MPQS = [
    r"C:\Program Files (x86)\Warcraft III\war3\War3x.mpq",
    r"C:\Program Files (x86)\Warcraft III\war3\war3.mpq",
    r"C:\Program Files (x86)\Warcraft III\war3\War3xLocal.mpq",
]


def _decode_to_end(data):
    """用当前解码逻辑把一个 Huffman 扇区解到自然终止。

    返回 (reason, out_len, new_syms, bytes_left)。real StormLib 流应得到
    reason='END'（命中 0x100 结束符）且 bytes_left<=1（输入恰好读完）——
    自适应树一旦与编码器失步(如新符号重复加权)就不可能在大量真实流上对齐。
    """
    from w3xtool.huffman import _InputStream, _HuffmannTree
    is_ = _InputStream(data)
    tree = _HuffmannTree()
    ok, dt = is_.get_8_bits()
    if not ok:
        return "EOF", 0, 0, 0
    is_sparse = (dt == 0)
    if not tree.build_tree(dt):
        return "NOTREE", 0, 0, 0
    out = 0
    new_syms = 0
    while out < 1_000_000:
        v = tree.decode_one_byte(is_)
        if v == 0x100:
            return "END", out, new_syms, len(data) - is_.pos
        if v == 0x1FF:
            return "ERR", out, new_syms, len(data) - is_.pos
        if v == 0x101:                       # 新符号：审计曾怀疑此路径重复加权
            new_syms += 1
            ok, v = is_.get_8_bits()
            if not ok:
                return "EOF", out, new_syms, 0
            tree.insert_new_branch_and_rebalance(tree.head.pPrev.DecompressedValue, v)
            if not is_sparse:
                tree.inc_weights_and_rebalance(tree.items_by_byte[v])
        out += 1
        if is_sparse:
            tree.inc_weights_and_rebalance(tree.items_by_byte[v])
    return "LOOP", out, new_syms, 0


class TestHuffmanRealStormLibStreams(unittest.TestCase):
    """对真实 StormLib 编码的 Huffman 流做位级同步校验。

    游戏 MPQ 的音频用 Huffman(+ADPCM) 压缩。逐扇区解码到自然终止：正确实现
    必在编码器写入的 0x100 结束符处恰好停下、输入读尽；新符号(0x101)插入路径
    一旦重复加权就会让自适应树失步、无法在成百上千条真实流上对齐。
    （审计曾怀疑新符号重复加权——此测试证伪：与 StormLib 完全一致。）
    """

    def test_real_huffman_sectors_decode_in_sync(self):
        import w3xtool.mpq as M
        from w3xtool.mpq import MPQArchive
        mpq_path = next((p for p in _GAME_MPQS if os.path.exists(p)), None)
        if not mpq_path:
            self.skipTest("无游戏 MPQ 可取真实 Huffman 流")

        captured = []
        orig = M.huff_decompress

        def cap(data, out_size):
            if len(captured) < 200:
                captured.append(bytes(data))
            return orig(data, out_size)

        M.huff_decompress = cap
        try:
            a = MPQArchive(mpq_path)
            for n in a.list_files():
                try:
                    a.read_file(n)
                except Exception:
                    pass
                if len(captured) >= 200:
                    break
            a.close()
        finally:
            M.huff_decompress = orig

        if not captured:
            self.skipTest("该 MPQ 未用到 Huffman 压缩")

        perfect = 0
        new_sym_sectors = 0
        for data in captured:
            reason, out, ns, left = _decode_to_end(data)
            self.assertEqual(reason, "END",
                             "Huffman 扇区未在 0x100 处终止(树失步)：%s out=%d" % (reason, out))
            self.assertLessEqual(left, 1, "END 时输入未读尽(失步)：剩 %d 字节" % left)
            perfect += 1
            if ns:
                new_sym_sectors += 1
        # 必须真的覆盖到新符号路径，否则这测试没验证审计关心的点
        self.assertGreater(new_sym_sectors, 0, "样本未触发新符号(0x101)插入路径")


class TestHuffmanRealMap(unittest.TestCase):
    def test_war3map_j_huffman(self):
        if not os.path.exists(MAP_PATH):
            self.skipTest("Huffman 测试地图不存在（设 W3X_HUFFMAN_MAP 指定）：%s" % MAP_PATH)
        a = MPQArchive(MAP_PATH)
        j = a.read_file("war3map.j")
        self.assertGreater(len(j), 1_000_000)
        text = j.decode("utf-8", "replace")
        self.assertIn("function", text)
        self.assertIn("endfunction", text)


if __name__ == "__main__":
    unittest.main()

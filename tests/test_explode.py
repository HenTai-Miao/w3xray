"""PKWARE DCL 解压的 LZ77 回溯拷贝：批量切片(无重叠) 与 逐字节(重叠 RLE)
两条路径必须与朴素逐字节实现完全一致。"""
import random
import unittest

from w3xtool.explode import _copy_match


def _naive(prefix: bytes, start: int, length: int) -> bytes:
    out = bytearray(prefix)
    for i in range(length):
        out.append(out[start + i])
    return bytes(out)


class TestCopyMatch(unittest.TestCase):
    def test_non_overlapping_bulk(self):
        out = bytearray(b"ABCDEF")
        _copy_match(out, 0, 3)                 # dist=6 ≥ 3，整段拷贝
        self.assertEqual(bytes(out), b"ABCDEFABC")

    def test_exact_boundary_no_overlap(self):
        out = bytearray(b"ABCD")
        _copy_match(out, 0, 4)                 # dist=4 == length，仍无重叠
        self.assertEqual(bytes(out), b"ABCDABCD")

    def test_rle_single_byte(self):
        out = bytearray(b"AB")
        _copy_match(out, 1, 5)                 # dist=1 < 5，重复末字节
        self.assertEqual(bytes(out), b"AB" + b"B" * 5)

    def test_partial_overlap(self):
        out = bytearray(b"ABC")
        _copy_match(out, 1, 5)                 # dist=2 < 5
        self.assertEqual(bytes(out), _naive(b"ABC", 1, 5))

    def test_matches_naive_random(self):
        rnd = random.Random(3)
        for _ in range(5000):
            n = rnd.randint(1, 20)
            prefix = bytes(rnd.randint(0, 255) for _ in range(n))
            start = rnd.randint(0, n - 1)
            length = rnd.randint(1, 30)
            out = bytearray(prefix)
            _copy_match(out, start, length)
            self.assertEqual(bytes(out), _naive(prefix, start, length),
                             (prefix, start, length))


if __name__ == "__main__":
    unittest.main()

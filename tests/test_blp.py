"""BLP2 调色板解码特征测试：锁定 索引→RGBA 的精确输出。

BLP 调色板是 BGRA 存储；解码应映射成 RGBA（B/R 交换），无 alpha 通道时 alpha=255。
用于在把逐像素循环改成向量化(PIL "P" 模式)时保证输出不变。
"""

import struct
import unittest

from w3xtool.blp import decode_blp


def _build_blp2_palette(width, height, palette_bgra, indices, alpha=None):
    """构造一张最小 BLP2 调色板图。palette_bgra: list[(B,G,R,A)]；indices: list[int]。"""
    buf = bytearray(20 + 128 + 1024)
    buf[0:4] = b"BLP2"
    alpha_depth = 8 if alpha is not None else 0
    struct.pack_into("<I", buf, 4, 1)  # compression
    struct.pack_into(
        "<BBBB", buf, 8, 1, alpha_depth, 0, 0
    )  # encoding, alpha_depth, ...
    struct.pack_into("<II", buf, 12, width, height)
    data_off = 20 + 128 + 1024
    struct.pack_into("<I", buf, 20, data_off)  # mip_offsets[0]
    data_size = len(indices) + (len(alpha) if alpha is not None else 0)
    struct.pack_into("<I", buf, 20 + 64, data_size)  # mip_sizes[0]
    pal = bytearray(1024)
    for i, (b, g, r, a) in enumerate(palette_bgra):
        pal[i * 4 : i * 4 + 4] = bytes([b, g, r, a])
    buf[20 + 128 : 20 + 128 + 1024] = pal
    buf += bytes(indices)
    if alpha is not None:
        buf += bytes(alpha)
    return bytes(buf)


def _build_blp2_dxt1_red() -> bytes:
    """Build one correctly laid-out 4x4 BLP2 DXT1 block."""
    buf = bytearray(20 + 128 + 1024)
    buf[0:4] = b"BLP2"
    struct.pack_into("<I", buf, 4, 1)
    struct.pack_into("<BBBB", buf, 8, 2, 0, 0, 0)
    struct.pack_into("<II", buf, 12, 4, 4)
    data_off = len(buf)
    struct.pack_into("<I", buf, 20, data_off)
    struct.pack_into("<I", buf, 20 + 64, 8)
    buf += struct.pack("<HHI", 0xF800, 0x07E0, 0)
    return bytes(buf)


class TestBlpMaliciousInput(unittest.TestCase):
    """BLP 来自不可信地图：畸形头不应 OOM 或抛异常，应安全返回 None。"""

    def test_huge_dimensions_do_not_oom(self):
        # width*height ≈ 42 亿，旧码 bytearray(n*4) 会尝试分配 ~17GB
        data = _build_blp2_palette(1, 1, [(0, 0, 0, 255)], [0])
        data = bytearray(data)
        struct.pack_into("<II", data, 12, 0xFFFF, 0xFFFF)  # 篡改成巨大尺寸
        self.assertIsNone(decode_blp(bytes(data)))

    def test_truncated_blp1_header_returns_none(self):
        # 以 BLP1 开头但头部不完整：旧码 struct.unpack_from 会抛 struct.error
        self.assertIsNone(decode_blp(b"BLP1"))
        self.assertIsNone(decode_blp(b"BLP1" + b"\x00" * 20))

    def test_truncated_blp2_header_returns_none(self):
        self.assertIsNone(decode_blp(b"BLP2"))
        self.assertIsNone(decode_blp(b"BLP2" + b"\x00" * 20))

    def test_short_data_returns_none(self):
        self.assertIsNone(decode_blp(b""))
        self.assertIsNone(decode_blp(b"BL"))


class TestBlp2Palette(unittest.TestCase):
    def test_palette_indices_map_to_rgba(self):
        pal = [
            (10, 20, 30, 255),
            (40, 50, 60, 255),
            (70, 80, 90, 255),
            (100, 110, 120, 255),
        ]
        data = _build_blp2_palette(2, 2, pal, [0, 1, 2, 3])
        img = decode_blp(data)
        assert img is not None
        self.assertEqual(img.size, (2, 2))
        self.assertEqual(img.mode, "RGBA")
        # BGRA(b,g,r) -> RGBA(r,g,b,255)，按像素展开成字节比较
        self.assertEqual(
            img.tobytes(),
            bytes(
                [30, 20, 10, 255, 60, 50, 40, 255, 90, 80, 70, 255, 120, 110, 100, 255]
            ),
        )

    def test_palette_with_8bit_alpha(self):
        pal = [(10, 20, 30, 255), (40, 50, 60, 255)]
        data = _build_blp2_palette(2, 1, pal, [0, 1], alpha=[128, 64])
        img = decode_blp(data)
        assert img is not None
        self.assertEqual(img.tobytes(), bytes([30, 20, 10, 128, 60, 50, 40, 64]))

    def test_dxt1_icon_decodes_to_rgba(self):
        # Given: a correctly laid-out Reforged BLP2 DXT1 texture.
        data = _build_blp2_dxt1_red()

        # When: the public decoder loads it.
        img = decode_blp(data)

        # Then: compressed client icons are visible instead of silently returning None.
        assert img is not None
        self.assertEqual(img.size, (4, 4))
        self.assertEqual(img.convert("RGBA").getpixel((0, 0)), (248, 0, 0, 255))


if __name__ == "__main__":
    unittest.main()

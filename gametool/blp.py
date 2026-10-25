"""BLP 图片解码（魔兽图标格式）。支持 BLP1 的 JPEG 内容与调色板内容，及 BLP2 调色板。

返回 PIL.Image（RGBA）。JPEG 内容借助 Pillow 解码。
"""

from __future__ import annotations

import struct
from io import BytesIO


def _palette_rgba(Image, pal, idx, alpha_data, width, height):
    """调色板(BGRA)+索引 → RGBA 图。

    常见情形（索引完整）用 PIL "P" 模式让 C 层批量展开，避免逐像素 Python 循环；
    索引被截断等异常情形回退逐像素，保留旧的 (0,0,0,0) 填充语义。
    """
    n = width * height
    pal = bytes(pal).ljust(1024, b"\x00")  # 补齐 256 个 BGRA 条目，防越界
    if n > 0 and len(idx) >= n:
        # 256 项调色板转 RGB（小循环，非热点），交给 Pillow 批量展开 n 个像素
        rgb_pal = bytearray(768)
        for i in range(256):
            rgb_pal[i * 3] = pal[i * 4 + 2]  # R
            rgb_pal[i * 3 + 1] = pal[i * 4 + 1]  # G
            rgb_pal[i * 3 + 2] = pal[i * 4]  # B
        pimg = Image.frombytes("P", (width, height), bytes(idx[:n]))
        pimg.putpalette(bytes(rgb_pal))
        img = pimg.convert("RGB")
        if alpha_data is not None:
            # 不足 n 的尾部补 255，与旧逐像素逻辑一致
            a_full = bytes(alpha_data[:n]).ljust(n, b"\xff")
            img.putalpha(Image.frombytes("L", (width, height), a_full))
        else:
            img = img.convert("RGBA")
        return img
    # 回退：逐像素
    out = bytearray(n * 4)
    for i in range(min(n, len(idx))):
        p = idx[i] * 4
        out[i * 4] = pal[p + 2]
        out[i * 4 + 1] = pal[p + 1]
        out[i * 4 + 2] = pal[p]
        out[i * 4 + 3] = 255
    if alpha_data is not None:
        for i in range(min(n, len(alpha_data))):
            out[i * 4 + 3] = alpha_data[i]
    return Image.frombytes("RGBA", (width, height), bytes(out))


def decode_blp(data: bytes):
    from PIL import Image

    if data[:4] == b"BLP1":
        return _decode_blp1(data, Image)
    if data[:4] == b"BLP2":
        return _decode_blp2(data, Image)
    # 也许就是普通图片(png/tga/jpg) — 交给 Pillow 试
    try:
        return Image.open(BytesIO(data)).convert("RGBA")
    except NotImplementedError, OSError, ValueError, struct.error:
        return None


def _decode_blp1(data, Image):
    if len(data) < 28 + 128 + 4:  # 头(24)+mip偏移表(64)+mip大小表(64)+jpeg头长(4)
        return None
    (compression, flags, width, height, _pic_type, _pic_subtype) = struct.unpack_from(
        "<IIIIII", data, 4
    )
    if width <= 0 or height <= 0:
        return None
    mip_offsets = struct.unpack_from("<16I", data, 28)
    mip_sizes = struct.unpack_from("<16I", data, 28 + 64)

    if compression == 0:
        # JPEG 内容：共享头 + 第0级数据 拼成完整 JPEG
        jpeg_hdr_size = struct.unpack_from("<I", data, 28 + 128)[0]
        hdr_start = 28 + 128 + 4
        if hdr_start + jpeg_hdr_size > len(data):
            return None
        shared = data[hdr_start : hdr_start + jpeg_hdr_size]
        off, size = mip_offsets[0], mip_sizes[0]
        if off < hdr_start or size <= 0 or off + size > len(data):
            return None
        jpeg = shared + data[off : off + size]
        try:
            img = Image.open(BytesIO(jpeg))
            if img.size != (width, height):
                return None
            img.load()
        except NotImplementedError, OSError, ValueError, struct.error:
            return None
        # BLP 的 JPEG 是反相存储的 BGRA(被读成 CMYK)：各通道取反 + 调成 RGB
        if img.mode == "CMYK":
            from PIL import ImageChops

            ch = [ImageChops.invert(c) for c in img.split()]
            img = Image.merge(
                "RGBA", (ch[2], ch[1], ch[0], Image.new("L", img.size, 255))
            )
        else:
            img = img.convert("RGBA")
        return img

    # compression == 1：调色板
    pal = data[28 + 128 + 0 : 28 + 128 + 1024]  # 256*4 BGRA
    off = mip_offsets[0]
    n = width * height
    required = n * (2 if flags == 8 else 1)
    if compression != 1 or off < 28 + 128 + 1024 or off + required > len(data):
        return None
    idx = data[off : off + n]
    alpha_data = data[off + n : off + n + n] if flags == 8 else None
    return _palette_rgba(Image, pal, idx, alpha_data, width, height)


def _decode_blp2(data, Image):
    # BLP2 stores a uint32 compression at offset 4, followed by four byte fields.
    # Pillow's bundled BLP decoder supports palette plus DXT1/3/5 and is the
    # authoritative implementation for these variants.
    if len(data) < 20:
        return None
    width, height = struct.unpack_from("<II", data, 12)
    if width <= 0 or height <= 0:
        return None
    encoding, alpha_depth = struct.unpack_from("<BB", data, 8)
    if encoding == 1:
        if len(data) < 20 + 128 + 1024:
            return None
        (offset,) = struct.unpack_from("<I", data, 20)
        pixel_count = width * height
        if alpha_depth not in (0, 1, 4, 8):
            return None
        alpha_bytes = (pixel_count * alpha_depth + 7) // 8
        if offset < 20 + 128 + 1024 or offset + pixel_count + alpha_bytes > len(data):
            return None
        palette = data[20 + 128 : 20 + 128 + 1024]
        indices = data[offset : offset + pixel_count]
        alpha = _unpack_alpha(
            data[offset + pixel_count : offset + pixel_count + alpha_bytes],
            alpha_depth,
            pixel_count,
        )
        return _palette_rgba(Image, palette, indices, alpha, width, height)
    if encoding == 2:
        if len(data) < 148:
            return None
        offset = struct.unpack_from("<I", data, 20)[0]
        alpha_encoding = data[10]
        block_bytes = 8 if alpha_depth == 0 or alpha_encoding == 0 else 16
        required = ((width + 3) // 4) * ((height + 3) // 4) * block_bytes
        if offset < 148 or offset + required > len(data):
            return None
    try:
        image = Image.open(BytesIO(data))
        image.load()
        return image.convert("RGBA")
    except NotImplementedError, OSError, ValueError, struct.error:
        return None


def _unpack_alpha(data: bytes, depth: int, count: int) -> bytes | None:
    if depth == 0:
        return None
    if depth == 8:
        return data
    mask = (1 << depth) - 1
    per_byte = 8 // depth
    return bytes(
        ((data[index // per_byte] >> ((index % per_byte) * depth)) & mask)
        * (255 // mask)
        for index in range(count)
    )

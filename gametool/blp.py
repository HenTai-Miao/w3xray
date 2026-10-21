"""BLP 图片解码（魔兽图标格式）。支持 BLP1 的 JPEG 内容与调色板内容，及 BLP2 调色板。

返回 PIL.Image（RGBA）。JPEG 内容借助 Pillow 解码。
"""

from __future__ import annotations

import struct
from io import BytesIO

# 单边像素上限：真实地图图标(64)/纹理/载入图远小于此。BLP 来自不可信地图，
# 头里 width*height 直接驱动内存分配，必须设硬上限防解压炸弹(否则可被构造成 ~17GB)。
_MAX_DIM = 4096


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
    (compression, flags, width, height, pic_type, pic_subtype) = struct.unpack_from(
        "<IIIIII", data, 4
    )
    if not (0 < width <= _MAX_DIM and 0 < height <= _MAX_DIM):
        return None
    mip_offsets = struct.unpack_from("<16I", data, 28)
    mip_sizes = struct.unpack_from("<16I", data, 28 + 64)

    if compression == 0:
        # JPEG 内容：共享头 + 第0级数据 拼成完整 JPEG
        jpeg_hdr_size = struct.unpack_from("<I", data, 28 + 128)[0]
        hdr_start = 28 + 128 + 4
        shared = data[hdr_start : hdr_start + jpeg_hdr_size]
        off, size = mip_offsets[0], mip_sizes[0]
        jpeg = shared + data[off : off + size]
        try:
            img = Image.open(BytesIO(jpeg))
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
    if not (0 < width <= _MAX_DIM and 0 < height <= _MAX_DIM):
        return None
    encoding, alpha_depth = struct.unpack_from("<BB", data, 8)
    if encoding == 1:
        if len(data) < 20 + 128 + 1024:
            return None
        (offset,) = struct.unpack_from("<I", data, 20)
        pixel_count = width * height
        palette = data[20 + 128 : 20 + 128 + 1024]
        indices = data[offset : offset + pixel_count]
        alpha = (
            data[offset + pixel_count : offset + pixel_count * 2]
            if alpha_depth == 8
            else None
        )
        return _palette_rgba(Image, palette, indices, alpha, width, height)
    try:
        image = Image.open(BytesIO(data))
        image.load()
        return image.convert("RGBA")
    except NotImplementedError, OSError, ValueError, struct.error:
        return None

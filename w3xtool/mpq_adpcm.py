"""StormLib-compatible bounded MPQ ADPCM decompression."""

from __future__ import annotations

import sys
from array import array
from typing import Final, Literal


class MPQADPCMError(ValueError):
    """Raised when an MPQ ADPCM stream violates its declared bounds."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


NEXT_STEP_TABLE: Final = (
    -1, 0, -1, 4, -1, 2, -1, 6, -1, 1, -1, 5, -1, 3, -1, 7,
    -1, 1, -1, 5, -1, 3, -1, 7, -1, 2, -1, 4, -1, 6, -1, 8,
)
STEP_SIZE_TABLE: Final = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143,
    157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544,
    598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707,
    1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871,
    5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635,
    13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
)
INITIAL_STEP_INDEX: Final = 44


def _build_next_index_table() -> tuple[tuple[int, ...], ...]:
    """每（步长索引, 字节）直接给出已钳位的下一索引。"""
    rows: list[tuple[int, ...]] = []
    for step_index in range(89):
        row = tuple(
            max(0, min(88, step_index + NEXT_STEP_TABLE[encoded & 0x1F]))
            for encoded in range(256)
        )
        rows.append(row)
    return tuple(rows)


_NEXT_INDEX_TABLE: Final = _build_next_index_table()
_DIFFERENCE_TABLES: dict[int, tuple[tuple[int, ...], ...]] = {}


def _difference_table(bit_shift: int) -> tuple[tuple[int, ...], ...]:
    """每（步长索引, 编码 6 位）直接给出解码差分值；按流内 shift 记忆。"""
    cached = _DIFFERENCE_TABLES.get(bit_shift)
    if cached is not None:
        return cached
    rows: list[tuple[int, ...]] = []
    for step_size in STEP_SIZE_TABLE:
        base = step_size >> bit_shift
        row = tuple(
            base
            + (step_size if code & 0x01 else 0)
            + (step_size >> 1 if code & 0x02 else 0)
            + (step_size >> 2 if code & 0x04 else 0)
            + (step_size >> 3 if code & 0x08 else 0)
            + (step_size >> 4 if code & 0x10 else 0)
            + (step_size >> 5 if code & 0x20 else 0)
            for code in range(64)
        )
        rows.append(row)
    table = tuple(rows)
    _DIFFERENCE_TABLES[bit_shift] = table
    return table


def decompress_adpcm(
    data: bytes, channels: Literal[1, 2], output_size: int
) -> bytes:
    """Decode Blizzard's adaptive PCM stream without exceeding ``output_size``.

    音频密集的 RPG 地图单图就有上十亿个样本；原实现每样本调用
    _write_sample/_next_step_index/_decode_sample 三个函数并逐样本
    min/max/to_bytes/extend。这里把整条解码链内联成单层循环：
    单/双声道分开（立体声用两组局部量避免列表寻址），位加法展开，
    输出进 array('h') 一次落盘，边界检查用样本计数内联。
    """
    if channels not in (1, 2):
        raise MPQADPCMError(f"invalid ADPCM channels: {channels}")
    if output_size < 0:
        raise MPQADPCMError(f"invalid ADPCM output size: {output_size}")
    header_size = 2 + channels * 2
    if len(data) < header_size:
        raise MPQADPCMError("truncated ADPCM header")

    bit_shift = data[1]
    next_table = _NEXT_INDEX_TABLE
    difference_table = _difference_table(bit_shift)
    out: array = array("h")
    append = out.append
    max_samples = output_size // 2

    if channels == 1:
        predictor = int.from_bytes(data[2:4], "little", signed=True)
        step_index = INITIAL_STEP_INDEX
        if max_samples < 1:
            raise MPQADPCMError("ADPCM output exceeds declared size")
        append(predictor)
        count = 1
        for encoded in data[4:]:
            if encoded == 0x80:
                if step_index != 0:
                    step_index -= 1
            elif encoded == 0x81:
                step_index += 8
                if step_index > 88:
                    step_index = 88
                continue
            else:
                difference = difference_table[step_index][encoded & 0x3F]
                if encoded & 0x40:
                    predictor -= difference
                    if predictor < -32768:
                        predictor = -32768
                else:
                    predictor += difference
                    if predictor > 32767:
                        predictor = 32767
                step_index = next_table[step_index][encoded]
            if count >= max_samples:
                raise MPQADPCMError("ADPCM output exceeds declared size")
            append(predictor)
            count += 1
    else:
        predictor_left = int.from_bytes(data[2:4], "little", signed=True)
        predictor_right = int.from_bytes(data[4:6], "little", signed=True)
        index_left = INITIAL_STEP_INDEX
        index_right = INITIAL_STEP_INDEX
        if max_samples < 2:
            raise MPQADPCMError("ADPCM output exceeds declared size")
        append(predictor_left)
        append(predictor_right)
        count = 2
        channel = 1
        for encoded in data[6:]:
            channel ^= 1
            if encoded == 0x80:
                if channel == 0:
                    if index_left != 0:
                        index_left -= 1
                else:
                    if index_right != 0:
                        index_right -= 1
            elif encoded == 0x81:
                if channel == 0:
                    index_left += 8
                    if index_left > 88:
                        index_left = 88
                else:
                    index_right += 8
                    if index_right > 88:
                        index_right = 88
                channel ^= 1
                continue
            elif channel == 0:
                difference = difference_table[index_left][encoded & 0x3F]
                if encoded & 0x40:
                    predictor_left -= difference
                    if predictor_left < -32768:
                        predictor_left = -32768
                else:
                    predictor_left += difference
                    if predictor_left > 32767:
                        predictor_left = 32767
                index_left = next_table[index_left][encoded]
            else:
                difference = difference_table[index_right][encoded & 0x3F]
                if encoded & 0x40:
                    predictor_right -= difference
                    if predictor_right < -32768:
                        predictor_right = -32768
                else:
                    predictor_right += difference
                    if predictor_right > 32767:
                        predictor_right = 32767
                index_right = next_table[index_right][encoded]
            if count >= max_samples:
                raise MPQADPCMError("ADPCM output exceeds declared size")
            if channel == 0:
                append(predictor_left)
            else:
                append(predictor_right)
            count += 1

    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes()

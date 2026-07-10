"""StormLib-compatible bounded MPQ ADPCM decompression."""

from __future__ import annotations

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


def _write_sample(out: bytearray, sample: int, output_size: int) -> None:
    if len(out) + 2 > output_size:
        raise MPQADPCMError("ADPCM output exceeds declared size")
    out.extend(sample.to_bytes(2, "little", signed=True))


def _next_step_index(step_index: int, encoded: int) -> int:
    return max(0, min(88, step_index + NEXT_STEP_TABLE[encoded & 0x1F]))


def _decode_sample(predicted: int, encoded: int, step_size: int, shift: int) -> int:
    difference = step_size >> shift
    for bit, divisor in ((0x01, 0), (0x02, 1), (0x04, 2), (0x08, 3),
                         (0x10, 4), (0x20, 5)):
        if encoded & bit:
            difference += step_size >> divisor
    if encoded & 0x40:
        return max(-32768, predicted - difference)
    return min(32767, predicted + difference)


def decompress_adpcm(
    data: bytes, channels: Literal[1, 2], output_size: int
) -> bytes:
    """Decode Blizzard's adaptive PCM stream without exceeding ``output_size``."""
    if channels not in (1, 2):
        raise MPQADPCMError(f"invalid ADPCM channels: {channels}")
    if output_size < 0:
        raise MPQADPCMError(f"invalid ADPCM output size: {output_size}")
    header_size = 2 + channels * 2
    if len(data) < header_size:
        raise MPQADPCMError("truncated ADPCM header")

    bit_shift = data[1]
    predictors = [0, 0]
    step_indexes = [INITIAL_STEP_INDEX, INITIAL_STEP_INDEX]
    out = bytearray()
    position = 2
    for channel in range(channels):
        predictor = int.from_bytes(data[position : position + 2], "little", signed=True)
        position += 2
        predictors[channel] = predictor
        _write_sample(out, predictor, output_size)

    channel = channels - 1
    for encoded in data[position:]:
        channel = (channel + 1) % channels
        if encoded == 0x80:
            if step_indexes[channel] != 0:
                step_indexes[channel] -= 1
            _write_sample(out, predictors[channel], output_size)
            continue
        if encoded == 0x81:
            step_indexes[channel] = min(88, step_indexes[channel] + 8)
            channel = (channel + 1) % channels
            continue

        old_index = step_indexes[channel]
        predictors[channel] = _decode_sample(
            predictors[channel], encoded, STEP_SIZE_TABLE[old_index], bit_shift
        )
        _write_sample(out, predictors[channel], output_size)
        step_indexes[channel] = _next_step_index(old_index, encoded)
    return bytes(out)

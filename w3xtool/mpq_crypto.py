"""Storm MPQ hashing and table/block decryption primitives."""

from __future__ import annotations

import struct
from typing import Final


_ASCII_UPPER_TABLE: Final = bytes.maketrans(
    b"abcdefghijklmnopqrstuvwxyz", b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
)


def _make_crypt_table() -> tuple[int, ...]:
    table = [0] * 0x500
    seed = 0x00100001
    for index1 in range(0x100):
        index2 = index1
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp1 = (seed & 0xFFFF) << 0x10
            seed = (seed * 125 + 3) % 0x2AAAAB
            table[index2] = (temp1 | (seed & 0xFFFF)) & 0xFFFFFFFF
            index2 += 0x100
    return tuple(table)


CRYPT_TABLE: Final = _make_crypt_table()


def hash_name_bytes(name: bytes, hash_type: int) -> int:
    """Hash exact MPQ filename bytes using Storm's ASCII-only uppercase table."""
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE
    for byte in name.translate(_ASCII_UPPER_TABLE):
        value = CRYPT_TABLE[(hash_type << 8) + byte]
        seed1 = (value ^ ((seed1 + seed2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        seed2 = (byte + seed1 + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
    return seed1


def _hash(name: str, hash_type: int) -> int:
    """Compatibility wrapper for the reader's historical string hash helper."""
    return hash_name_bytes(name.encode("utf-8"), hash_type)


def _decrypt(data: bytes, key: int) -> bytes:
    count = len(data) // 4
    if count == 0:
        return data
    # 解密是导出路径最重的纯 Python 热点：绑定局部表、去掉冗余掩码
    # （参与异或的两个数都已是 32 位内），避免每次循环的全局查找。
    table = CRYPT_TABLE
    seed1 = key & 0xFFFFFFFF
    seed2 = 0xEEEEEEEE
    encrypted_words = struct.unpack(f"<{count}I", data[: count * 4])
    values = [0] * count
    for index in range(count):
        encrypted = encrypted_words[index]
        seed2 = (seed2 + table[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
        value = encrypted ^ ((seed1 + seed2) & 0xFFFFFFFF)
        values[index] = value
        seed1 = (
            ((~seed1 & 0xFFFFFFFF) << 0x15) + 0x11111111 | (seed1 >> 0x0B)
        ) & 0xFFFFFFFF
        seed2 = (value + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
    plain = struct.pack(f"<{count}I", *values)
    return plain + data[count * 4 :]


def _detect_offtable_key(e0: int, e1: int, off0: int, max_off1: int) -> int | None:
    """Recover a sector-offset-table key from its first two known plaintexts."""
    temp = ((e0 ^ off0) - 0xEEEEEEEE) & 0xFFFFFFFF
    for candidate in range(0x100):
        key1 = (temp - CRYPT_TABLE[0x400 + candidate]) & 0xFFFFFFFF
        key2 = (0xEEEEEEEE + CRYPT_TABLE[0x400 + (key1 & 0xFF)]) & 0xFFFFFFFF
        if (e0 ^ ((key1 + key2) & 0xFFFFFFFF)) != off0:
            continue
        next_key = (
            ((~key1 & 0xFFFFFFFF) << 0x15) + 0x11111111 | (key1 >> 0x0B)
        ) & 0xFFFFFFFF
        next_seed = (off0 + key2 + (key2 << 5) + 3) & 0xFFFFFFFF
        next_seed = (
            next_seed + CRYPT_TABLE[0x400 + (next_key & 0xFF)]
        ) & 0xFFFFFFFF
        if off0 < (e1 ^ ((next_key + next_seed) & 0xFFFFFFFF)) <= max_off1:
            return key1
    return None

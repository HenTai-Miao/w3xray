"""Read PE headers and declared version resources as data, without loading code."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import struct


class PEImageError(ValueError):
    """A declared image structure is missing, truncated or ambiguous."""


@dataclass(frozen=True, slots=True)
class PESection:
    rva: int
    virtual_size: int
    raw_offset: int
    raw_size: int


@dataclass(frozen=True, slots=True)
class PEHeader:
    machine: int
    timestamp: int
    image_size: int
    headers_size: int
    resource_rva: int
    resource_size: int
    sections: tuple[PESection, ...]


@dataclass(frozen=True, slots=True)
class PEImage:
    header: PEHeader | None
    version: str | None = None
    diagnostics: tuple[str, ...] = ()


def pe_header_record(header: PEHeader) -> dict[str, object]:
    """Use JSON arrays for section records in persisted live reports."""
    record = asdict(header)
    record["sections"] = [asdict(section) for section in header.sections]
    return record


def read_pe_header(
    read_at: Callable[[int, int], bytes | None], extent: int
) -> PEHeader:
    """Parse only measured header ranges, for either disk or loaded images."""

    def read(offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > extent:
            raise PEImageError(f"PE 范围越界: 0x{offset:X}+0x{size:X}")
        data = read_at(offset, size)
        if data is None or len(data) != size:
            raise PEImageError(f"PE 读取不完整: 0x{offset:X}+0x{size:X}")
        return data

    dos = read(0, 64)
    if dos[:2] != b"MZ":
        raise PEImageError("缺少 DOS MZ 头")
    pe_offset = struct.unpack_from("<I", dos, 0x3C)[0]
    if pe_offset < 64:
        raise PEImageError("PE 头偏移落在 DOS 头内")
    coff = read(pe_offset, 24)
    if coff[:4] != b"PE\0\0":
        raise PEImageError("缺少 PE 签名")
    machine, section_count, timestamp = struct.unpack_from("<HHI", coff, 4)
    optional_size = struct.unpack_from("<H", coff, 20)[0]
    optional = read(pe_offset + 24, optional_size)
    if len(optional) < 64:
        raise PEImageError("PE Optional Header 不完整")
    magic = struct.unpack_from("<H", optional)[0]
    directory_start = {0x10B: 96, 0x20B: 112}.get(magic)
    if directory_start is None or len(optional) < directory_start:
        raise PEImageError("PE Optional Header 格式未知或不完整")
    if (machine == 0x14C and magic != 0x10B) or (
        machine in (0x8664, 0xAA64) and magic != 0x20B
    ):
        raise PEImageError("PE Machine 与 Optional Header 位数冲突")
    image_size, headers_size = struct.unpack_from("<II", optional, 56)
    section_offset = pe_offset + 24 + optional_size
    if not headers_size or image_size < headers_size:
        raise PEImageError("PE SizeOfImage/SizeOfHeaders 无效")
    if section_offset + section_count * 40 > headers_size:
        raise PEImageError("PE 节表超出 SizeOfHeaders")
    if headers_size > extent:
        raise PEImageError("PE 头超出实际映像范围")
    directory_count = struct.unpack_from("<I", optional, directory_start - 4)[0]
    if directory_count > (len(optional) - directory_start) // 8:
        raise PEImageError("PE 数据目录数量超出 Optional Header")
    resource_rva = resource_size = 0
    if directory_count > 2:
        resource_rva, resource_size = struct.unpack_from(
            "<II", optional, directory_start + 16
        )
    if bool(resource_rva) != bool(resource_size):
        raise PEImageError("PE 资源目录 RVA/长度不成对")
    if resource_rva + resource_size > image_size:
        raise PEImageError("PE 资源目录超出 SizeOfImage")
    section_data = read(section_offset, section_count * 40)
    sections: list[PESection] = []
    for offset in range(0, len(section_data), 40):
        virtual_size, rva, raw_size, raw_offset = struct.unpack_from(
            "<IIII", section_data, offset + 8
        )
        if rva + max(virtual_size, raw_size) > image_size:
            raise PEImageError("PE 节范围超出 SizeOfImage")
        sections.append(PESection(rva, virtual_size, raw_offset, raw_size))
    return PEHeader(
        machine,
        timestamp,
        image_size,
        headers_size,
        resource_rva,
        resource_size,
        tuple(sections),
    )


def _rva_bytes(data: bytes, header: PEHeader, rva: int, size: int) -> bytes:
    """Require one complete disk mapping; overlapping sections are ambiguous."""
    candidates: list[int] = []
    if 0 <= rva and rva + size <= header.headers_size:
        candidates.append(rva)
    for section in header.sections:
        delta = rva - section.rva
        if 0 <= delta and delta + size <= max(section.virtual_size, section.raw_size):
            if delta + size > section.raw_size:
                raise PEImageError("PE 资源位于未落盘的节范围")
            candidates.append(section.raw_offset + delta)
    if len(candidates) != 1:
        raise PEImageError("PE 资源 RVA 缺少唯一的完整节映射")
    offset = candidates[0]
    if offset + size > len(data):
        raise PEImageError("PE 资源数据超出实际文件")
    return data[offset : offset + size]


def _fixed_version(payload: bytes) -> str:
    if len(payload) < 6:
        raise PEImageError("VS_VERSION_INFO 头不完整")
    length, value_length, kind = struct.unpack_from("<HHH", payload)
    if length > len(payload) or length < 6 or kind != 0:
        raise PEImageError("VS_VERSION_INFO 长度/类型无效")
    end = 6
    while end + 2 <= length and payload[end : end + 2] != b"\0\0":
        end += 2
    if end + 2 > length:
        raise PEImageError("VS_VERSION_INFO 名称未终止")
    if payload[6:end] != "VS_VERSION_INFO".encode("utf-16-le"):
        raise PEImageError("RT_VERSION 根名称不是 VS_VERSION_INFO")
    value_offset = (end + 2 + 3) & ~3
    if value_length != 52 or value_offset + value_length > length:
        raise PEImageError("VS_FIXEDFILEINFO 长度无效或不完整")
    signature, structure_version, ms, ls = struct.unpack_from(
        "<IIII", payload, value_offset
    )
    if signature != 0xFEEF04BD or structure_version != 0x10000:
        raise PEImageError("VS_FIXEDFILEINFO 签名/结构版本无效")
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def _resource_version(data: bytes, header: PEHeader) -> str:
    if not header.resource_rva:
        raise PEImageError("PE 未声明版本资源")
    resources = _rva_bytes(data, header, header.resource_rva, header.resource_size)

    def entries(offset: int) -> list[tuple[int, int]]:
        if offset + 16 > len(resources):
            raise PEImageError("PE 资源目录头越界")
        named, ids = struct.unpack_from("<HH", resources, offset + 12)
        count = named + ids
        if count > (len(resources) - offset - 16) // 8:
            raise PEImageError("PE 资源目录条目不完整")
        return [
            struct.unpack_from("<II", resources, entry)
            for entry in range(offset + 16, offset + 16 + count * 8, 8)
        ]

    roots = [target for name, target in entries(0) if name == 16]
    if len(roots) != 1:
        raise PEImageError("PE 缺少唯一的 RT_VERSION 资源类型")
    versions: set[str] = set()
    pending = [(roots[0], 0, frozenset({0}))]
    while pending:
        target, depth, ancestors = pending.pop()
        is_directory = bool(target & 0x80000000)
        offset = target & 0x7FFFFFFF
        if is_directory:
            if depth >= 2 or offset in ancestors:
                raise PEImageError("RT_VERSION 目录层级无效或循环")
            children = entries(offset)
            if not children:
                raise PEImageError("RT_VERSION 目录为空")
            for _name, child in children:
                pending.append((child, depth + 1, ancestors | {offset}))
        else:
            if depth != 2 or offset + 16 > len(resources):
                raise PEImageError("RT_VERSION 数据条目层级无效或越界")
            rva, size = struct.unpack_from("<II", resources, offset)
            versions.add(_fixed_version(_rva_bytes(data, header, rva, size)))
    if len(versions) != 1:
        raise PEImageError("RT_VERSION 的多个版本资源互相冲突")
    return next(iter(versions))


def parse_pe_image(data: bytes) -> PEImage:
    """An absent/bad version resource cannot erase a confirmed machine header."""
    try:
        header = read_pe_header(
            lambda offset, size: data[offset : offset + size], len(data)
        )
        for section in header.sections:
            if section.raw_size and section.raw_offset + section.raw_size > len(data):
                raise PEImageError("PE 节数据超出实际文件")
    except PEImageError as exc:
        return PEImage(None, diagnostics=(str(exc),))
    try:
        return PEImage(header, _resource_version(data, header))
    except PEImageError as exc:
        return PEImage(header, diagnostics=(str(exc),))


def _file_identity(stat: os.stat_result) -> tuple[int, ...]:
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def read_pe_image(path: str | os.PathLike[str]) -> PEImage:
    """Read one stable file snapshot for both version and header metadata."""
    try:
        with open(path, "rb") as stream:
            before = os.fstat(stream.fileno())
            data = stream.read()
            after = os.fstat(stream.fileno())
            current = Path(path).stat()
        if (
            _file_identity(before) != _file_identity(after)
            # Windows stat(path) and fstat(fd) expose different legacy ctime
            # semantics. Compare ctime only between the two descriptor reads.
            or _file_identity(after)[:4] != _file_identity(current)[:4]
            or len(data) != after.st_size
        ):
            return PEImage(None, diagnostics=("读取期间 PE 文件已变化或被替换",))
        return parse_pe_image(data)
    except (OSError, MemoryError, OverflowError) as exc:
        return PEImage(
            None, diagnostics=(f"PE 文件不可读: {type(exc).__name__}: {exc}",)
        )

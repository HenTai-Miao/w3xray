"""地图内部结构文件的只读摘要。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Final

STRUCTURE_FILES: Final = (
    "war3map.w3r",
    "war3map.w3c",
    "war3map.w3s",
    "war3map.wpm",
    "war3map.shd",
)
_MAX_COUNT: Final = 1_000_000
_MAX_STRINGS: Final = 50
_MIN_STRING_LEN: Final = 2


@dataclass(frozen=True, slots=True)
class PathingSummary:
    width: int
    height: int
    cells: int
    no_walk: int = 0
    no_fly: int = 0
    no_build: int = 0
    blight: int = 0
    no_water: int = 0
    unknown: int = 0


@dataclass(frozen=True, slots=True)
class ShadowSummary:
    width: int | None
    height: int | None
    cells: int
    shadowed: int
    unshadowed: int
    unknown: int = 0


@dataclass(frozen=True, slots=True)
class MapStructureReport:
    regions: int | None = None
    cameras: int | None = None
    sounds: int | None = None
    pathing: PathingSummary | None = None
    shadow: ShadowSummary | None = None
    region_strings: tuple[str, ...] = ()
    camera_strings: tuple[str, ...] = ()
    sound_strings: tuple[str, ...] = ()

    @property
    def has_data(self) -> bool:
        return any(value is not None for value in (
            self.regions,
            self.cameras,
            self.sounds,
            self.pathing,
            self.shadow,
            self.region_strings,
            self.camera_strings,
            self.sound_strings,
        ))


def parse_counted_structure(data: bytes, magic: bytes) -> int | None:
    """解析 W3R/W3C/W3S 这类 magic/version/count 头。"""
    if len(data) < 12 or data[:4] != magic:
        return None
    count = struct.unpack_from("<i", data, 8)[0]
    if count < 0 or count > _MAX_COUNT:
        return None
    return count


def parse_structure_strings(data: bytes, magic: bytes) -> tuple[str, ...]:
    """从 W3R/W3C/W3S 结构文件中提取可读的零结尾字符串。"""
    if parse_counted_structure(data, magic) is None:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for chunk in data[12:].split(b"\x00"):
        text = _decode_readable_chunk(chunk)
        if text is None or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= _MAX_STRINGS:
            break
    return tuple(out)


def parse_wpm_summary(data: bytes) -> PathingSummary | None:
    """解析 war3map.wpm 路径图尺寸与 pathing flag 统计。"""
    if len(data) < 16 or data[:4] != b"MP3W":
        return None
    width, height = struct.unpack_from("<ii", data, 8)
    if width <= 0 or height <= 0 or width > _MAX_COUNT or height > _MAX_COUNT:
        return None
    cells = width * height
    end = 16 + cells
    if len(data) < end:
        return None
    payload = data[16:end]
    # 单遍统计字节值再按位聚合；逐 flag 的生成器扫描要过 payload 六次。
    byte_counts = Counter(payload)

    def _flag_total(flag: int) -> int:
        return sum(n for byte, n in byte_counts.items() if byte & flag)

    return PathingSummary(
        width=width,
        height=height,
        cells=cells,
        no_walk=_flag_total(0x02),
        no_fly=_flag_total(0x04),
        no_build=_flag_total(0x08),
        blight=_flag_total(0x20),
        no_water=_flag_total(0x40),
        unknown=_flag_total(0x80),
    )


def parse_shd_summary(data: bytes, pathing: PathingSummary | None = None) -> ShadowSummary | None:
    """解析 war3map.shd 阴影图，必要时用路径图尺寸校验。"""
    if not data:
        return None
    if pathing is not None and len(data) != pathing.cells:
        return None
    shadowed = data.count(0xFF)
    unshadowed = data.count(0x00)
    return ShadowSummary(
        width=pathing.width if pathing is not None else None,
        height=pathing.height if pathing is not None else None,
        cells=len(data),
        shadowed=shadowed,
        unshadowed=unshadowed,
        unknown=len(data) - shadowed - unshadowed,
    )


def build_map_structure_report(files: dict[str, bytes]) -> MapStructureReport:
    """从内部文件 payload 构建地图结构摘要。"""
    lowered = {name.lower(): data for name, data in files.items()}
    region_data = lowered.get("war3map.w3r", b"")
    camera_data = lowered.get("war3map.w3c", b"")
    sound_data = lowered.get("war3map.w3s", b"")
    pathing = parse_wpm_summary(lowered.get("war3map.wpm", b""))
    return MapStructureReport(
        regions=parse_counted_structure(region_data, b"W3R!"),
        cameras=parse_counted_structure(camera_data, b"W3C!"),
        sounds=parse_counted_structure(sound_data, b"W3S!"),
        pathing=pathing,
        shadow=parse_shd_summary(lowered.get("war3map.shd", b""), pathing),
        region_strings=parse_structure_strings(region_data, b"W3R!"),
        camera_strings=parse_structure_strings(camera_data, b"W3C!"),
        sound_strings=parse_structure_strings(sound_data, b"W3S!"),
    )


def _decode_readable_chunk(raw: bytes) -> str | None:
    chunk = raw.strip()
    if len(chunk) < _MIN_STRING_LEN:
        return None
    for start in range(min(len(chunk), 8)):
        for encoding in ("utf-8", "gb18030", "latin-1"):
            try:
                text = chunk[start:].decode(encoding).strip()
            except UnicodeDecodeError:
                continue
            if _is_readable_text(text) and not _looks_binary_prefixed(text):
                return text
    return None


def _is_readable_text(text: str) -> bool:
    if len(text) < _MIN_STRING_LEN:
        return False
    printable = sum(1 for char in text if char.isprintable())
    return printable == len(text)


def _looks_binary_prefixed(text: str) -> bool:
    return len(text) >= 2 and text[0].isascii() and not text[1].isascii()


def map_structure_report_from_map_path(path: str) -> MapStructureReport:
    """从地图 MPQ 中读取结构文件；读取失败时返回空报告。"""
    from .mpq import MPQArchive

    if not Path(path).is_file():
        return MapStructureReport()
    files: dict[str, bytes] = {}
    try:
        with MPQArchive(path) as archive:
            for name in STRUCTURE_FILES:
                if archive.has_file(name):
                    files[name] = archive.read_file(name)
    except (OSError, ValueError, KeyError, struct.error):
        return MapStructureReport()
    return build_map_structure_report(files)

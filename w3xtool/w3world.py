"""war3map world-editor metadata parsers: regions, cameras, and sounds."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .wts import resolve


@dataclass(frozen=True, slots=True)
class Region:
    left: float
    bottom: float
    right: float
    top: float
    name: str
    region_id: int
    weather_effect: str
    ambient_sound: str
    color_rgb: tuple[int, int, int]
    alpha: int


@dataclass(frozen=True, slots=True)
class Camera:
    target_x: float
    target_y: float
    offset_z: float
    rotation: float
    angle_of_attack: float
    distance: float
    roll: float
    field_of_view: float
    far_clip: float
    near_clip: float
    name: str
    local_pitch: float | None = None
    local_yaw: float | None = None
    local_roll: float | None = None


@dataclass(frozen=True, slots=True)
class Sound:
    name: str
    path: str
    eax_effect: str
    flags: int
    fade_in_rate: int
    fade_out_rate: int
    volume: int
    pitch: float
    channel: int
    min_distance: float
    max_distance: float
    cutoff_distance: float
    pitch_variance: float = 0.0
    priority: int = 0
    variable_name: str = ""

    @property
    def is_looping(self) -> bool:
        return bool(self.flags & 0x1)

    @property
    def is_3d(self) -> bool:
        return bool(self.flags & 0x2)

    @property
    def is_music(self) -> bool:
        return bool(self.flags & 0x8)

    @property
    def is_imported(self) -> bool:
        return bool(self.flags & 0x10)


class _Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0

    def i32(self) -> int:
        value = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return value

    def f32(self) -> float:
        value = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return value

    def u8(self) -> int:
        if self.p >= len(self.d):
            raise IndexError("u8 越界")
        value = self.d[self.p]
        self.p += 1
        return value

    def raw(self, size: int) -> bytes:
        if self.p + size > len(self.d):
            raise IndexError("raw 越界")
        value = self.d[self.p:self.p + size]
        self.p += size
        return value

    def cstr(self) -> str:
        end = self.d.find(b"\x00", self.p)
        if end < 0:
            raise IndexError("cstr 缺少终止符")
        raw = self.d[self.p:end]
        self.p = end + 1
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return raw.decode("gbk")
            except UnicodeDecodeError:
                return raw.decode("utf-8", "replace")


def parse_regions(data: bytes, wts: dict | None = None) -> list[Region]:
    wts = wts or {}
    try:
        reader = _Reader(data)
        if reader.i32() != 5:
            return []
        count = reader.i32()
        if count < 0 or count > len(data):
            return []
        regions: list[Region] = []
        for _ in range(count):
            left = reader.f32()
            bottom = reader.f32()
            right = reader.f32()
            top = reader.f32()
            name = str(resolve(reader.cstr(), wts))
            region_id = reader.i32()
            weather = reader.raw(4).decode("latin-1", "replace").rstrip("\x00")
            sound = str(resolve(reader.cstr(), wts))
            blue = reader.u8()
            green = reader.u8()
            red = reader.u8()
            alpha = reader.u8()
            regions.append(Region(left, bottom, right, top, name, region_id,
                                  weather, sound, (red, green, blue), alpha))
        return regions
    except (struct.error, IndexError):
        return []


def parse_cameras(data: bytes) -> list[Camera]:
    for include_local_rotation in (False, True):
        cameras = _parse_cameras_variant(data, include_local_rotation)
        if cameras is not None:
            return cameras
    return []


def _parse_cameras_variant(data: bytes, include_local_rotation: bool) -> list[Camera] | None:
    try:
        reader = _Reader(data)
        if reader.i32() != 0:
            return None
        count = reader.i32()
        if count < 0 or count > len(data):
            return None
        cameras: list[Camera] = []
        for _ in range(count):
            values = [reader.f32() for _ in range(10)]
            local_pitch = local_yaw = local_roll = None
            if include_local_rotation:
                local_pitch = reader.f32()
                local_yaw = reader.f32()
                local_roll = reader.f32()
            name = reader.cstr()
            cameras.append(Camera(*values, name, local_pitch, local_yaw, local_roll))
        return cameras if reader.p == len(data) else None
    except (struct.error, IndexError):
        return None


def parse_sounds(data: bytes) -> list[Sound]:
    try:
        reader = _Reader(data)
        version = reader.i32()
        count = reader.i32()
        if count < 0 or count > len(data):
            return []
    except (struct.error, IndexError):
        return []
    match version:
        case 1:
            return _parse_sound_records(reader, count, include_v3_tail=False)
        case 3:
            return _parse_sound_records(reader, count, include_v3_tail=True)
        case _:
            return []


def _parse_sound_records(reader: _Reader, count: int, include_v3_tail: bool) -> list[Sound]:
    sounds: list[Sound] = []
    for _ in range(count):
        try:
            sounds.append(_read_sound(reader, include_v3_tail))
        except (struct.error, IndexError):
            break
    return sounds


def _read_sound(reader: _Reader, include_v3_tail: bool) -> Sound:
    name = reader.cstr()
    path = reader.cstr()
    eax = reader.cstr()
    flags = reader.i32()
    fade_in = reader.i32()
    fade_out = reader.i32()
    volume = reader.i32()
    pitch = reader.f32()
    pitch_var = reader.f32() if include_v3_tail else 0.0
    priority = reader.i32() if include_v3_tail else 0
    if not include_v3_tail:
        reader.i32()
        reader.i32()
    channel = reader.i32()
    min_dist = reader.f32()
    max_dist = reader.f32()
    cutoff = reader.f32()
    for _ in range(6):
        reader.i32()
    variable = ""
    if include_v3_tail:
        variable = reader.cstr()
        reader.cstr()
        reader.cstr()
        reader.i32()
        reader.u8()
        reader.i32()
        reader.i32()
        reader.i32()
        reader.u8()
        reader.i32()
    return Sound(name, path, eax, flags, fade_in, fade_out, volume, pitch,
                 channel, min_dist, max_dist, cutoff, pitch_var, priority, variable)

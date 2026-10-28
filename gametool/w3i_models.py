"""Lossless evidence and compatibility models for map information."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

PLAYER_TYPES = {1: "用户", 2: "电脑", 3: "中立", 4: "可救援"}
RACES = {0: "可选", 1: "人族", 2: "兽族", 3: "不死", 4: "暗夜", 5: "中立"}

type FieldValue = int | float | str | tuple[int, ...] | tuple[float, ...]


class W3iDiagnosticCode(StrEnum):
    """Conditions that prevent an unqualified complete interpretation."""

    UNSUPPORTED_VERSION = "unsupported_version"
    TRUNCATED = "truncated"
    INVALID_COUNT = "invalid_count"
    INVALID_VALUE = "invalid_value"
    UNKNOWN_VALUE = "unknown_value"
    LOSSY_STRING = "lossy_string"
    TRAILING_DATA = "trailing_data"


@dataclass(frozen=True, slots=True)
class W3iDiagnostic:
    code: W3iDiagnosticCode
    field: str
    offset: int
    message: str


@dataclass(frozen=True, slots=True)
class W3iField:
    """One confirmed field; strings retain their pre-WTS value and exact bytes."""

    name: str
    offset: int
    value: FieldValue
    raw: bytes

    @property
    def end_offset(self) -> int:
        return self.offset + len(self.raw)


@dataclass  # MUTABLE_OK, SLOTS_OK: legacy mutable compatibility model.
class Player:
    id: int
    type: int
    race: int
    fixed_start: int
    name: str
    start_x: float | None = 0.0
    start_y: float | None = 0.0
    ally_low_priority_flags: int = 0
    ally_high_priority_flags: int = 0
    enemy_low_priority_flags: int | None = None
    enemy_high_priority_flags: int | None = None
    race_hud: int | None = None
    offset: int | None = None
    end_offset: int | None = None

    @property
    def type_name(self) -> str:
        return PLAYER_TYPES.get(self.type, str(self.type))

    @property
    def race_name(self) -> str:
        return RACES.get(self.race, str(self.race))


@dataclass  # MUTABLE_OK, SLOTS_OK: legacy mutable compatibility model.
class Force:
    name: str
    allied: bool = False
    allied_victory: bool = False
    share_vision: bool = False
    share_control: bool = False
    players: list[int] = field(default_factory=list)
    flags: int = 0
    player_mask: int = 0
    share_advanced_control: bool = False
    offset: int | None = None
    end_offset: int | None = None


@dataclass(frozen=True, slots=True)
class UpgradeAvailability:
    player_mask: int
    object_id: str
    level: int
    availability: int
    offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class TechAvailability:
    player_mask: int
    object_id: str
    offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class RandomUnitRow:
    chance: int
    object_ids: tuple[str, ...]
    offset: int
    end_offset: int


@dataclass(slots=True)  # MUTABLE_OK: retain confirmed prefixes of partial tables.
class RandomUnitTable:
    index: int
    name: str
    offset: int
    column_types: list[int] = field(default_factory=list)
    rows: list[RandomUnitRow] = field(default_factory=list)
    complete: bool = False
    end_offset: int | None = None


@dataclass(frozen=True, slots=True)
class RandomItem:
    chance: int
    object_id: str
    offset: int
    end_offset: int


@dataclass(slots=True)  # MUTABLE_OK: retain confirmed items of partial sets.
class RandomItemSet:
    offset: int
    items: list[RandomItem] = field(default_factory=list)
    complete: bool = False
    end_offset: int | None = None


@dataclass(slots=True)  # MUTABLE_OK: retain confirmed sets of partial tables.
class RandomItemTable:
    index: int
    name: str
    offset: int
    sets: list[RandomItemSet] = field(default_factory=list)
    complete: bool = False
    end_offset: int | None = None


@dataclass  # MUTABLE_OK, SLOTS_OK: mutable extraction builder compatibility model.
class W3iInfo:
    # Keep all original constructor positions before the new metadata fields.
    version: int = 0
    map_name: str = ""
    author: str = ""
    description: str = ""
    recommended_players: str = ""
    width: int = 0
    height: int = 0
    script_type: str = ""  # JASS/Lua/unknown; empty means no declaration in format.
    disable_preview: bool = False
    custom_ally: bool = False
    melee: bool = False
    large_map: bool = False
    custom_forces: bool = False
    custom_techtree: bool = False
    custom_ability: bool = False
    custom_upgrade: bool = False
    players: list[Player] = field(default_factory=list)
    forces: list[Force] = field(default_factory=list)
    parse_issue: str = ""
    camera_bounds: tuple[float, ...] = ()
    camera_margins: tuple[int, ...] = ()
    map_version: int | None = None
    editor_version: int | None = None
    game_version: tuple[int, ...] = ()
    flags: int | None = None
    tileset: str | None = None
    loading_screen_background: int | None = None
    race_hud: int | None = None
    loading_screen_path: str | None = None
    loading_screen_text: str | None = None
    loading_screen_title: str | None = None
    loading_screen_subtitle: str | None = None
    game_data_set: int | None = None
    prologue_screen_background: int | None = None
    prologue_screen_path: str | None = None
    prologue_screen_text: str | None = None
    prologue_screen_title: str | None = None
    prologue_screen_subtitle: str | None = None
    fog_style: int | None = None
    fog_start: float | None = None
    fog_end: float | None = None
    fog_density: float | None = None
    fog_color_bgra: tuple[int, ...] = ()
    fog_height_start: float | None = None
    fog_height_end: float | None = None
    fog_linear_start: float | None = None
    fog_linear_end: float | None = None
    fog_max_opacity: float | None = None
    fog_draw_over_sky: int | None = None
    weather_id: str | None = None
    sound_environment: str | None = None
    light_environment: str | None = None
    water_color_bgra: tuple[int, ...] = ()
    script_language_raw: int | None = None
    supported_modes: int | None = None
    game_data_version: int | None = None
    default_camera_zoom: int | None = None
    max_camera_zoom: int | None = None
    min_camera_zoom: int | None = None
    hd_water_min_opacity: int | None = None
    hd_water_max_opacity: int | None = None
    hd_water_reflectivity: int | None = None
    hd_water_emissivity: int | None = None
    hd_water_edge_softness: int | None = None
    hd_water_wave_displacement: int | None = None
    hd_water_wave_normal_strength: int | None = None
    hd_water_color_bgra: tuple[int, ...] = ()
    hd_water_envmap_reflectivity: int | None = None
    alpha_tile_minimap_color_bgra: tuple[int, ...] = ()
    upgrades: list[UpgradeAvailability] = field(default_factory=list)
    techs: list[TechAvailability] = field(default_factory=list)
    random_unit_tables: list[RandomUnitTable] = field(default_factory=list)
    random_item_tables: list[RandomItemTable] = field(default_factory=list)
    legacy_tail_reserved: int | None = None
    optional_data_skipped: bool = False
    fields: list[W3iField] = field(default_factory=list)
    diagnostics: list[W3iDiagnostic] = field(default_factory=list)
    header_complete: bool = False
    tables_complete: bool = False
    complete: bool = False
    consumed_bytes: int = 0
    unconsumed_data: bytes = b""

"""Read proven W3I layouts without discarding raw or incomplete evidence.

Layout reference: War3Net reader AND writer at commit
5f6f7bac26ed7ce7d0db83ceb4fb9ce59f918ff8, including the Info/Common record readers:
https://github.com/Drake53/War3Net/blob/5f6f7bac26ed7ce7d0db83ceb4fb9ce59f918ff8/src/War3Net.Build.Core/Serialization/Binary/Info/MapInfo.cs

Only explicitly verified versions are accepted. Every consumed byte belongs to
a field with its original bytes and offset; all remaining bytes are retained.
"""

from __future__ import annotations

from collections.abc import Mapping

from .w3f import CampaignMapEntry, W3fDiagnostic, W3fInfo, parse_w3f
from .w3i_evidence import w3i_info_to_dict
from .w3i_models import (
    PLAYER_TYPES,
    RACES,
    Force,
    Player,
    RandomItem,
    RandomItemSet,
    RandomItemTable,
    RandomUnitRow,
    RandomUnitTable,
    TechAvailability,
    UpgradeAvailability,
    W3iDiagnostic,
    W3iDiagnosticCode,
    W3iField,
    W3iInfo,
)
from .w3i_reader import W3iReadError, W3iReader

__all__ = [
    "CampaignMapEntry",
    "Force",
    "PLAYER_TYPES",
    "Player",
    "RACES",
    "RandomItem",
    "RandomItemSet",
    "RandomItemTable",
    "RandomUnitRow",
    "RandomUnitTable",
    "TechAvailability",
    "UpgradeAvailability",
    "W3fDiagnostic",
    "W3fInfo",
    "W3iDiagnostic",
    "W3iDiagnosticCode",
    "W3iField",
    "W3iInfo",
    "parse_w3f",
    "parse_w3i",
    "w3i_info_to_dict",
]

SUPPORTED_W3I_VERSIONS = frozenset((18, 23, 24, 25, 26, 27, 28, 31, 32, 33, 39))
_KNOWN_MAP_FLAGS = ((1 << 26) - 1) | (1 << 29) | (1 << 30)
_KNOWN_RACE_HUD_FLAGS = 0xCF


def parse_w3i(data: bytes, wts: Mapping[int, str] | None = None) -> W3iInfo | None:
    """Return confirmed metadata and complete diagnostics, including bad tails.

    ``complete`` means all encoded data was understood without diagnostics.
    A terminal FF is a documented omitted-table marker: ``optional_data_skipped``
    is true, and ``tables_complete`` remains false rather than claiming no rows.
    """
    if len(data) < 4:
        return None
    info = W3iInfo()
    r = W3iReader(data, info, wts if wts is not None else {})
    info.version = r.i32("version")
    if info.version >= 28 or info.version not in SUPPORTED_W3I_VERSIONS:
        # A missing/corrupt declaration must not act like an old format that
        # never declared a language, allowing downstream WCT language guessing.
        info.script_type = "unknown"
    if info.version not in SUPPORTED_W3I_VERSIONS:
        r.problem(
            W3iDiagnosticCode.UNSUPPORTED_VERSION,
            "version",
            f"unverified W3I layout {info.version}; remaining bytes retained",
            offset=0,
        )
    else:
        try:
            _read_header(r, info)
            info.header_complete = True
            _read_players(r, info)
            _read_forces(r, info)
            _read_optional_tables(r, info)
            if r.remaining:
                r.problem(
                    W3iDiagnosticCode.TRAILING_DATA,
                    "unconsumed_data",
                    f"{r.remaining} bytes follow the verified layout",
                )
        except W3iReadError:
            pass  # The failed bounded read already recorded its exact boundary.
    info.consumed_bytes = r.position
    info.unconsumed_data = data[r.position :]
    info.complete = not info.diagnostics and not info.unconsumed_data
    info.parse_issue = "; ".join(
        f"{diagnostic.code} W3I {diagnostic.field} at byte {diagnostic.offset}: "
        f"{diagnostic.message}"
        for diagnostic in info.diagnostics
    )
    return info


def _read_header(r: W3iReader, info: W3iInfo) -> None:
    info.map_version = r.i32("map_version")
    info.editor_version = r.i32("editor_version")
    if info.version >= 27:
        offset = r.position
        info.game_version = r.ints("game_version", 4)
        if any(value < 0 for value in info.game_version):
            r.problem(
                W3iDiagnosticCode.INVALID_VALUE,
                "game_version",
                "negative game-version component; original values retained",
                offset=offset,
            )
    info.map_name = r.text("map_name")
    info.author = r.text("author")
    info.description = r.text("description")
    info.recommended_players = r.text("recommended_players")
    info.camera_bounds = r.floats("camera_bounds", 8)
    info.camera_margins = r.ints("camera_margins", 4)
    info.width = _dimension(r, "width")
    info.height = _dimension(r, "height")
    flags = r.flags("flags", _KNOWN_MAP_FLAGS)
    info.flags = flags
    info.disable_preview = bool(flags & 0x1)
    info.custom_ally = bool(flags & 0x2)
    info.melee = bool(flags & 0x4)
    info.large_map = bool(flags & 0x8)
    info.custom_forces = bool(flags & 0x40)
    info.custom_techtree = bool(flags & 0x80)
    info.custom_ability = bool(flags & 0x100)
    info.custom_upgrade = bool(flags & 0x200)
    info.tileset = r.code("tileset", 1)
    info.loading_screen_background = r.i32("loading_screen_background")
    if info.version >= 39:
        info.race_hud = r.flags("race_hud", _KNOWN_RACE_HUD_FLAGS)
    if info.version >= 23:
        info.loading_screen_path = r.text("loading_screen_path", display=False)
    info.loading_screen_text = r.text("loading_screen_text")
    info.loading_screen_title = r.text("loading_screen_title")
    info.loading_screen_subtitle = r.text("loading_screen_subtitle")
    if info.version >= 23:
        info.game_data_set = r.enum("game_data_set", (-1, 0, 1, 2))
        info.prologue_screen_path = r.text("prologue_screen_path", display=False)
    else:
        info.prologue_screen_background = r.i32("prologue_screen_background")
    info.prologue_screen_text = r.text("prologue_screen_text")
    info.prologue_screen_title = r.text("prologue_screen_title")
    info.prologue_screen_subtitle = r.text("prologue_screen_subtitle")
    if info.version >= 23:
        _read_environment(r, info)
    if info.version >= 28:
        info.script_language_raw = r.enum("script_language_raw", (0, 1))
        info.script_type = {0: "JASS", 1: "Lua"}.get(
            info.script_language_raw, "unknown"
        )
    if info.version >= 31:
        info.supported_modes = r.flags("supported_modes", 7)
        info.game_data_version = r.enum("game_data_version", (0, 1, 2))
    if info.version >= 32:
        info.default_camera_zoom = r.i32("default_camera_zoom")
        info.max_camera_zoom = r.i32("max_camera_zoom")
    if info.version >= 33:
        info.min_camera_zoom = r.i32("min_camera_zoom")
    if info.version >= 39:
        _read_hd_water(r, info)


def _dimension(r: W3iReader, name: str) -> int:
    offset = r.position
    value = r.i32(name)
    if value <= 0:
        r.problem(
            W3iDiagnosticCode.INVALID_VALUE,
            name,
            f"non-positive map dimension {value}; raw evidence retained",
            offset=offset,
        )
        return 0
    return value


def _read_environment(r: W3iReader, info: W3iInfo) -> None:
    info.fog_style = r.enum("fog_style", (0, 1, 2))
    info.fog_start = r.f32("fog_start")
    info.fog_end = r.f32("fog_end")
    info.fog_density = r.f32("fog_density")
    info.fog_color_bgra = r.octets("fog_color_bgra", 4)
    if info.version >= 39:
        info.fog_height_start = r.f32("fog_height_start")
        info.fog_height_end = r.f32("fog_height_end")
        info.fog_linear_start = r.f32("fog_linear_start")
        info.fog_linear_end = r.f32("fog_linear_end")
        info.fog_max_opacity = r.f32("fog_max_opacity")
        info.fog_draw_over_sky = r.enum("fog_draw_over_sky", (0, 1))
    if info.version >= 25:
        info.weather_id = r.code("weather_id")
    info.sound_environment = r.text("sound_environment", display=False)
    info.light_environment = r.code("light_environment", 1)
    info.water_color_bgra = r.octets("water_color_bgra", 4)


def _read_hd_water(r: W3iReader, info: W3iInfo) -> None:
    info.hd_water_min_opacity = r.i32("hd_water_min_opacity")
    info.hd_water_max_opacity = r.i32("hd_water_max_opacity")
    info.hd_water_reflectivity = r.i32("hd_water_reflectivity")
    info.hd_water_emissivity = r.i32("hd_water_emissivity")
    info.hd_water_edge_softness = r.i32("hd_water_edge_softness")
    info.hd_water_wave_displacement = r.i32("hd_water_wave_displacement")
    info.hd_water_wave_normal_strength = r.i32("hd_water_wave_normal_strength")
    info.hd_water_color_bgra = r.octets("hd_water_color_bgra", 4)
    info.hd_water_envmap_reflectivity = r.i32("hd_water_envmap_reflectivity")
    info.alpha_tile_minimap_color_bgra = r.octets("alpha_tile_minimap_color_bgra", 4)


def _read_players(r: W3iReader, info: W3iInfo) -> None:
    minimum = 33 + (8 if info.version >= 31 else 0) + (4 if info.version >= 39 else 0)
    for index in range(r.count("players.count", minimum)):
        offset = r.position
        path = f"players[{index}]"
        pid = r.i32(f"{path}.id")
        controller = r.enum(f"{path}.type", (0, 1, 2, 3, 4))
        race = r.enum(f"{path}.race", (0, 1, 2, 3, 4, 5))
        race_hud = (
            r.flags(f"{path}.race_hud", _KNOWN_RACE_HUD_FLAGS)
            if info.version >= 39
            else None
        )
        flags = r.flags(f"{path}.fixed_start", 3)
        name = r.text(f"{path}.name")
        sx = r.f32(f"{path}.start_x")
        sy = r.f32(f"{path}.start_y")
        ally_low = r.u32(f"{path}.ally_low_priority_flags")
        ally_high = r.u32(f"{path}.ally_high_priority_flags")
        enemy_low = enemy_high = None
        if info.version >= 31:
            enemy_low = r.u32(f"{path}.enemy_low_priority_flags")
            enemy_high = r.u32(f"{path}.enemy_high_priority_flags")
        info.players.append(
            Player(
                pid,
                controller,
                race,
                flags,
                name,
                sx,
                sy,
                ally_low,
                ally_high,
                enemy_low,
                enemy_high,
                race_hud,
                offset,
                r.position,
            )
        )


def _read_forces(r: W3iReader, info: W3iInfo) -> None:
    for index in range(r.count("forces.count", 9)):
        offset = r.position
        path = f"forces[{index}]"
        flags = r.flags(f"{path}.flags", 0x3F)
        mask = r.u32(f"{path}.player_mask")
        name = r.text(f"{path}.name")
        info.forces.append(
            Force(
                name=name,
                allied=bool(flags & 0x1),
                allied_victory=bool(flags & 0x2),
                share_vision=bool(flags & 0x8),
                share_control=bool(flags & 0x10),
                players=[bit + 1 for bit in range(32) if mask & (1 << bit)],
                flags=flags,
                player_mask=mask,
                share_advanced_control=bool(flags & 0x20),
                offset=offset,
                end_offset=r.position,
            )
        )


def _read_optional_tables(r: W3iReader, info: W3iInfo) -> None:
    # The reference writer emits FF as the entire omitted-data tail. Match that
    # whole marker, so a real upgrade count of 255 cannot erase its records.
    if r.remaining == 1 and r.data[r.position] == 0xFF:
        r.octets("optional_data_marker", 1)
        info.optional_data_skipped = True
        return
    for index in range(r.count("upgrades.count", 16)):
        offset = r.position
        path = f"upgrades[{index}]"
        mask = r.u32(f"{path}.player_mask")
        code = r.code(f"{path}.object_id")
        level = r.i32(f"{path}.level")
        availability = r.enum(f"{path}.availability", (0, 1, 2))
        info.upgrades.append(
            UpgradeAvailability(mask, code, level, availability, offset, r.position)
        )
    for index in range(r.count("techs.count", 8)):
        offset = r.position
        path = f"techs[{index}]"
        mask = r.u32(f"{path}.player_mask")
        code = r.code(f"{path}.object_id")
        info.techs.append(TechAvailability(mask, code, offset, r.position))
    _read_random_units(r, info)
    if info.version >= 24:
        _read_random_items(r, info)
    if info.version in (26, 27):
        offset = r.position
        info.legacy_tail_reserved = r.i32("legacy_tail_reserved")
        if info.legacy_tail_reserved != 0:
            r.problem(
                W3iDiagnosticCode.UNKNOWN_VALUE,
                "legacy_tail_reserved",
                f"expected zero reserved field, found {info.legacy_tail_reserved}",
                offset=offset,
            )
    info.tables_complete = True


def _read_random_units(r: W3iReader, info: W3iInfo) -> None:
    for index in range(r.count("random_unit_tables.count", 13)):
        offset = r.position
        path = f"random_unit_tables[{index}]"
        number = r.i32(f"{path}.index")
        name = r.text(f"{path}.name")
        table = RandomUnitTable(number, name, offset)
        info.random_unit_tables.append(table)
        columns = r.count(f"{path}.columns.count", 4)
        for column in range(columns):
            table.column_types.append(r.i32(f"{path}.columns[{column}]"))
        for row in range(r.count(f"{path}.rows.count", 4 + 4 * columns)):
            row_offset = r.position
            chance = r.i32(f"{path}.rows[{row}].chance")
            codes = tuple(
                r.code(f"{path}.rows[{row}].object_ids[{column}]")
                for column in range(columns)
            )
            table.rows.append(RandomUnitRow(chance, codes, row_offset, r.position))
        table.complete = True
        table.end_offset = r.position


def _read_random_items(r: W3iReader, info: W3iInfo) -> None:
    for index in range(r.count("random_item_tables.count", 9)):
        offset = r.position
        path = f"random_item_tables[{index}]"
        number = r.i32(f"{path}.index")
        name = r.text(f"{path}.name")
        table = RandomItemTable(number, name, offset)
        info.random_item_tables.append(table)
        for group in range(r.count(f"{path}.sets.count", 4)):
            item_set = RandomItemSet(r.position)
            table.sets.append(item_set)
            set_path = f"{path}.sets[{group}]"
            for item in range(r.count(f"{set_path}.items.count", 8)):
                item_offset = r.position
                chance = r.i32(f"{set_path}.items[{item}].chance")
                code = r.code(f"{set_path}.items[{item}].object_id")
                item_set.items.append(RandomItem(chance, code, item_offset, r.position))
            item_set.complete = True
            item_set.end_offset = r.position
        table.complete = True
        table.end_offset = r.position

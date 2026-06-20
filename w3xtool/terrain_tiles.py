"""Readable terrain tile metadata for W3E tile ids."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from .westrings import WESTRINGS

_TILE_PATH_DATA: Final = (
    "Adrt=TerrainArt\\Ashenvale\\Ashen_Dirt.blp;Adrd=TerrainArt\\Ashenvale\\Ashen_DirtRough.blp;"
    "Agrs=TerrainArt\\Ashenvale\\Ashen_Grass.blp;Arck=TerrainArt\\Ashenvale\\Ashen_Rcok.blp;"
    "Agrd=TerrainArt\\Ashenvale\\Ashen_GrassLumpy.blp;Avin=TerrainArt\\Ashenvale\\Ashen_Vines.blp;"
    "Adrg=TerrainArt\\Ashenvale\\Ashen_DirtGrass.blp;Alvd=TerrainArt\\Ashenvale\\Ashen_Leaves.blp;"
    "Bdrt=TerrainArt\\Barrens\\Barrens_Dirt.blp;Bdrh=TerrainArt\\Barrens\\Barrens_DirtRough.blp;"
    "Bdrr=TerrainArt\\Barrens\\Barrens_Pebbles.blp;Bdrg=TerrainArt\\Barrens\\Barrens_DirtGrass.blp;"
    "Bdsr=TerrainArt\\Barrens\\Barrens_Desert.blp;Bdsd=TerrainArt\\Barrens\\Barrens_DesertDark.blp;"
    "Bflr=TerrainArt\\Barrens\\Barrens_Rock.blp;Bgrr=TerrainArt\\Barrens\\Barrens_Grass.blp;"
    "Ydrt=TerrainArt\\Cityscape\\City_Dirt.blp;Ydtr=TerrainArt\\Cityscape\\City_DirtRough.blp;"
    "Yblm=TerrainArt\\Cityscape\\City_BlackMarble.blp;Ybtl=TerrainArt\\Cityscape\\City_BrickTiles.blp;"
    "Ysqd=TerrainArt\\Cityscape\\City_SquareTiles.blp;Yrtl=TerrainArt\\Cityscape\\City_RoundTiles.blp;"
    "Ygsb=TerrainArt\\Cityscape\\City_Grass.blp;Yhdg=TerrainArt\\Cityscape\\City_GrassTrim.blp;"
    "Ywmb=TerrainArt\\Cityscape\\City_WhiteMarble.blp;Xdrt=TerrainArt\\Dalaran\\Dalaran_Dirt.blp;"
    "Xdtr=TerrainArt\\Dalaran\\Dalaran_DirtRough.blp;Xblm=TerrainArt\\Dalaran\\Dalaran_BlackMarble.blp;"
    "Xbtl=TerrainArt\\Dalaran\\Dalaran_BrickTiles.blp;Xsqd=TerrainArt\\Dalaran\\Dalaran_SquareTiles.blp;"
    "Xrtl=TerrainArt\\Dalaran\\Dalaran_RoundTiles.blp;Xgsb=TerrainArt\\Dalaran\\Dalaran_Grass.blp;"
    "Xhdg=TerrainArt\\Dalaran\\Dalaran_GrassTrim.blp;Xwmb=TerrainArt\\Dalaran\\Dalaran_WhiteMarble.blp;"
    "Ddrt=TerrainArt\\Dungeon\\Cave_Dirt.blp;Dbrk=TerrainArt\\Dungeon\\Cave_Brick.blp;"
    "Drds=TerrainArt\\Dungeon\\Cave_RedStones.blp;Dlvc=TerrainArt\\Dungeon\\Cave_LavaCracks.blp;"
    "Dlav=TerrainArt\\Dungeon\\Cave_Lava.blp;Ddkr=TerrainArt\\Dungeon\\Cave_DarkRocks.blp;"
    "Dgrs=TerrainArt\\Dungeon\\Cave_GreyStones.blp;Dsqd=TerrainArt\\Dungeon\\Cave_SquareTiles.blp;"
    "Fdrt=TerrainArt\\LordaeronFall\\Lordf_Dirt.blp;Fdro=TerrainArt\\LordaeronFall\\Lordf_DirtRough.blp;"
    "Fdrg=TerrainArt\\LordaeronFall\\Lordf_DirtGrass.blp;Frok=TerrainArt\\LordaeronFall\\Lordf_Rock.blp;"
    "Fgrs=TerrainArt\\LordaeronFall\\Lordf_Grass.blp;Fgrd=TerrainArt\\LordaeronFall\\Lordf_GrassDark.blp;"
    "Ldrt=TerrainArt\\LordaeronSummer\\Lords_Dirt.blp;Ldro=TerrainArt\\LordaeronSummer\\Lords_DirtRough.blp;"
    "Ldrg=TerrainArt\\LordaeronSummer\\Lords_DirtGrass.blp;Lrok=TerrainArt\\LordaeronSummer\\Lords_Rock.blp;"
    "Lgrs=TerrainArt\\LordaeronSummer\\Lords_Grass.blp;Lgrd=TerrainArt\\LordaeronSummer\\Lords_GrassDark.blp;"
    "Wdrt=TerrainArt\\LordaeronWinter\\Lordw_Dirt.blp;Wdro=TerrainArt\\LordaeronWinter\\Lordw_DirtRough.blp;"
    "Wsng=TerrainArt\\LordaeronWinter\\Lordw_SnowGrass.blp;Wrok=TerrainArt\\LordaeronWinter\\Lordw_Rock.blp;"
    "Wgrs=TerrainArt\\LordaeronWinter\\Lordw_Grass.blp;Wsnw=TerrainArt\\LordaeronWinter\\Lordw_Snow.blp;"
    "Ndrt=TerrainArt\\Northrend\\North_dirt.blp;Ndrd=TerrainArt\\Northrend\\North_dirtdark.blp;"
    "Nrck=TerrainArt\\Northrend\\North_rock.blp;Ngrs=TerrainArt\\Northrend\\North_Grass.blp;"
    "Nice=TerrainArt\\Northrend\\North_ice.blp;Nsnw=TerrainArt\\Northrend\\North_Snow.blp;"
    "Nsnr=TerrainArt\\Northrend\\North_SnowRock.blp;Vdrt=TerrainArt\\Village\\Village_Dirt.blp;"
    "Vdrr=TerrainArt\\Village\\Village_DirtRough.blp;Vcrp=TerrainArt\\Village\\Village_Crops.blp;"
    "Vcbp=TerrainArt\\Village\\Village_CobblePath.blp;Vstp=TerrainArt\\Village\\Village_StonePath.blp;"
    "Vgrs=TerrainArt\\Village\\Village_GrassShort.blp;Vrck=TerrainArt\\Village\\Village_Rocks.blp;"
    "Vgrt=TerrainArt\\Village\\Village_GrassThick.blp;Qdrt=TerrainArt\\VillageFall\\VillageFall_Dirt.blp;"
    "Qdrr=TerrainArt\\VillageFall\\VillageFall_DirtRough.blp;Qcrp=TerrainArt\\VillageFall\\VillageFall_Crops.blp;"
    "Qcbp=TerrainArt\\VillageFall\\VillageFall_CobblePath.blp;Qstp=TerrainArt\\VillageFall\\VillageFall_StonePath.blp;"
    "Qgrs=TerrainArt\\VillageFall\\VillageFall_GrassShort.blp;Qrck=TerrainArt\\VillageFall\\VillageFall_Rocks.blp;"
    "Qgrt=TerrainArt\\VillageFall\\VillageFall_GrassThick.blp;Gdrt=TerrainArt\\Dungeon2\\GDirt.blp;"
    "Gbrk=TerrainArt\\Dungeon2\\GBrick.blp;Grds=TerrainArt\\Dungeon2\\GRedStones.blp;"
    "Glvc=TerrainArt\\Dungeon2\\GLavaCracks.blp;Glav=TerrainArt\\Dungeon2\\GLava.blp;"
    "Gdkr=TerrainArt\\Dungeon2\\GDrakRocks.blp;Ggrs=TerrainArt\\Dungeon2\\GGreyStones.blp;"
    "Gsqd=TerrainArt\\Dungeon2\\GSquareTiles.blp;Cdrt=TerrainArt\\Felwood\\Felwood_Dirt.blp;"
    "Cdrd=TerrainArt\\Felwood\\Felwood_DirtRough.blp;Cpos=TerrainArt\\Felwood\\Felwood_Poison.blp;"
    "Crck=TerrainArt\\Felwood\\Felwood_Rock.blp;Cvin=TerrainArt\\Felwood\\Felwood_Vines.blp;"
    "Cgrs=TerrainArt\\Felwood\\Felwood_Grass.blp;Clvg=TerrainArt\\Felwood\\Felwood_Leaves.blp;"
    "Jdrt=TerrainArt\\DalaranRuins\\DRuins_Dirt.blp;Jdtr=TerrainArt\\DalaranRuins\\DRuins_DirtRough.blp;"
    "Jblm=TerrainArt\\DalaranRuins\\DRuins_BlackMarble.blp;Jbtl=TerrainArt\\DalaranRuins\\DRuins_BrickTiles.blp;"
    "Jsqd=TerrainArt\\DalaranRuins\\DRuins_SquareTiles.blp;Jrtl=TerrainArt\\DalaranRuins\\DRuins_RoundTiles.blp;"
    "Jgsb=TerrainArt\\DalaranRuins\\DRuins_Grass.blp;Jhdg=TerrainArt\\DalaranRuins\\DRuins_GrassTrim.blp;"
    "Jwmb=TerrainArt\\DalaranRuins\\DRuins_WhiteMarble.blp;Kdrt=TerrainArt\\BlackCitadel\\Citadel_Dirt.blp;"
    "Kfsl=TerrainArt\\BlackCitadel\\Citadel_DirtLight.blp;Kdtr=TerrainArt\\BlackCitadel\\Citadel_RoughDirt.blp;"
    "Kfst=TerrainArt\\BlackCitadel\\Citadel_FlatStones.blp;Ksmb=TerrainArt\\BlackCitadel\\Citadel_SmallBricks.blp;"
    "Klgb=TerrainArt\\BlackCitadel\\Citadel_LargeBricks.blp;Ksqt=TerrainArt\\BlackCitadel\\Citadel_SquareTiles.blp;"
    "Kdkt=TerrainArt\\BlackCitadel\\Citadel_DarkTiles.blp;Idrt=TerrainArt\\Icecrown\\Ice_Dirt.blp;"
    "Idtr=TerrainArt\\Icecrown\\Ice_DirtRough.blp;Idki=TerrainArt\\Icecrown\\Ice_DarkIce.blp;"
    "Ibkb=TerrainArt\\Icecrown\\Ice_BlackBricks.blp;Irbk=TerrainArt\\Icecrown\\Ice_RuneBricks.blp;"
    "Itbk=TerrainArt\\Icecrown\\Ice_TiledBricks.blp;Iice=TerrainArt\\Icecrown\\Ice_Ice.blp;"
    "Ibsq=TerrainArt\\Icecrown\\Ice_BlackSquares.blp;Isnw=TerrainArt\\Icecrown\\Ice_Snow.blp;"
    "Odrt=TerrainArt\\Outland\\Outland_Dirt.blp;Odtr=TerrainArt\\Outland\\Outland_DirtLight.blp;"
    "Osmb=TerrainArt\\Outland\\Outland_RoughDirt.blp;Ofst=TerrainArt\\Outland\\Outland_DirtCracks.blp;"
    "Olgb=TerrainArt\\Outland\\Outland_FlatStones.blp;Orok=TerrainArt\\Outland\\Outland_Rock.blp;"
    "Ofsl=TerrainArt\\Outland\\Outland_FlatStonesLight.blp;Oaby=TerrainArt\\Outland\\Outland_Abyss.blp;"
    "Zdrt=TerrainArt\\Ruins\\Ruins_Dirt.blp;Zdtr=TerrainArt\\Ruins\\Ruins_DirtRough.blp;"
    "Zdrg=TerrainArt\\Ruins\\Ruins_DirtGrass.blp;Zbks=TerrainArt\\Ruins\\Ruins_SmallBricks.blp;"
    "Zsan=TerrainArt\\Ruins\\Ruins_Sand.blp;Zbkl=TerrainArt\\Ruins\\Ruins_LargeBricks.blp;"
    "Ztil=TerrainArt\\Ruins\\Ruins_RoundTiles.blp;Zgrs=TerrainArt\\Ruins\\Ruins_Grass.blp;"
    "Zvin=TerrainArt\\Ruins\\Ruins_GrassDark.blp;"
)
_SUMMARY_TILE_LIMIT: Final = 6


@dataclass(frozen=True, slots=True)
class TerrainTile:
    tile_id: str
    label: str
    path: str


def _parse_tile_path_data(data: str) -> dict[str, str]:
    paths: dict[str, str] = {}
    for item in data.split(";"):
        if not item:
            continue
        tile_id, path = item.split("=", 1)
        paths[tile_id] = path
    return paths


TERRAIN_TILE_PATHS: Final[Mapping[str, str]] = MappingProxyType(
    _parse_tile_path_data(_TILE_PATH_DATA),
)


def describe_terrain_tile(tile_id: str) -> TerrainTile:
    """Return localized editor label and texture path for a W3E tile id."""
    label = WESTRINGS.get(f"WESTRING_TERRAINTYPE_{tile_id}", tile_id)
    return TerrainTile(tile_id=tile_id, label=label, path=TERRAIN_TILE_PATHS.get(tile_id, ""))


def format_terrain_tile(tile_id: str) -> str:
    """Format a tile id for human-facing summaries."""
    tile = describe_terrain_tile(tile_id)
    if tile.path:
        return f"{tile.tile_id}({tile.label} · {tile.path})"
    if tile.label != tile.tile_id:
        return f"{tile.tile_id}({tile.label})"
    return tile.tile_id


def format_terrain_tile_list(tile_ids: tuple[str, ...]) -> str:
    """Format a bounded terrain tile list for CLI output."""
    shown = "、".join(format_terrain_tile(tile_id) for tile_id in tile_ids[:_SUMMARY_TILE_LIMIT])
    if len(tile_ids) <= _SUMMARY_TILE_LIMIT:
        return shown
    return f"{shown} …… 另有 {len(tile_ids) - _SUMMARY_TILE_LIMIT} 个"

"""Knowledge-pack resource bodies may use selected client icons as fallback."""

from __future__ import annotations

from pathlib import Path

from w3xtool.game_data_source import DirectoryDataSource
from w3xtool.knowledge_assets import export_resource_bodies
from w3xtool.knowledge_pack import write_knowledge_pack
from w3xtool.map_data import GameObject, MapData

_ICON = "ReplaceableTextures\\CommandButtons\\BTNClient.blp"
_CUSTOM_ICON = "UI\\CustomIcon.blp"


def test_referenced_client_icon_is_exported_with_explicit_source(tmp_path: Path) -> None:
    # Given: an object references an icon absent from the map but present in client data.
    client_root = tmp_path / "client"
    client_icon = client_root / "war3.w3mod" / "ReplaceableTextures" / "CommandButtons" / "BTNClient.blp"
    client_icon.parent.mkdir(parents=True)
    client_icon.write_bytes(b"BLP1client")
    md = _map_with_icon(tmp_path / "missing.w3x")
    output = tmp_path / "pack"

    # When: the full knowledge pack uses the selected game-data path.
    write_knowledge_pack(md, str(output), game_data_path=str(client_root))

    # Then: the body and manifest identify the external source honestly.
    body = output / "资源" / "素材文件" / "replaceabletextures" / "commandbuttons" / "btnclient.blp"
    assert body.read_bytes() == b"BLP1client"
    manifest = (output / "资源" / "素材文件_manifest.tsv").read_text(encoding="utf-8")
    assert "已导出\t客户端数据" in manifest


def test_map_body_wins_over_same_named_client_icon(tmp_path: Path) -> None:
    # Given: both the map directory and client data expose the referenced icon.
    map_root = tmp_path / "map"
    map_icon = map_root / "ReplaceableTextures" / "CommandButtons" / "BTNClient.blp"
    map_icon.parent.mkdir(parents=True)
    map_icon.write_bytes(b"BLP1map")
    client_root = tmp_path / "client"
    client_icon = client_root / "ReplaceableTextures" / "CommandButtons" / "BTNClient.blp"
    client_icon.parent.mkdir(parents=True)
    client_icon.write_bytes(b"BLP1client")
    md = _map_with_icon(map_root)
    client_source = DirectoryDataSource(str(client_root))

    # When: resource bodies are resolved against both sources.
    report = export_resource_bodies(
        md,
        str(tmp_path / "resources"),
        game_data_source=client_source,
    )

    # Then: map bytes and provenance win without consulting external content.
    exported = report.items[0]
    assert exported.status == "已导出"
    assert exported.source == "地图数据"
    assert Path(tmp_path / "resources" / exported.exported_path).read_bytes() == b"BLP1map"


def test_nonstandard_object_icon_path_can_fall_back_to_client_data(tmp_path: Path) -> None:
    # Given: the object icon is authoritative even without a BTN filename convention.
    client_root = tmp_path / "client"
    client_icon = client_root / "UI" / "CustomIcon.blp"
    client_icon.parent.mkdir(parents=True)
    client_icon.write_bytes(b"BLP1custom")
    md = _map_with_icon(tmp_path / "missing.w3x", icon=_CUSTOM_ICON)
    client_source = DirectoryDataSource(str(client_root))

    # When: the referenced icon body is exported.
    report = export_resource_bodies(
        md,
        str(tmp_path / "resources"),
        game_data_source=client_source,
    )

    # Then: object provenance enables fallback regardless of path naming heuristics.
    exported = report.items[0]
    assert exported.status == "已导出"
    assert exported.source == "客户端数据"
    assert Path(tmp_path / "resources" / exported.exported_path).read_bytes() == b"BLP1custom"


def _map_with_icon(path: Path, *, icon: str = _ICON) -> MapData:
    obj = GameObject("单位", "w3u", "H001", "hX01", "Client unit", True, icon=icon)
    md = MapData(path=str(path), name="client icon map", objects={"单位": [obj]})
    md.obj_index = {obj.obj_id: obj}
    return md

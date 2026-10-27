"""Live auto-packs reuse only complete, source-bound, unchanged generations."""

import os
from pathlib import Path

import pytest

from gametool import live_cli
from gametool.extraction_profile import (
    ExtractionProfile,
    profile_config_path,
    save_profile,
)
from gametool.knowledge_results import KnowledgeWriteItem, KnowledgeWriteReport
from gametool.load_context import MapLoadContext
from gametool.map_data import GameObject, MapData


@pytest.fixture
def cache_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GAMEXRAY_CACHE_DIR", str(tmp_path / "private-cache"))
    monkeypatch.setattr(
        "gametool.load_context.build_map_load_context", lambda: MapLoadContext()
    )
    monkeypatch.setattr(
        "gametool.knowledge_pack_contents.discover_game_data_path", lambda: None
    )
    source = tmp_path / "source.w3x"
    archive = Path(__file__).parent / "fixtures/reference/stormlib-slk-map.w3x"
    source.write_bytes(archive.read_bytes() + b"cache-identity-padding-0")
    loaded: list[MapData] = []

    def load_map(path: str, **_kwargs):
        obj = GameObject("单位", "w3u", "H001", "hfoo", "Fixture unit", True)
        result = MapData(path=path, name="Fixture map", objects={"单位": [obj]})
        result.obj_index = {"H001": obj}
        loaded.append(result)
        return result

    monkeypatch.setattr("gametool.api.load_map", load_map)
    return source, loaded


def test_existing_single_field_file_is_not_a_complete_live_cache(cache_fixture):
    source, loaded = cache_fixture
    old = live_cli.live_pack_cache_dir(str(source))
    old.mkdir(parents=True)
    evidence = old / "对象字段.tsv"
    evidence.write_bytes(b"partial previous write")

    actual = Path(
        live_cli._ensure_pack_dir(live_cli.LiveCliOptions(map_path=str(source)))
    )

    assert actual != old
    assert evidence.read_bytes() == b"partial previous write"
    assert "字段键" in (actual / "对象字段.tsv").read_text(encoding="utf-8")
    assert len(loaded) == 1 and loaded[0]._closed


def test_partial_publication_never_becomes_ready_or_reusable(
    cache_fixture, monkeypatch: pytest.MonkeyPatch, capsys
):
    source, loaded = cache_fixture
    attempts: list[Path] = []

    def partial_write(_md, directory: str, **_kwargs):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        (root / "对象字段.tsv").write_bytes(b"partial")
        attempts.append(root)
        return KnowledgeWriteReport(
            (
                KnowledgeWriteItem("对象字段.tsv", True, 7, None),
                KnowledgeWriteItem("对象ID/单位.tsv", False, 0, "fixture disk full"),
            )
        )

    monkeypatch.setattr(
        "gametool.knowledge_pack.write_knowledge_pack_report", partial_write
    )
    options = live_cli.LiveCliOptions(map_path=str(source))

    with pytest.raises(live_cli.LiveCliOptionError, match="fixture disk full"):
        live_cli._ensure_pack_dir(options)
    with pytest.raises(live_cli.LiveCliOptionError, match="fixture disk full"):
        live_cli._ensure_pack_dir(options)

    assert len(attempts) == 2 and attempts[0] != attempts[1]
    assert all((root / "对象字段.tsv").read_bytes() == b"partial" for root in attempts)
    assert len(loaded) == 2 and all(md._closed for md in loaded)
    assert "知识包就绪" not in capsys.readouterr().out


def test_reuse_verifies_every_published_file_and_retains_tampered_generation(
    cache_fixture,
):
    source, loaded = cache_fixture
    options = live_cli.LiveCliOptions(map_path=str(source))
    first = Path(live_cli._ensure_pack_dir(options))
    assert Path(live_cli._ensure_pack_dir(options)) == first
    assert len(loaded) == 1
    damaged = first / "对象ID" / "单位.tsv"
    original = damaged.read_bytes()
    damaged.write_bytes(b"!" * len(original))

    second = Path(live_cli._ensure_pack_dir(options))

    assert second != first
    assert damaged.read_bytes() == b"!" * len(original)
    assert "Fixture unit" in (second / "对象ID" / "单位.tsv").read_text(
        encoding="utf-8"
    )
    assert len(loaded) == 2 and all(md._closed for md in loaded)


def test_same_size_same_mtime_source_replacement_invalidates_live_cache(cache_fixture):
    source, loaded = cache_fixture
    options = live_cli.LiveCliOptions(map_path=str(source))
    first = Path(live_cli._ensure_pack_dir(options))
    previous = source.stat()
    source.write_bytes(source.read_bytes()[:-1] + b"1")
    os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))

    second = Path(live_cli._ensure_pack_dir(options))

    assert second != first
    assert len(loaded) == 2
    assert first.is_dir()


def test_campaign_live_cache_includes_every_child_pack(
    cache_fixture, monkeypatch: pytest.MonkeyPatch
):
    source, loaded = cache_fixture
    campaign = MapData(path=str(source), name="Campaign")
    campaign.sub_maps = [
        MapData(path=f"child-{index}.w3x", name=f"Mission {index}")
        for index in range(3)
    ]
    loaded.append(campaign)
    monkeypatch.setattr("gametool.api.load_map", lambda *_args, **_kwargs: campaign)

    result = Path(
        live_cli._ensure_pack_dir(live_cli.LiveCliOptions(map_path=str(source)))
    )

    assert len(list(result.glob("子地图/*/对象字段.tsv"))) == 3
    assert campaign._closed and all(md._closed for md in campaign.sub_maps)


def test_live_auto_pack_is_full_scope_without_changing_the_saved_profile(cache_fixture):
    source, _loaded = cache_fixture
    save_profile(ExtractionProfile({"objects": False, "units": False}))
    configuration = Path(profile_config_path())
    original = configuration.read_bytes(), configuration.stat().st_mtime_ns

    result = Path(
        live_cli._ensure_pack_dir(live_cli.LiveCliOptions(map_path=str(source)))
    )

    assert (result / "对象字段.tsv").is_file()
    assert (result / "对象ID/单位.tsv").is_file()
    assert (configuration.read_bytes(), configuration.stat().st_mtime_ns) == original


def test_source_change_during_export_keeps_incomplete_generation_for_diagnosis(
    cache_fixture, monkeypatch: pytest.MonkeyPatch
):
    from gametool import knowledge_pack

    source, loaded = cache_fixture
    original_write = knowledge_pack.write_knowledge_pack_report
    attempts = []

    def changing_write(md, directory, **kwargs):
        report = original_write(md, directory, **kwargs)
        attempts.append(Path(directory))
        source.write_bytes(source.read_bytes()[:-1] + b"1")
        return report

    monkeypatch.setattr(knowledge_pack, "write_knowledge_pack_report", changing_write)

    with pytest.raises(live_cli.LiveCliOptionError, match="地图文件在导出期间改变"):
        live_cli._ensure_pack_dir(live_cli.LiveCliOptions(map_path=str(source)))

    assert len(attempts) == 1 and attempts[0].is_dir()
    assert not (attempts[0] / ".gamexray-live-pack.json").exists()
    assert loaded[0]._closed

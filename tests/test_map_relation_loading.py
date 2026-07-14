"""Map loading publishes complete text and item relation indexes once."""

from pathlib import Path

from w3xtool.description_cache import (
    DescriptionCache,
    DescriptionCacheEntry,
    format_description_cache_tsv,
)
from w3xtool.gui_loader import LoadedMap, load_path_payload
from w3xtool.load_context import MapLoadContext
from w3xtool.map_data import MapData
from w3xtool.map_loader import _load_map_impl


class _Archive:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.path = "fixture.w3x"
        self._data = b""
        self._files = {
            self._normalize(name): (name, payload) for name, payload in files.items()
        }

    def has_file(self, name: str) -> bool:
        return self._normalize(name) in self._files

    def read_file(self, name: str) -> bytes:
        return self._files[self._normalize(name)][1]

    def list_files(self) -> list[str]:
        return [name for name, _payload in self._files.values()]

    def close(self) -> None:
        """Match the archive protocol; the in-memory fixture owns no resource."""

    @staticmethod
    def _normalize(name: str) -> str:
        return name.replace("/", "\\").casefold()


def test_map_loader_publishes_text_and_relation_indexes_before_return() -> None:
    # Given: one named map item has complete text and a fixed script placement.
    archive = _Archive(
        {
            "Units\\ItemStrings.txt": (
                b"[I001]\nName=Loaded Item\nTip=Loaded tip\nUbertip=Loaded full description\n"
            ),
            "war3map.j": b"call CreateItem('I001', 128.0, -64.0)\n",
        }
    )

    # When: the high-level map implementation finishes all components.
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: both immutable indexes are already available to every consumer.
    assert md.object_texts.for_object("物品", "I001")
    assert md.item_relations.for_item("I001")


def test_description_cache_path_reaches_gui_map_load_context(tmp_path: Path) -> None:
    # Given: a valid standalone trusted cache selected by the GUI loader.
    cache = DescriptionCache.build(
        (
            DescriptionCacheEntry(
                "物品",
                "ratf",
                "扩展提示",
                None,
                "缓存全文",
                "缓存全文",
                "a" * 64,
                "owned.tsv",
            ),
        )
    )
    cache_path = tmp_path / "可信描述缓存.tsv"
    cache_path.write_text(format_description_cache_tsv(cache), encoding="utf-8")
    captured: list[MapLoadContext | None] = []
    md = MapData("x.w3x", "缓存图")

    def load(path: str, *, load_context: MapLoadContext | None = None) -> MapData:
        assert path == "x.w3x"
        captured.append(load_context)
        return md

    def prepare(
        active: MapData,
        campaign_path: str | None,
        views: list[tuple[str, MapData]] | None,
        *,
        load_options: dict[str, bool] | None,
    ) -> LoadedMap:
        _ = load_options
        return LoadedMap(active, [], [], None, views, campaign_path)

    # When: a path payload is loaded with only the cache as optional context.
    load_path_payload(
        "x.w3x",
        load=load,
        prepare=prepare,
        game_data_path=str(tmp_path / "missing-client"),
        description_cache_path=str(cache_path),
    )

    # Then: the context is not optimized away and contains the selected evidence.
    assert captured[0] is not None
    assert captured[0].description_cache.lookup("物品", "ratf", "扩展提示", None)

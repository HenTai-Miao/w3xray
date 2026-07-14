"""Single-map batch extraction integration tests."""

from __future__ import annotations

import csv
import hashlib
import io
import struct
from collections.abc import Iterable
from contextlib import nullcontext
from pathlib import Path
from typing import ContextManager

import pytest

import w3xtool.batch_map_processing as batch_map_processing
from w3xtool.batch_map_processing import process_one_map
from w3xtool.batch_models import MapBatchState
from w3xtool.batch_runner import BatchOptions, fingerprint_source
from w3xtool.extraction_ledger import (
    BlockSource,
    BlockState,
    ExtractionEntry,
    build_extraction_ledger,
)
from w3xtool.icon_resources import AnonymousIconBlock
from w3xtool.load_context import MapLoadContext
from w3xtool.map_archive_reader import MapArchiveReader
from w3xtool.map_data import GameObject, MapData


def _one_pixel_blp() -> bytes:
    buffer = bytearray(20 + 128 + 1024)
    buffer[0:4] = b"BLP2"
    struct.pack_into("<I", buffer, 4, 1)
    struct.pack_into("<BBBB", buffer, 8, 1, 0, 0, 0)
    struct.pack_into("<II", buffer, 12, 1, 1)
    struct.pack_into("<I", buffer, 20, len(buffer))
    struct.pack_into("<I", buffer, 84, 1)
    buffer[148:152] = bytes((10, 20, 30, 255))
    buffer.append(0)
    return bytes(buffer)


class _Block:
    def __init__(self, file_size: int) -> None:
        self.file_size = file_size


class _Archive:
    path = "fixture.w3x"

    def __init__(self, named: dict[str, bytes], anonymous: dict[int, bytes]) -> None:
        self._data = b""
        self._named = {name.casefold(): payload for name, payload in named.items()}
        self._anonymous = anonymous
        self._blocks = {
            index: _Block(len(payload)) for index, payload in anonymous.items()
        }

    def has_file(self, name: str) -> bool:
        return name.casefold() in self._named

    def read_file(self, name: str) -> bytes:
        return self._named[name.casefold()]

    def list_files(self) -> list[str]:
        return list(self._named)

    def close(self) -> None:
        """The in-memory fake owns no external resource."""

    def iter_blocks(self) -> Iterable[tuple[int, AnonymousIconBlock]]:
        return tuple(self._blocks.items())

    def read_block_anon(self, block: AnonymousIconBlock) -> bytes | None:
        return next(
            (
                self._anonymous[index]
                for index, candidate in self._blocks.items()
                if candidate is block
            ),
            None,
        )


class _ArchiveSource:
    def __init__(self, archive: _Archive) -> None:
        self.path = archive.path
        self.archive = archive
        self.closed = False

    def open(self) -> ContextManager[MapArchiveReader]:
        return nullcontext(self.archive)

    def close(self) -> None:
        self.closed = True


def _loaded_map(source_path: str, icon_path: str) -> tuple[MapData, _ArchiveSource]:
    payload = _one_pixel_blp()
    archive = _Archive({r"Icons\BTNHero.blp": payload}, {7: payload})
    source = _ArchiveSource(archive)
    item = GameObject(
        category="技能",
        ext="w3a",
        obj_id="A001",
        base_id="AHbz",
        name="暴风雪",
        is_custom=True,
        icon=icon_path,
        field_values={"aub1": "|cffffcc00说明|r|n第二行"},
        field_sources={"aub1": "war3map.w3a"},
    )
    digest = hashlib.sha256(payload).hexdigest()
    entry = ExtractionEntry(
        block_index=7,
        internal_path="Unknown/block_000007.blp",
        state=BlockState.DECODED,
        source=BlockSource.ARCHIVE_RECOVERED,
        declared_size=len(payload),
        written_size=len(payload),
        sha256=digest,
        encrypted=False,
        error_code="",
        detail="",
    )
    return (
        MapData(
            path=source_path,
            name="集成测试图",
            objects={"技能": [item]},
            archive_source=source,
            extraction_ledger=build_extraction_ledger(source_path, "a" * 64, (entry,)),
        ),
        source,
    )


def test_process_one_map_publishes_named_anonymous_and_description_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_path = tmp_path / "sample.w3x"
    source_path.write_bytes(b"map source stays read only")
    loaded, archive_source = _loaded_map(str(source_path), r"Icons\BTNHero.blp")
    monkeypatch.setattr(
        batch_map_processing, "load_map", lambda *_args, **_kwargs: loaded
    )
    monkeypatch.setattr(
        batch_map_processing, "open_game_data_source", lambda _path: None
    )
    fingerprint = fingerprint_source(str(source_path))
    options = BatchOptions(str(tmp_path), str(tmp_path / "output"))

    # When
    result = process_one_map(1, fingerprint, options, MapLoadContext())

    # Then
    output = Path(options.output_root, result.output_directory)
    assert result.state is MapBatchState.COMPLETE
    assert (result.named_icon_count, result.anonymous_icon_count) == (1, 1)
    assert (result.original_written_count, result.png_written_count) == (2, 2)
    assert tuple(output.glob("图标/原始/具名/Icons/*.blp"))
    assert tuple(output.glob("图标/原始/匿名/*.blp"))
    description_text = (output / "对象描述.tsv").read_text(encoding="utf-8")
    description = next(csv.DictReader(io.StringIO(description_text), delimiter="\t"))
    assert description["原始说明"] == "|cffffcc00说明|r|n第二行"
    assert description["可读说明"] == "说明\n第二行"
    assert archive_source.closed


def test_process_one_map_publishes_partial_result_for_an_unresolved_named_icon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_path = tmp_path / "sample.w3x"
    source_path.write_bytes(b"map")
    loaded, _archive_source = _loaded_map(str(source_path), r"Icons\Missing.blp")
    monkeypatch.setattr(
        batch_map_processing, "load_map", lambda *_args, **_kwargs: loaded
    )
    monkeypatch.setattr(
        batch_map_processing, "open_game_data_source", lambda _path: None
    )

    # When
    result = process_one_map(
        1,
        fingerprint_source(str(source_path)),
        BatchOptions(str(tmp_path), str(tmp_path / "output")),
        MapLoadContext(),
    )

    # Then
    assert result.state is MapBatchState.PARTIAL
    assert result.named_icon_count == 0
    assert result.icon_failure_count == 1
    assert result.stage == "published"


def test_process_one_map_closes_loaded_map_when_client_source_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_path = tmp_path / "sample.w3x"
    source_path.write_bytes(b"map")
    loaded, archive_source = _loaded_map(str(source_path), r"Icons\BTNHero.blp")
    monkeypatch.setattr(
        batch_map_processing, "load_map", lambda *_args, **_kwargs: loaded
    )

    def fail_open(_path: str | None) -> None:
        raise OSError("client unavailable")

    monkeypatch.setattr(batch_map_processing, "open_game_data_source", fail_open)

    # When / Then
    with pytest.raises(OSError, match="client unavailable"):
        process_one_map(
            1,
            fingerprint_source(str(source_path)),
            BatchOptions(str(tmp_path), str(tmp_path / "output")),
            MapLoadContext(),
        )
    assert archive_source.closed

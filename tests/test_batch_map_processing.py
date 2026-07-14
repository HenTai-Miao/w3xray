"""Single-map batch extraction integration tests."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from tests.batch_map_processing_fixture import loaded_map
import w3xtool.batch_map_processing as batch_map_processing
from w3xtool.batch_map_processing import process_one_map
from w3xtool.batch_models import MapBatchState
from w3xtool.batch_runner import BatchOptions, fingerprint_source
from w3xtool.load_context import MapLoadContext


def test_process_one_map_publishes_named_anonymous_and_description_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_path = tmp_path / "sample.w3x"
    source_path.write_bytes(b"map source stays read only")
    loaded, archive_source = loaded_map(str(source_path), r"Icons\BTNHero.blp")
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
    loaded, _archive_source = loaded_map(str(source_path), r"Icons\Missing.blp")
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
    loaded, archive_source = loaded_map(str(source_path), r"Icons\BTNHero.blp")
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

"""Single-map batch extraction integration tests."""

from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

import pytest

from tests.batch_map_processing_fixture import loaded_map
import w3xtool.batch_map_processing as batch_map_processing
from w3xtool.batch_map_processing import process_one_map
from w3xtool.batch_models import MapBatchState
from w3xtool.batch_runner import BatchOptions, fingerprint_source
from w3xtool.icon_resources import IconObjectReference, NamedIconResource
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
    assert result.dependency_fingerprint != fingerprint.sha256
    assert len(result.dependency_fingerprint) == 64
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


def test_process_one_map_merges_map_bound_trusted_icon_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the live sources miss an icon that an exact-map trusted cache retained.
    source_path = tmp_path / "sample.w3x"
    source_path.write_bytes(b"map")
    loaded, archive_source = loaded_map(str(source_path), r"Icons\Missing.blp")
    payload = archive_source.archive.read_file(r"Icons\BTNHero.blp")
    fingerprint = fingerprint_source(str(source_path))

    class TrustedSource:
        closed = False

        def has_file(self, _name: str) -> bool:
            return False

        def read_file(self, name: str) -> bytes:
            raise FileNotFoundError(name)

        def cached_icons_for(self, source_digest: str) -> tuple[NamedIconResource, ...]:
            assert source_digest == fingerprint.sha256
            return (
                NamedIconResource(
                    requested_path=r"Icons\Missing.blp",
                    normalized_path=r"Icons\Missing.blp",
                    resolved_path=r"Icons\BTNHero.blp",
                    source_path="可信图标缓存:war3.mpq",
                    payload=payload,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    objects=(IconObjectReference("技能", "A001", "暴风雪"),),
                ),
            )

        def close(self) -> None:
            self.closed = True

    trusted = TrustedSource()
    monkeypatch.setattr(
        batch_map_processing, "load_map", lambda *_args, **_kwargs: loaded
    )
    monkeypatch.setattr(
        batch_map_processing, "open_game_data_source", lambda _path: trusted
    )

    # When: the one-map publisher resolves and exports all known icon evidence.
    result = process_one_map(
        1,
        fingerprint,
        BatchOptions(str(tmp_path), str(tmp_path / "output")),
        MapLoadContext(),
    )

    # Then: cached evidence clears the unresolved count and remains auditable.
    output = Path(result.output_directory)
    index = Path(tmp_path / "output" / output / "图标索引.tsv").read_text(
        encoding="utf-8"
    )
    assert result.state is MapBatchState.COMPLETE
    assert result.named_icon_count == 1
    assert result.icon_failure_count == 0
    assert "可信图标缓存:war3.mpq" in index
    assert trusted.closed

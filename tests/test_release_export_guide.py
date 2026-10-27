"""Release regressions for failed guide generation and image publication."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image
import pytest

import gametool.guide_cli as guide_cli
from gametool.guide_cli import GuideCliOptions
from gametool.guide_minimap import render_marks
from gametool.map_data import MapData


@pytest.mark.parametrize("fail", (False, True))
def test_guide_always_releases_the_map_and_preserves_worker_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fail: bool,
) -> None:
    md = MapData(path="map.w3x", name="地图")
    monkeypatch.delenv("GAMEXRAY_MATERIALIZE_WORKERS", raising=False)
    monkeypatch.setattr(guide_cli, "report_cache_path", lambda _path: None)
    monkeypatch.setattr(guide_cli, "load_map", lambda *_args, **_kwargs: md)
    monkeypatch.setattr(guide_cli, "build_map_load_context", lambda: None)

    def format_report(_md: MapData, _section: str | None) -> str:
        if fail:
            raise ValueError("invalid guide evidence")
        return "【基本信息】\n- 地图名：地图"

    monkeypatch.setattr(guide_cli, "format_guide_report", format_report)

    assert guide_cli.run_guide_cli(GuideCliOptions(str(tmp_path / "map.w3x"))) == (
        2 if fail else 0
    )
    assert md._closed
    assert "GAMEXRAY_MATERIALIZE_WORKERS" not in os.environ
    assert "invalid guide evidence" in capsys.readouterr().err if fail else True


def test_failed_image_encoding_preserves_the_existing_minimap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "minimap.png"
    output.write_bytes(b"previous valid output")
    before = output.read_bytes(), output.stat().st_mtime_ns

    def fail_save(self: Image.Image, destination, *args, **kwargs) -> None:
        if hasattr(destination, "write"):
            destination.write(b"incomplete PNG")
        else:
            Path(destination).write_bytes(b"incomplete PNG")
        raise OSError("encoding failed")

    monkeypatch.setattr(Image.Image, "save", fail_save)

    with pytest.raises(OSError, match="encoding failed"):
        render_marks(
            Image.new("RGB", (4, 4)),
            (0.0, 0.0, 100.0, 100.0),
            (("商店", 50.0, 50.0),),
            str(output),
        )

    assert (output.read_bytes(), output.stat().st_mtime_ns) == before

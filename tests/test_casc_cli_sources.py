"""CASC CLI routing through the common game-data source factory."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from w3xtool.casc_cli import run_casc_cli
from w3xtool.casclib_enumeration import CascEntry, CascNameType
from w3xtool.game_data_inventory import GameDataInventoryView


class _KnownPathSource:
    inventory_view = GameDataInventoryView.KNOWN_PATHS

    def __init__(self) -> None:
        self.closed = False

    def has_file(self, name: str) -> bool:
        return name == "UI\\Test.txt"

    def read_file(self, name: str) -> bytes:
        if not self.has_file(name):
            raise FileNotFoundError(name)
        return b"client-data"

    def iter_entries(
        self,
        _mask: str = "*",
        _listfile: str | None = None,
    ) -> Generator[CascEntry, None, None]:
        yield CascEntry(
            "UI\\Test.txt",
            CascNameType.FULL,
            None,
            "",
            "",
            11,
            True,
            None,
            None,
        )

    def close(self) -> None:
        self.closed = True


def test_inventory_uses_common_known_path_source(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    # Given: the common opener selects a known-path fallback source.
    source = _KnownPathSource()
    output = tmp_path / "inventory.tsv"
    monkeypatch.setattr("w3xtool.casc_cli.open_game_data_source", lambda _path: source, raising=False)

    # When: the CLI writes an inventory.
    code = run_casc_cli((
        "inventory",
        "--game-dir", str(tmp_path),
        "--output", str(output),
    ))

    # Then: fallback scope is explicit and its source is closed.
    assert code == 0
    assert "已知路径" in capsys.readouterr().out
    assert "UI\\Test.txt" in output.read_text(encoding="utf-8")
    assert source.closed


def test_extract_uses_common_known_path_source(tmp_path: Path, monkeypatch) -> None:
    # Given: the common opener selects a readable fallback source.
    source = _KnownPathSource()
    monkeypatch.setattr("w3xtool.casc_cli.open_game_data_source", lambda _path: source, raising=False)

    # When: one real logical path is extracted.
    code = run_casc_cli((
        "extract",
        "--game-dir", str(tmp_path),
        "--entry", "UI\\Test.txt",
        "--output-dir", str(tmp_path / "out"),
    ))

    # Then: data comes from the common source and lifecycle closes once.
    assert code == 0
    assert (tmp_path / "out" / "UI" / "Test.txt").read_bytes() == b"client-data"
    assert source.closed

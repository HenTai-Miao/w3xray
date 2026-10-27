"""Release regressions for native CASC module-path extraction."""

from pathlib import Path
from collections.abc import Generator

import pytest

from gametool.casc_browser import CascBrowserModel
from gametool.casc_cli import run_casc_cli
from gametool.casclib_enumeration import CascEntry, CascNameType
from gametool.casc_source import CascUnsupportedError
from gametool.game_data_inventory import GameDataInventoryView


class _ModuleSource:
    inventory_view = GameDataInventoryView.FULL_ROOT

    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    def read_file(self, name: str) -> bytes:
        assert name == self.name
        return b"native-client-data"

    def has_file(self, name: str) -> bool:
        return name == self.name

    def has_exact_file(self, name: str) -> bool:
        return self.has_file(name)

    def read_exact_file(self, name: str) -> bytes:
        return self.read_file(name)

    def iter_entries(
        self, mask: str = "*", listfile: str | None = None
    ) -> Generator[CascEntry, None, None]:
        del mask, listfile
        yield CascEntry(self.name, CascNameType.FULL, None, "", "", 18, True, 0, 0)

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("name", "relative"),
    (
        (r"war3.w3mod:UI\TriggerData.txt", "war3.w3mod/UI/TriggerData.txt"),
        (
            r"war3.w3mod:_locales\zhcn.w3mod:UI\WorldEditStrings.txt",
            "war3.w3mod/_locales/zhcn.w3mod/UI/WorldEditStrings.txt",
        ),
    ),
)
def test_cli_extracts_modular_root_names_to_portable_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, relative: str
) -> None:
    source = _ModuleSource(name)
    monkeypatch.setattr("gametool.casc_cli.open_game_data_source", lambda _path: source)
    output = tmp_path / "out"

    code = run_casc_cli(
        (
            "extract",
            "--game-dir",
            str(tmp_path),
            "--entry",
            name,
            "--output-dir",
            str(output),
        )
    )

    assert code == 0
    assert (output / relative).read_bytes() == b"native-client-data"
    assert source.closed


def test_browser_extracts_same_modular_path_as_cli(tmp_path: Path) -> None:
    name = r"war3.w3mod:_locales\zhcn.w3mod:UI\TriggerData.txt"
    source = _ModuleSource(name)
    entry = CascEntry(
        name, CascNameType.FULL, None, "01" * 16, "02" * 16, 18, True, 0, 0
    )
    model = CascBrowserModel(source)

    exported = model.export_entry(entry, tmp_path)

    assert exported == tmp_path / "war3.w3mod/_locales/zhcn.w3mod/UI/TriggerData.txt"
    assert exported.read_bytes() == b"native-client-data"


@pytest.mark.parametrize(
    "name",
    (r"..\outside", r"C:\outside.txt", "file.txt:stream", "war3.w3mod:../outside"),
)
def test_module_mapping_preserves_path_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    def unexpected_open(_path: str):
        pytest.fail("unsafe names must be rejected before opening storage")

    monkeypatch.setattr("gametool.casc_cli.open_game_data_source", unexpected_open)
    assert (
        run_casc_cli(
            (
                "extract",
                "--game-dir",
                str(tmp_path),
                "--entry",
                name,
                "--output-dir",
                str(tmp_path / "out"),
            )
        )
        == 1
    )


def test_unsupported_blte_is_an_actionable_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class EncryptedSource(_ModuleSource):
        def read_file(self, name: str) -> bytes:
            raise CascUnsupportedError("encrypted BLTE chunk")

    source = EncryptedSource("encrypted.blp")
    monkeypatch.setattr("gametool.casc_cli.open_game_data_source", lambda _path: source)

    code = run_casc_cli(
        (
            "extract",
            "--game-dir",
            str(tmp_path),
            "--entry",
            "encrypted.blp",
            "--output-dir",
            str(tmp_path / "out"),
        )
    )

    assert code == 1
    assert "encrypted BLTE" in capsys.readouterr().err
    assert source.closed
    assert not (tmp_path / "out").exists()

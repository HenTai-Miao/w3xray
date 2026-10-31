"""Source children must keep POSIX component boundaries on Windows."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import pytest

from gametool import windows_source_reads as sources


@pytest.mark.skipif(os.name != "nt", reason="Windows source component semantics")
@pytest.mark.parametrize(
    "relative",
    (
        r"C:\outside.txt",
        r"C:outside.txt",
        r"\outside.txt",
        r"\\server\share\outside.txt",
        r"nested\outside.txt",
        r"..\outside.txt",
        "source.txt:stream",
        "CON.txt",
        "source.txt.",
    ),
)
def test_rejects_windows_redirection_before_opening_a_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    with sources.WindowsSourceRoot.open(tmp_path) as root:
        opened: list[Path] = []

        def reject_open(*_args: object, **_kwargs: object) -> None:
            opened.append(tmp_path)
            raise AssertionError("invalid child must fail before any native open")

        monkeypatch.setattr(sources, "_hold_component", reject_open)
        with pytest.raises(sources.WindowsSourceError, match="canonical relative"):
            with root.protect(PurePosixPath(relative)):
                pytest.fail("invalid relative source was accepted")
        assert not opened


@pytest.mark.skipif(os.name != "nt", reason="Windows source component semantics")
def test_nested_unicode_source_remains_readable_and_releases_handles(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "对象" / "来源.tsv"
    nested.parent.mkdir()
    nested.write_bytes(b"complete evidence")
    with sources.WindowsSourceRoot.open(tmp_path) as root:
        with root.protect(PurePosixPath("对象/来源.tsv")):
            assert nested.read_bytes() == b"complete evidence"
    nested.rename(nested.with_suffix(".released"))

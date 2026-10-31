"""Script exports retain distinct source paths and their exact contents."""

from __future__ import annotations

from pathlib import Path

from gametool.knowledge_io import knowledge_write_session
from gametool.knowledge_script_exports import write_script_exports
from gametool.script_text_export import ReadableScriptExport


def test_same_basename_sources_keep_both_relative_paths_and_bytes(
    tmp_path: Path,
) -> None:
    sources = (
        ReadableScriptExport("chapter_a/war3map.lua", 'print("first")\r\n'),
        ReadableScriptExport("chapter_b/war3map.lua", 'print("second")\n'),
    )

    with knowledge_write_session(str(tmp_path)) as recorder:
        count = write_script_exports(sources, str(tmp_path))

    assert count == 2
    for source in sources:
        assert (tmp_path / source.name).read_bytes() == source.text.encode("utf-8")
    assert {item.path for item in recorder.report().items} == {
        source.name for source in sources
    }


def test_unsafe_source_path_is_reported_without_writing_outside_pack(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    outside = tmp_path / "outside.lua"
    outside.write_bytes(b"existing external data")
    source = ReadableScriptExport("../outside.lua", 'print("new")\n')

    with knowledge_write_session(str(pack)) as recorder:
        count = write_script_exports((source,), str(pack))

    assert count == 0
    assert outside.read_bytes() == b"existing external data"
    report = recorder.report()
    assert report.failed_count == 1
    assert report.items[0].error

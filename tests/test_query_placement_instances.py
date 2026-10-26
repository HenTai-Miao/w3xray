"""Independent source instances add up; missing provenance never invents one."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_HEADER = [
    "来源",
    "行号",
    "函数",
    "调用",
    "参数序号",
    "参数",
    "字符串",
    "对象码",
    "机制",
    "用途",
    "摘要",
    "调用偏移",
]
_POINT = (1.25, -2.5)


@pytest.fixture(autouse=True)
def isolated_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _call(lua: bool = True, *, x: str = "1.25") -> str:
    return (
        f"CreateItem(FourCC('I001'),{x},-2.5)"
        if lua
        else f"call CreateItem('I001',{x},-2.5)"
    )


def _script(pack: Path, name: str, text: str) -> Path:
    path = pack / "脚本可读文本" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _index(pack: Path, sources: list[str], *, lua: bool = True, body: str = "") -> Path:
    pack.mkdir(parents=True, exist_ok=True)
    path = pack / "脚本调用参数索引.tsv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerows(
            [
                _HEADER,
                *[
                    [
                        source,
                        "1",
                        "Owner",
                        "CreateItem",
                        "1",
                        "argument",
                        "",
                        "",
                        "",
                        "",
                        body or _call(lua),
                        str(i),
                    ]
                    for i, source in enumerate(sources)
                ],
            ]
        )
    return path


def _near(pack: Path, limit: int = 1):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "near", "1.25 -2.5 1", limit=limit)
    )


@pytest.mark.parametrize("lua", [False, True])
@pytest.mark.parametrize("source_count,index_count", [(1, 1), (1, 4), (3, 1), (3, 4)])
def test_independent_indexed_instances_are_added_to_full_source_instances(
    tmp_path: Path, lua: bool, source_count: int, index_count: int
) -> None:
    suffix = ".lua" if lua else ".j"
    source = _script(tmp_path, "known" + suffix, "\n".join([_call(lua)] * source_count))
    table = _index(tmp_path, ["extra" + suffix] * index_count, lua=lua)
    original = (source.read_bytes(), table.read_bytes())
    assert queries.load_placements(tmp_path) == [("I001", *_POINT, "item")] * (
        source_count + index_count
    )
    data = json.loads(_near(tmp_path).render(as_json=True))
    assert data["exit_code"] == 0 and not data["spatial_diagnostics"]
    entry = data["entries"][0]
    assert entry["count"] == source_count + index_count
    assert entry["positions"] == [list(_POINT)] * (source_count + index_count)
    assert "其余" not in "\n".join(data["lines"])
    assert (source.read_bytes(), table.read_bytes()) == original


def test_a_known_mirror_is_removed_before_independent_instances_are_added(
    tmp_path: Path,
) -> None:
    _script(tmp_path, "known.lua", _call())
    _index(tmp_path, ["KNOWN.LUA", "extra.lua"])
    data = json.loads(_near(tmp_path).render(as_json=True))
    assert not data["spatial_diagnostics"]
    assert data["entries"][0]["count"] == 2


def test_matching_numeric_positions_from_different_expressions_keep_both_instances(
    tmp_path: Path,
) -> None:
    _script(tmp_path, "known.lua", _call())
    _index(tmp_path, ["extra.lua"], body=_call(x="1.250"))
    assert len(queries.load_placements(tmp_path)) == 2
    assert (
        json.loads(_near(tmp_path).render(as_json=True))["entries"][0]["positions"]
        == [list(_POINT)] * 2
    )


@pytest.mark.parametrize("body", [_call(), _call(x="1.5")])
def test_missing_index_source_is_diagnosed_when_real_script_sources_exist(
    tmp_path: Path, body: str
) -> None:
    _script(tmp_path, "known.lua", _call())
    _index(tmp_path, [""], body=body)
    data = json.loads(_near(tmp_path).render(as_json=True))
    assert data["exit_code"] == 0
    assert data["entries"][0]["count"] == 1
    assert data["entries"][0]["positions"] == [list(_POINT)]
    assert data["spatial_diagnostics"]
    assert "来源未记录" in "\n".join(data["lines"])
    assert body in "\n".join(data["lines"])


def test_unattributed_index_cannot_bypass_a_shadowed_source_native(
    tmp_path: Path,
) -> None:
    _script(tmp_path, "known.lua", "local CreateItem=function(...) end;" + _call())
    _index(tmp_path, [""])
    data = json.loads(_near(tmp_path).render(as_json=True))
    assert data["exit_code"] == 2 and not data["entries"]
    assert "来源未记录" in "\n".join(data["lines"])


def test_unattributed_standalone_legacy_index_still_retains_its_point(
    tmp_path: Path,
) -> None:
    path = tmp_path / "脚本调用参数索引.tsv"
    path.write_text(_call(False) + "\n", encoding="utf-8")
    data = json.loads(_near(tmp_path).render(as_json=True))
    assert data["exit_code"] == 0 and not data["spatial_diagnostics"]
    assert data["entries"][0]["count"] == 1


def test_content_change_between_independent_and_mirrored_sources_refreshes_counts(
    tmp_path: Path,
) -> None:
    _script(tmp_path, "known.lua", _call())
    path = _index(tmp_path, ["extra.lua"])
    before = path.stat()
    assert json.loads(_near(tmp_path).render(as_json=True))["entries"][0]["count"] == 2
    _index(tmp_path, ["known.lua"])
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert json.loads(_near(tmp_path).render(as_json=True))["entries"][0]["count"] == 1


def test_campaign_sections_keep_all_independent_instances(tmp_path: Path) -> None:
    for i in range(2):
        pack = tmp_path / "子地图" / str(i)
        _script(pack, "known.lua", _call())
        _index(pack, ["extra.lua"] * (i + 1))
    data = json.loads(_near(tmp_path).render(as_json=True))
    assert data["exit_code"] == 0 and not data["spatial_diagnostics"]
    assert [entry["count"] for entry in data["entries"]] == [2, 3]

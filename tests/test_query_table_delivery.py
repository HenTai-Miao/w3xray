"""Queries deliver exact frozen table evidence and revalidate it before success."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(root: Path, category: str = "单位", name: str = "旧值") -> Path:
    path = root / "对象ID" / (category + ".tsv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "分类\tID\t数值\t基础ID\t名称\t自定义\t说明\n"
        + f"{category}\tx001\t1\tHamg\t{name}\t是\t原始证据\n",
        encoding="utf-8",
    )
    return path


def _mutate(path: Path) -> None:
    info = path.stat()
    path.write_bytes(path.read_bytes().replace("旧值".encode(), "新值".encode()))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))


def _query(root: Path, command: str = "units", query: str = ""):
    return queries.execute_pack_query(PackQueryCliOptions(str(root), command, query))


def test_csv_parser_receives_the_same_bytes_as_the_cache_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path)
    real_reader = csv.reader
    changed = False

    def reader(source, *args, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            _mutate(path)
        return real_reader(source, *args, **kwargs)

    monkeypatch.setattr(queries.csv, "reader", reader)
    # This low-level read returns its frozen bytes. The public execution boundary
    # subsequently verifies those bytes before claiming a successful delivery.
    rows = queries._read_rows(tmp_path, "对象ID/单位.tsv")
    assert changed and rows[1][4] == "旧值"
    assert "新值" in path.read_text(encoding="utf-8")
    assert queries._read_rows(tmp_path, "对象ID/单位.tsv")[1][4] == "新值"


@pytest.mark.parametrize(
    "command,category,keyword",
    [
        ("units", "单位", ""),
        ("heroes", "单位", ""),
        ("search", "单位", "旧值"),
        ("item", "物品", ""),
        ("price", "物品", ""),
        ("tech", "科技", ""),
    ],
)
def test_changed_source_keeps_evidence_but_never_replaces_successful_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    category: str,
    keyword: str,
) -> None:
    path = _write(tmp_path, category)
    assert _query(tmp_path, command, keyword).exit_code == 0
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()
    real = queries._QUERIES[command]

    def change(pack, query, limit):
        lines = real(pack, query, limit)
        _mutate(path)
        return lines

    monkeypatch.setitem(queries._QUERIES, command, change)
    result = _query(tmp_path, command, keyword)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["source_stable"] is False
    assert "[x001] 旧值" in result.render() and "新值" not in result.render()
    assert "查询交付前变化" in result.render() and any(
        str(tmp_path) in note for note in data["warnings"]
    )
    assert memo.read_bytes() == before


@pytest.mark.parametrize("change", ["remove", "appear"])
def test_source_existence_changes_cannot_be_reported_as_stable_empty_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    path = _write(tmp_path) if change == "remove" else tmp_path / "对象ID" / "单位.tsv"
    real = queries._QUERIES["units"]

    def mutate(pack, query, limit):
        lines = real(pack, query, limit)
        if change == "remove":
            path.unlink()
        else:
            _write(tmp_path)
        return lines

    monkeypatch.setitem(queries._QUERIES, "units", mutate)
    result = _query(tmp_path)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["source_stable"] is False
    assert "对象ID/单位.tsv" in result.render() and "查询交付前变化" in result.render()
    assert queries._load_last_query() is None


def test_campaign_revalidates_earlier_zero_match_scopes_before_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "子地图" / "001", tmp_path / "子地图" / "002"
    path = _write(first)
    _write(second, name="目标")
    real = queries._QUERIES["units"]

    def mutate(pack, query, limit):
        lines = real(pack, query, limit)
        if pack == second:
            _mutate(path)
        return lines

    monkeypatch.setitem(queries._QUERIES, "units", mutate)
    result = _query(tmp_path, query="目标")
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["source_stable"] is False
    assert any(
        section["pack"] == str(first)
        and section["source_stable"] is False
        and "查询交付前变化" in "\n".join(section["lines"])
        for section in data["sections"]
    )
    assert any(
        section["pack"] == str(second) and "目标" in "\n".join(section["lines"])
        for section in data["sections"]
    )


def test_diff_revalidates_both_old_and_new_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    path = _write(old)
    _write(new)
    real = queries._query_diff_result

    def mutate(pack, query, limit, pack_b=""):
        result = real(pack, query, limit, pack_b)
        _mutate(path)
        return result

    monkeypatch.setattr(queries, "_query_diff_result", mutate)
    result = _query(new, "diff", str(old))
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["comparison_complete"] is False
    assert data["source_stable"] is False and any(
        str(old) in note for note in data["warnings"]
    )


def test_query_snapshot_context_is_restored_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = {}
    monkeypatch.setattr(queries, "_QUERY_TABLE_SNAPSHOTS", sentinel)

    def fail(pack, query, limit):
        raise RuntimeError("query failed")

    monkeypatch.setitem(queries._QUERIES, "units", fail)
    with pytest.raises(RuntimeError, match="query failed"):
        _query(tmp_path)
    assert queries._QUERY_TABLE_SNAPSHOTS is sentinel


def _script(root: Path, *, original: bool = True, command: str = "-test") -> Path:
    folder = root / ("脚本原始文本" if original else "脚本可读文本")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "war3map.lua"
    path.write_text(
        "local t=CreateTrigger()\n"
        f"TriggerRegisterPlayerChatEvent(t,Player(0),'{command}',true)\n"
        "TriggerAddAction(t,function() BJDebugMsg('OLD') end)\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("original", [True, False])
@pytest.mark.parametrize(
    "command,query", [("cmd", "-test"), ("where", "I001"), ("drop", "I001")]
)
def test_script_bytes_are_verified_after_the_last_query_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    original: bool,
    command: str,
    query: str,
) -> None:
    path = _script(tmp_path, original=original)
    _write(tmp_path)
    assert _query(tmp_path).exit_code == 0
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()
    real = queries._query_script_result

    def mutate(pack, mode, keyword, limit):
        result = real(pack, mode, keyword, limit)
        info = path.stat()
        path.write_bytes(path.read_bytes().replace(b"OLD", b"NEW"))
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        return result

    monkeypatch.setattr(queries, "_query_script_result", mutate)
    result = _query(tmp_path, command, query)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["source_stable"] is False
    assert "war3map.lua" in result.render() and "查询交付前变化" in result.render()
    if command == "cmd":
        assert "OLD" in result.render() and "NEW" not in result.render()
    assert memo.read_bytes() == before


@pytest.mark.parametrize(
    "change", ["new_file", "missing_readable", "new_original", "deleted_file"]
)
def test_script_inventory_and_missing_directory_observations_are_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    path = None if change == "missing_readable" else _script(tmp_path, original=False)
    real = queries._query_script_result

    def mutate(pack, mode, keyword, limit):
        result = real(pack, mode, keyword, limit)
        if change == "missing_readable":
            _script(tmp_path, original=False)
        elif change == "new_original":
            _script(tmp_path)
        elif change == "new_file":
            assert path is not None
            (path.parent / "later.lua").write_text(
                "CreateItem(FourCC('I001'),1,2)", encoding="utf-8"
            )
        else:
            assert path is not None
            path.unlink()
        return result

    monkeypatch.setattr(queries, "_query_script_result", mutate)
    result = _query(tmp_path, "cmd", "-test")
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["source_stable"] is False
    assert "查询交付前变化" in result.render()
    assert queries._load_last_query() is None


def test_campaign_script_proofs_include_earlier_zero_match_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "子地图" / "001", tmp_path / "子地图" / "002"
    path = _script(first, command="-other")
    _script(second)
    real = queries._query_script_result

    def mutate(pack, mode, keyword, limit):
        result = real(pack, mode, keyword, limit)
        if pack == second:
            info = path.stat()
            path.write_bytes(path.read_bytes().replace(b"OLD", b"NEW"))
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        return result

    monkeypatch.setattr(queries, "_query_script_result", mutate)
    result = _query(tmp_path, "cmd", "-test")
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["source_stable"] is False
    assert any(
        section["pack"] == str(first) and section["source_stable"] is False
        for section in data["sections"]
    )
    assert any(
        section["pack"] == str(second) and "OLD" in "\n".join(section["lines"])
        for section in data["sections"]
    )

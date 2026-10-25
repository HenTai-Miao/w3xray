"""Legacy source aliases retain full coordinate evidence without binding guesses."""

import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_placement_index import indexed_placements
from gametool.script_call_argument_index import (
    build_script_call_argument_index,
    format_script_call_argument_index_tsv,
)
from gametool.script_source_identity import ScriptSourceNames, source_name_key
from gametool.script_sources import AnalysisScriptSource

_CALL = "_G . CreateItem(FourCC('I001'),1.25,-2.5)"
_SHADOW = "local _G={}; " + _CALL


@pytest.mark.parametrize(
    "alias",
    [
        "war3map.lua",
        "WAR3MAP.LUA",
        "./war3map.lua",
        r".\war3map.lua",
        ".//./war3map.lua",
        "脚本可读文本/war3map.lua",
        r"脚本可读文本\WAR3MAP.LUA",
        r"C:\old\pack\脚本可读文本\war3map.lua",
        "/old/pack/脚本可读文本/WAR3MAP.LUA",
        r"\\server\pack\脚本可读文本\war3map.lua",
        r"C:\old\map\war3map.lua",
    ],
)
def test_source_aliases_resolve_to_the_loaded_name_without_reading_paths(
    alias: str,
) -> None:
    names = ScriptSourceNames(["war3map.lua"])
    match = names.resolve(alias)
    assert match.sources == ("war3map.lua",) and not match.diagnostic
    assert names.resolve(alias) is match


@pytest.mark.parametrize(
    "alias",
    [
        "scripts/war3map.lua",
        r"scripts\war3map.lua",
        "SCRIPTS/WAR3MAP.LUA",
        "./scripts//./war3map.lua",
        "脚本可读文本/scripts/war3map.lua",
        "war3map.lua",
        r"C:\previous\scripts\war3map.lua",
    ],
)
def test_nested_source_and_unique_basename_aliases_keep_the_full_identity(
    alias: str,
) -> None:
    match = ScriptSourceNames(["scripts/war3map.lua"]).resolve(alias)
    assert (
        match.sources == ("scripts/war3map.lua",) and match.key == "scripts/war3map.lua"
    )


@pytest.mark.parametrize(
    "alias", ["shared.lua", "SHARED.LUA", r"old\shared.lua", r"C:\previous\shared.lua"]
)
def test_ambiguous_basenames_keep_all_candidates(alias: str) -> None:
    match = ScriptSourceNames(["a/shared.lua", "b/shared.lua"]).resolve(alias)
    assert match.method == "ambiguous" and match.sources == (
        "a/shared.lua",
        "b/shared.lua",
    )
    assert all(name in match.diagnostic for name in match.sources)


def test_full_exact_identity_wins_over_another_source_basename() -> None:
    names = ScriptSourceNames(["shared.lua", "folder/shared.lua", "FOLDER/SHARED.LUA"])
    assert names.resolve("shared.lua").sources == ("shared.lua",)
    assert names.resolve("folder/shared.lua").sources == ("folder/shared.lua",)
    assert names.resolve("Folder/Shared.lua").method == "ambiguous"


@pytest.mark.parametrize(
    "name",
    [
        "../war3map.lua",
        r"folder\..\war3map.lua",
        "脚本可读文本/../war3map.lua",
        r"C:\old\..\war3map.lua",
    ],
)
def test_parent_directory_labels_are_diagnosed_instead_of_resolved(name: str) -> None:
    match = ScriptSourceNames(["war3map.lua"]).resolve(name)
    assert (
        match.method == "unsafe"
        and not match.sources
        and "上级目录" in match.diagnostic
    )
    assert ".." in source_name_key(name).split("/")


def test_case_collision_retains_exact_names_and_diagnoses_fuzzy_names() -> None:
    names = ScriptSourceNames(["A.lua", "a.lua"])
    assert names.resolve("A.lua").sources == ("A.lua",)
    assert names.resolve("a.lua").sources == ("a.lua",)
    assert names.resolve("A.LUA").sources == ("A.lua", "a.lua")
    assert names.resolve("A.LUA").method == "ambiguous"


def test_unknown_sources_keep_case_and_are_not_merged_without_evidence() -> None:
    names = ScriptSourceNames([])
    assert names.resolve("A.lua").key != names.resolve("a.lua").key
    assert names.resolve("A.lua").method == "missing"


def test_multiple_export_prefix_candidates_are_all_retained() -> None:
    names = ScriptSourceNames(["a.lua", "脚本可读文本/a.lua"])
    match = names.resolve("C:/old/脚本可读文本/脚本可读文本/a.lua")
    assert match.method == "ambiguous" and len(match.sources) == 2
    assert names.resolve("脚本可读文本/a.lua").sources == ("脚本可读文本/a.lua",)


@pytest.mark.parametrize(
    "name",
    [
        "/folder/shared.lua",
        "//folder/shared.lua",
        r"\\folder\shared.lua",
        "///folder/shared.lua",
    ],
)
def test_absolute_or_unc_roots_are_not_silently_dropped(name: str) -> None:
    names = ScriptSourceNames(["folder/shared.lua", "other/shared.lua"])
    assert source_name_key(name).startswith("/")
    assert names.resolve(name).method == "ambiguous"
    assert len(names.resolve(name).sources) == 2


@pytest.mark.parametrize(
    "alias",
    ["WAR3MAP.LUA", "./war3map.lua", "脚本可读文本/war3map.lua", r"C:\old\war3map.lua"],
)
def test_index_aliases_cannot_bypass_source_global_binding(alias: str) -> None:
    contexts = (AnalysisScriptSource("war3map.lua", _SHADOW, True),)
    report = indexed_placements(contexts, (((alias, "1"), _CALL, "15"),))
    assert not report.placements and not report.diagnostics


def test_known_source_aliases_merge_one_physical_index_call() -> None:
    contexts = (
        AnalysisScriptSource("folder/war3map.lua", "function Nothing() end", True),
    )
    rows = tuple(
        ((alias, "1"), _CALL, "10")
        for alias in (
            "folder/war3map.lua",
            "FOLDER/WAR3MAP.LUA",
            "war3map.lua",
            "脚本可读文本/folder/war3map.lua",
        )
    )
    assert indexed_placements(contexts, rows).placements == (
        ("I001", 1.25, -2.5, "item"),
    )


def test_different_offsets_and_independent_unknown_sources_keep_every_call() -> None:
    rows = tuple(
        ((source, "1"), _CALL, offset)
        for source, offset in [("a.lua", "10"), ("A.lua", "10"), ("a.lua", "20")]
    )
    assert (
        indexed_placements((), rows).placements == (("I001", 1.25, -2.5, "item"),) * 3
    )


def test_ambiguous_rows_keep_full_summaries_and_factor_the_candidate_catalog() -> None:
    contexts = tuple(
        AnalysisScriptSource(f"script{i:04}/shared.lua", "function Nothing() end", True)
        for i in range(1200)
    )
    rows = tuple(
        (("SHARED.LUA", str(i)), f"CreateItem(FourCC('I{i:03X}'),{i},0)", str(i))
        for i in range(300)
    )
    report = indexed_placements(contexts, rows)
    assert not report.placements and len(report.diagnostics) == 300
    output = "\n".join(report.diagnostics)
    assert all(output.count(context.source) == 1 for context in contexts)
    assert all(f"I{i:03X}" in output for i in range(300))
    assert "1200 个候选" in output and "来源候选组 1" in output


def test_alias_only_legacy_rows_keep_their_language_and_all_call_sites() -> None:
    rows = tuple(
        (("WAR3MAP.J", str(i)), f"call CreateItem('I001',{i}.25,-{i}.5)", str(i))
        for i in range(1600)
    )
    report = indexed_placements((), rows)
    assert len(report.placements) == 1600 and not report.diagnostics
    assert report.placements[-1] == ("I001", 1599.25, -1599.5, "item")


def test_resolved_source_language_is_authoritative_for_mirrors_and_wct() -> None:
    source = "war3map.wct(自定义代码).txt"
    contexts = (AnalysisScriptSource(source, "function Nothing() end", True),)
    rows = (((source.upper(), "1"), "CreateItem('I001',1,2)", "10"),)
    assert not indexed_placements(contexts, rows).placements


@pytest.mark.parametrize(
    "alias",
    ["WAR3MAP.LUA", "./war3map.lua", "脚本可读文本/war3map.lua", r"C:\old\war3map.lua"],
)
def test_real_pack_reader_reuses_binding_for_source_aliases(
    tmp_path: Path, alias: str
) -> None:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(_SHADOW, encoding="utf-8")
    md = MapData(
        path="synthetic.w3x", name="来源映射", scripts={"war3map.lua": _SHADOW}
    )
    table = format_script_call_argument_index_tsv(
        build_script_call_argument_index(md)
    ).replace("war3map.lua", alias)
    (tmp_path / "脚本调用参数索引.tsv").write_text(table, encoding="utf-8")
    assert queries.load_placements(tmp_path) == []


def test_near_discloses_ambiguous_source_candidates_in_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    scripts = tmp_path / "脚本可读文本"
    for folder in ("a", "b"):
        target = scripts / folder
        target.mkdir(parents=True)
        (target / "shared.lua").write_text("function Nothing() end", encoding="utf-8")
    (tmp_path / "脚本调用参数索引.tsv").write_text(
        f"SHARED.LUA\t1\tCreateItem\t{_CALL}\n", encoding="utf-8"
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1.25 -2.5 1")
    )
    data = json.loads(result.render(as_json=True))
    assert not data["entries"]
    output = result.render()
    assert "来源未唯一确定" in output and "I001" in output
    assert all(name in output for name in ("a/shared.lua", "b/shared.lua"))


def test_new_index_after_a_miss_invalidates_cached_query_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.j").write_text(
        "function F takes nothing returns nothing\nendfunction", encoding="utf-8"
    )
    options = PackQueryCliOptions(str(tmp_path), "near", "1.25 -2.5 1")
    assert not json.loads(queries.execute_pack_query(options).render(as_json=True))[
        "entries"
    ]
    (tmp_path / "脚本调用参数索引.tsv").write_text(
        "extra.j\t1\tCreateItem\tcall CreateItem('I001',1.25,-2.5)\n", encoding="utf-8"
    )
    entries = json.loads(queries.execute_pack_query(options).render(as_json=True))[
        "entries"
    ]
    assert [row["code"] for row in entries] == ["I001"]


def test_cached_rows_are_not_mutated_by_source_identity_mapping(tmp_path: Path) -> None:
    target = tmp_path / "脚本调用参数索引.tsv"
    target.write_text(f"WAR3MAP.LUA\t1\tCreateItem\t{_CALL}\n", encoding="utf-8")
    original = target.read_bytes()
    rows = queries._read_rows(tmp_path, target.name)
    snapshot = [list(row) for row in rows]
    assert queries.load_placements(tmp_path) == [("I001", 1.25, -2.5, "item")]
    assert queries._read_rows(tmp_path, target.name) is rows and rows == snapshot
    assert target.read_bytes() == original

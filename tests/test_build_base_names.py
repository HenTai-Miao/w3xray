"""build_base_names.py 的测试：DirSource 文件夹源 + 文件夹模式端到端。

只用合成数据，不读真实游戏文件，因此在经典 1.27（甚至无游戏）环境下也能跑。
"""
import os
import types

import pytest

import build_base_names as bbn


def test_module_imports():
    # 顶层 stdout.reconfigure 被守护后，pytest 捕获下也能导入
    assert hasattr(bbn, "main")


def test_dirsource_case_and_sep_insensitive(tmp_path):
    d = tmp_path / "Units"
    d.mkdir()
    (d / "HumanUnitStrings.txt").write_text("[hfoo]\nName=步兵\n", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    # 查询用 MPQ 风格反斜杠，磁盘是子目录正斜杠
    assert src.has_file("Units\\HumanUnitStrings.txt")
    assert "步兵" in src.read_file("Units\\HumanUnitStrings.txt").decode("utf-8")


def test_dirsource_lowercase_disk(tmp_path):
    d = tmp_path / "units"
    d.mkdir()
    (d / "humanunitstrings.txt").write_text("x", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    # 查询混合大小写，磁盘全小写
    assert src.has_file("Units\\HumanUnitStrings.txt")


def test_dirsource_w3mod_prefix(tmp_path):
    # 模拟 casc-extract 的 war3.w3mod 命名空间前缀
    d = tmp_path / "war3.w3mod" / "units"
    d.mkdir(parents=True)
    (d / "itemfunc.txt").write_text("y", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    assert src.has_file("Units\\ItemFunc.txt")


def test_dirsource_basename_fallback(tmp_path):
    # 路径结构对不上，但文件名唯一 -> 兜底命中
    d = tmp_path / "whatever" / "deep"
    d.mkdir(parents=True)
    (d / "UnitData.slk").write_text("z", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    assert src.has_file("Units\\UnitData.slk")


def test_dirsource_missing_returns_none(tmp_path):
    (tmp_path / "a.txt").write_text("z", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    assert not src.has_file("Units\\Nope.txt")
    with pytest.raises(FileNotFoundError):
        src.read_file("Units\\Nope.txt")


def test_dirsource_empty_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        bbn.DirSource(str(tmp_path))


def test_dirsource_nonexistent_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        bbn.DirSource(str(tmp_path / "nope"))


def test_dirsource_multi_candidate_picks_shortest_and_warns(tmp_path, capsys):
    # 同名 units/itemdata.slk 在两条带前缀的路径下（均非精确匹配，触发 endswith 多候选）：
    # 取最短路径并打 warning
    shallow = tmp_path / "sd" / "units"
    shallow.mkdir(parents=True)
    (shallow / "itemdata.slk").write_text("shallow", encoding="utf-8")
    deep = tmp_path / "war3.w3mod" / "hd" / "units"
    deep.mkdir(parents=True)
    (deep / "itemdata.slk").write_text("deep", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    assert src.read_file("Units\\ItemData.slk").decode() == "shallow"
    assert "warning" in capsys.readouterr().out.lower()


def test_folder_mode_end_to_end(tmp_path):
    # 合成一个最小的「游戏数据文件夹」
    units = tmp_path / "src" / "Units"
    units.mkdir(parents=True)
    (units / "HumanUnitStrings.txt").write_text(
        "[hfoo]\nName=步兵\n", encoding="utf-8")
    (units / "ItemData.slk").write_text(
        'ID;PWIDTH\nB;Y2;X2\nC;Y1;X1;K"code"\nC;Y1;X2;K"goldcost"\nC;Y2;X1;K"ratf"\nC;Y2;X2;K"200"\nE\n',
        encoding="utf-8")

    out = tmp_path / "out"
    out.mkdir()
    args = types.SimpleNamespace(
        from_dir=str(tmp_path / "src"), game=None, out_dir=str(out))
    bbn.main(args)

    names_py = (out / "base_names.py").read_text(encoding="utf-8")
    assert "hfoo" in names_py and "步兵" in names_py
    # 三个产物都应生成
    assert (out / "base_objects.py").exists()
    assert (out / "westrings.py").exists()


def test_report_dir_coverage_runs(tmp_path, capsys):
    d = tmp_path / "Units"
    d.mkdir()
    (d / "ItemData.slk").write_text("a", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    bbn.report_dir_coverage(src)
    out = capsys.readouterr().out
    assert "覆盖报告" in out
    assert "未找到" in out  # 绝大多数文件缺失

"""build_base_names.py 的测试：DirSource 文件夹源 + 文件夹模式端到端。

只用合成数据，不读真实游戏文件，因此在经典 1.27（甚至无游戏）环境下也能跑。
"""
import os

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


def test_report_dir_coverage_runs(tmp_path, capsys):
    d = tmp_path / "Units"
    d.mkdir()
    (d / "ItemData.slk").write_text("a", encoding="utf-8")
    src = bbn.DirSource(str(tmp_path))
    bbn.report_dir_coverage(src)
    out = capsys.readouterr().out
    assert "覆盖报告" in out
    assert "未找到" in out  # 绝大多数文件缺失

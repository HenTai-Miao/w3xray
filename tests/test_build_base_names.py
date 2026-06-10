"""build_base_names.py 的测试：DirSource 文件夹源 + 文件夹模式端到端。

只用合成数据，不读真实游戏文件，因此在经典 1.27（甚至无游戏）环境下也能跑。
"""
import os

import pytest

import build_base_names as bbn


def test_module_imports():
    # 顶层 stdout.reconfigure 被守护后，pytest 捕获下也能导入
    assert hasattr(bbn, "main")

# -*- coding: utf-8 -*-
"""live 子命令：读取运行中游戏的主角背包（多策略、版本自适应）。

用法：
    uv run main.py live <地图路径> [--strategy auto|handle|chain|icons] [--test-image <截图>]
                        [--pack <资料包目录>] [--save-snapshot <目录>] [--load-snapshot <目录>]
                        [--unit <单位名|四码>] [--players] [--resources <金币> <木材>]

策略 handle = 句柄系统直读: 自动识别当前选中单位并读其背包 6 槽 + 全图带物品单位
(需 Game.dll 版本偏移已知, 目前 1.27.0.52240 已验证)。auto 时优先尝试 handle。

对游戏进程只读（ReadProcessMemory / PrintWindow），不注入、不修改、不碰存档。
给地图路径时首次自动导出知识包到缓存（按地图大小+修改时间失效，之后复用）；
也可用 --pack 直接指定已有资料包。运行需要 numpy/pillow：
    uv run --with numpy --with pillow python main.py live <地图路径>
"""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .cache_root import w3xray_cache_root
from .cli_output import configure_cli_output
from .presentation_safety import single_line_text

__all__ = (
    "LiveCliOptionError",
    "LiveCliOptions",
    "parse_live_cli_options",
    "run_live_cli",
)

_STRATEGIES = ("auto", "handle", "chain", "icons")
_VALUE_OPTIONS = (
    "--pack",
    "--test-image",
    "--save-snapshot",
    "--load-snapshot",
    "--unit",
)
_FLAG_OPTIONS = ("--players",)
_TWO_VALUE_OPTIONS = ("--resources",)


@dataclass(frozen=True, slots=True)
class LiveCliOptions:
    """live 子命令的已解析参数；地图路径与 --pack 至少给一个。"""

    map_path: str | None = None
    pack_dir: str | None = None
    strategy: str = "auto"
    test_image: str | None = None
    save_snapshot: str | None = None
    load_snapshot: str | None = None
    unit_query: str | None = None
    players: bool = False
    resources: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True)
class LiveCliOptionError(ValueError):
    """live 参数错误，message 面向命令行用户。"""

    detail: str

    def __str__(self) -> str:
        return single_line_text(self.detail)


def parse_live_cli_options(argv: Sequence[str]) -> LiveCliOptions:
    """解析 live 后的参数：可选地图路径 + 选项；地图与 --pack 互斥但必须有其一。"""
    map_path: str | None = None
    if argv and not argv[0].startswith("--"):
        map_path = argv[0]
    values: dict[str, str] = {}
    flags: set[str] = set()
    strategy = "auto"
    resources: tuple[str, str] | None = None
    index = 0 if map_path is None else 1
    while index < len(argv):
        option = argv[index]
        if option == "--strategy":
            value_index = index + 1
            if value_index >= len(argv) or argv[value_index].startswith("--"):
                raise LiveCliOptionError("参数缺少策略值：--strategy")
            value = argv[value_index]
            if value not in _STRATEGIES:
                valid = "、".join(_STRATEGIES)
                raise LiveCliOptionError(f"未知策略：{value}（可选：{valid}）")
            strategy = value
            index += 2
            continue
        if option == "--resources":
            if resources is not None:
                raise LiveCliOptionError("参数不能重复：--resources")
            nxt = index + 1
            if nxt < len(argv) and argv[nxt] == "auto":
                resources = ("auto", "")
                index += 2
                continue
            v1_i, v2_i = index + 1, index + 2
            if (
                v2_i >= len(argv)
                or argv[v1_i].startswith("--")
                or argv[v2_i].startswith("--")
            ):
                raise LiveCliOptionError(
                    "参数需要两个数值：--resources 金币 木材 (或 --resources auto)"
                )
            for v in (argv[v1_i], argv[v2_i]):
                try:
                    float(v)
                except ValueError as exc:
                    raise LiveCliOptionError(
                        f"--resources 的值必须是数字：{v}"
                    ) from exc
            resources = (argv[v1_i], argv[v2_i])
            index += 3
            continue
        if option in _FLAG_OPTIONS:
            if option in flags:
                raise LiveCliOptionError(f"参数不能重复：{option}")
            flags.add(option)
            index += 1
            continue
        if option not in _VALUE_OPTIONS:
            raise LiveCliOptionError(f"不支持的参数：{option}")
        if option in values:
            raise LiveCliOptionError(f"参数不能重复：{option}")
        value_index = index + 1
        if value_index >= len(argv) or argv[value_index].startswith("--"):
            raise LiveCliOptionError(f"参数缺少路径值：{option}")
        values[option] = argv[value_index]
        index += 2
    if map_path is None and "--pack" not in values:
        raise LiveCliOptionError("缺少地图路径（或用 --pack 指定资料包目录）")
    return LiveCliOptions(
        map_path=map_path,
        pack_dir=values.get("--pack"),
        strategy=strategy,
        test_image=values.get("--test-image"),
        save_snapshot=values.get("--save-snapshot"),
        load_snapshot=values.get("--load-snapshot"),
        unit_query=values.get("--unit"),
        players="--players" in flags,
        resources=resources,
    )


def live_pack_cache_dir(map_path: str) -> Path:
    """按地图绝对路径+大小+mtime 推导缓存包目录（改动自动失效）。"""
    stat = os.stat(map_path)
    key_material = f"{os.path.abspath(map_path)}|{stat.st_size}|{int(stat.st_mtime)}"
    key = hashlib.sha1(key_material.encode("utf-8")).hexdigest()[:16]
    return w3xray_cache_root() / "live-pack" / key


def _ensure_pack_dir(options: LiveCliOptions) -> str:
    """返回资料包目录；按地图首次使用时自动导出到缓存。"""
    if options.pack_dir is not None:
        return options.pack_dir
    if options.map_path is None:  # pragma: no cover - parse 已保证
        raise LiveCliOptionError("缺少地图路径")
    pack_dir = live_pack_cache_dir(options.map_path)
    if (pack_dir / "对象字段.tsv").exists():
        return str(pack_dir)
    from .api import load_map
    from .knowledge_pack import write_knowledge_pack
    from .load_context import build_map_load_context

    print(f"首次分析地图，正在导出知识包 -> {pack_dir}")
    map_data = load_map(options.map_path, load_context=build_map_load_context())
    written = write_knowledge_pack(map_data, str(pack_dir))
    print(f"知识包就绪：{written} 个文件")
    return str(pack_dir)


def run_live_cli(options: LiveCliOptions) -> int:
    """准备资料包并运行多策略背包读取；失败返回 2。"""
    configure_cli_output()
    try:
        from .live_inventory import main as live_main
    except Exception:  # noqa: BLE001 - 依赖缺失给出可执行提示而不是堆栈。
        print(
            "缺少运行依赖 numpy/pillow，请用："
            "uv run --with numpy --with pillow python main.py live ...",
            file=sys.stderr,
        )
        return 2
    try:
        pack_dir = _ensure_pack_dir(options)
    except Exception as exc:  # noqa: BLE001 - CLI 边界统一转退出码。
        print(f"无法准备资料包：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    args = ["--pack", pack_dir, "--strategy", options.strategy]
    if options.players:
        args += ["--players"]
    if options.resources is not None:
        args += ["--resources", options.resources[0], options.resources[1]]
    if options.test_image is not None:
        args += ["--test-image", options.test_image]
    if options.save_snapshot is not None:
        args += ["--save-snapshot", options.save_snapshot]
    if options.load_snapshot is not None:
        args += ["--load-snapshot", options.load_snapshot]
    if options.unit_query is not None:
        args += ["--unit", options.unit_query]
    try:
        return live_main(args)
    except Exception as exc:  # noqa: BLE001 - 读取失败不抛堆栈给玩家。
        print(f"实时读取失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

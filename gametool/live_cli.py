# -*- coding: utf-8 -*-
"""live 子命令：读取运行中游戏的主角背包（多策略、版本自适应）。

用法：
    uv run main.py live <地图路径> [--strategy auto|handle|chain|icons] [--test-image <截图>]
                        [--pack <资料包目录>] [--save-snapshot <目录>] [--load-snapshot <目录>]
                        [--unit <单位名|四码>] [--players] [--resources <金币> <木材>]
                        [--dump-objects <导出目录>] [--pid <PID>]

--dump-objects: 对运行中的游戏做只读内存快照并全量导出对象表
(物品/技能/单位/增益/科技) 为知识包 TSV——地图文件被平台壳加密
(如 KK 平台 CAME 伪装头) 静态解析不可用时的唯一全量读取路径。
导出后可直接: uv run python -X utf8 main.py pack-query <导出目录> item <名称>。

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

from .cache_root import gamexray_cache_root
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
    "--nick",
    "--export-profile",
    "--profile-json",
    "--pid",
    "--dump-objects",
)
_FLAG_OPTIONS = ("--all-units", "--players", "--elevated-hint")
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
    all_units: bool = False
    resources: tuple[str, str] | None = None
    nick: str | None = None
    export_profile: str | None = None
    profile_json: str | None = None
    pid: str | None = None
    elevated_hint: bool = False
    dump_objects: str | None = None


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
        if os.path.isdir(map_path):
            raise LiveCliOptionError(
                "live 的位置参数应是地图 .w3x 文件，收到目录: "
                + map_path
                + "；已导出的知识包请用 --pack <目录>"
            )
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
    return LiveCliOptions(
        map_path=map_path,
        pack_dir=values.get("--pack"),
        strategy=strategy,
        test_image=values.get("--test-image"),
        save_snapshot=values.get("--save-snapshot"),
        load_snapshot=values.get("--load-snapshot"),
        unit_query=values.get("--unit"),
        players="--players" in flags,
        all_units="--all-units" in flags,
        resources=resources,
        nick=values.get("--nick"),
        export_profile=values.get("--export-profile"),
        profile_json=values.get("--profile-json"),
        pid=values.get("--pid"),
        elevated_hint="--elevated-hint" in flags,
        dump_objects=values.get("--dump-objects"),
    )


LIVE_PACK_CACHE_VERSION = "live-pack-v22"


def live_pack_cache_dir(map_path: str) -> Path:
    """按版本+地图绝对路径+大小+mtime(纳秒) 推导缓存包目录。"""
    stat = os.stat(map_path)
    # v2: 满量纪律后的导出语义 (无摘要截断/全文索引)。代码修复救不了旧缓存,
    # 版本入键让旧包立刻退役, 下次 live 运行自动用新代码重导。
    # mtime 纳秒粒度: 同秒改写地图不吃旧包 (对齐 _ROWS_CACHE 指纹纪律)。
    key_material = f"{LIVE_PACK_CACHE_VERSION}|{os.path.abspath(map_path)}|{stat.st_size}|{stat.st_mtime_ns}"
    key = hashlib.sha1(key_material.encode("utf-8")).hexdigest()[:16]
    return gamexray_cache_root() / "live-pack" / key


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


def _int_or_none(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _auto_map_path() -> str | None:
    """未给地图路径/--pack 时自动定位正在使用的图 (仅接受唯一「直接证据」)。

    复用 current 的发现逻辑: 仅 FOUND 且唯一候选 (文件使用中) 才采用;
    SUGGESTED/AMBIGUOUS/NOT_FOUND 一律返回 None——不猜, 交调用方提示显式给路径。"""
    try:
        from .current_map_discovery import locate_current_map
        from .current_map_models import ResolutionStatus

        resolution = locate_current_map()
    except Exception:
        return None
    if resolution.status != ResolutionStatus.FOUND:
        return None
    if len(resolution.candidates) != 1:
        return None
    path = resolution.candidates[0].path
    return str(path) if path else None


def _resolve_auto_map(options: LiveCliOptions) -> LiveCliOptions:
    """两者都没给时尝试自动定位当前图; 失败保持原样 (由入口统一提示)。"""
    if options.map_path is not None or options.pack_dir is not None:
        return options
    path = _auto_map_path()
    if path is None:
        return options
    from dataclasses import replace

    print(f"未指定地图: 自动定位正在使用的图 -> {path}")
    return replace(options, map_path=path)


def run_live_cli(options: LiveCliOptions) -> int:
    """准备资料包并运行多策略背包读取；失败返回 2。"""
    configure_cli_output()
    if options.dump_objects is not None:
        # 内存对象表全量导出: 不需要地图/资料包 (地图可能根本解析不了,
        # CAME 壳地图正是本模式的目标用户)。
        from .live_object_dump import dump_live_objects

        result = dump_live_objects(options.dump_objects, _int_or_none(options.pid))
        return 0 if result.objects else 2
    if options.elevated_hint:
        target = options.map_path or options.pack_dir or "<地图路径>"
        print("--elevated-hint 提权运行参考（UAC 弹窗选“是”）：")
        print("  Start-Process pwsh -Verb RunAs -ArgumentList '-NoProfile','-Command',")
        print(
            '    \'$env:PYTHONIOENCODING="utf-8"; uv run python -X utf8 main.py live "'
            + target
            + "\"'"
        )
        print("注意: 重定向到文件时同样保持 PYTHONIOENCODING=utf-8，避免 GBK 乱码。")
        return 0
    try:
        from .live_inventory import main as live_main
    except Exception:
        print(
            "缺少运行依赖 numpy/pillow，请用："
            "uv run --with numpy --with pillow python main.py live ...",
            file=sys.stderr,
        )
        return 2
    options = _resolve_auto_map(options)
    if options.map_path is None and options.pack_dir is None:
        print(
            "未指定地图路径，且未能自动定位正在使用的图；请:"
            " main.py live <地图.w3x|.w3n> (或 --pack <资料包目录>)。"
            " 若游戏正停在主菜单 (未进图), 进图后重试——未加载的地图无使用中证据。",
            file=sys.stderr,
        )
        return 2
    try:
        pack_dir = _ensure_pack_dir(options)
    except Exception as exc:
        print(f"无法准备资料包：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    args = ["--pack", pack_dir, "--strategy", options.strategy]
    if options.players:
        args += ["--players"]
    if options.all_units:
        args += ["--all-units"]
    if options.resources is not None:
        if options.resources == ("auto", ""):
            args += ["--resources", "auto"]
        else:
            args += ["--resources", options.resources[0], options.resources[1]]
    if options.test_image is not None:
        args += ["--test-image", options.test_image]
    if options.save_snapshot is not None:
        args += ["--save-snapshot", options.save_snapshot]
    if options.load_snapshot is not None:
        args += ["--load-snapshot", options.load_snapshot]
    if options.unit_query is not None:
        args += ["--unit", options.unit_query]
    if options.nick is not None:
        args += ["--nick", options.nick]
    if options.export_profile is not None:
        args += ["--export-profile", options.export_profile]
    if options.profile_json is not None:
        args += ["--profile-json", options.profile_json]
    if options.pid is not None:
        args += ["--pid", options.pid]
    try:
        return live_main(args)
    except Exception as exc:
        print(f"实时读取失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

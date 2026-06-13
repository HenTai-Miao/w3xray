"""魔兽地图提取器 — 程序入口。

直接运行启动 GUI；带参数 `cli <地图路径>` 时走命令行快速查看。
"""
import sys


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "cli":
        from w3xtool.api import load_map
        md = load_map(sys.argv[2])
        print("地图:", md.name)
        if md.w3i:
            w = md.w3i
            print(f"  作者: {w.author or '未知'}  脚本: {w.script_type or '?'}"
                  f"  玩家: {len(w.players)}  队伍: {len(w.forces)}  尺寸: {w.width}×{w.height}")
        for cat, objs in md.objects.items():
            print(f"  {cat}: {len(objs)}")
        if md.units or md.doodads:
            print(f"  预放置单位: {len(md.units)}  装饰物/可破坏物: {len(md.doodads)}")
        return
    from w3xtool.single_instance import ensure_single_instance
    ensure_single_instance()          # 单实例：先关掉上一个实例再启动，不允许多开
    from w3xtool.gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()

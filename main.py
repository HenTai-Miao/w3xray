"""魔兽地图提取器 — 程序入口。

直接运行启动 GUI；带参数 `cli <地图路径>` 时走命令行快速查看。
"""
import sys


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "cli":
        from w3xtool.api import load_map
        md = load_map(sys.argv[2])
        print("地图:", md.name)
        for cat, objs in md.objects.items():
            print(f"  {cat}: {len(objs)}")
        return
    from w3xtool.gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()

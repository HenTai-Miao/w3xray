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
        if getattr(md, "script_features", None):
            print(f"  脚本特征: {'、'.join(md.script_features)}")
        # 引用分析：引用边数 + 孤立自定义对象
        refs = getattr(md, "references", {}) or {}
        orphans = getattr(md, "orphans", []) or []
        if refs or orphans:
            edges = sum(len(codes) for entries in refs.values()
                        for _label, codes in entries)
            print(f"  引用关系: {len(refs)} 个对象有引用 · {edges} 条引用边")
            if getattr(md, "ref_low_coverage", False):
                print(f"  孤立自定义对象: {len(orphans)}（⚠ 引用覆盖低，疑为 SLK 优化图，"
                      "多为误报，仅供参考）")
            else:
                print(f"  孤立自定义对象: {len(orphans)}"
                      + ("（无人引用，可能是废弃对象）" if orphans else ""))
            for o in orphans[:10]:
                print(f"    - [{o.category}] {o.name}({o.obj_id})")
            if len(orphans) > 10:
                print(f"    …… 另有 {len(orphans) - 10} 个")
        return
    from w3xtool.single_instance import ensure_single_instance
    ensure_single_instance()          # 单实例：先关掉上一个实例再启动，不允许多开
    from w3xtool.gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()

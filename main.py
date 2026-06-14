"""魔兽地图提取器 — 程序入口。

直接运行启动 GUI；带参数 `cli <地图路径>` 时走命令行快速查看。
"""
import sys


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "cli":
        # 控制台输出编码处理：
        #  - 交互控制台(isatty)：保留原编码(中文 Windows 多为 cp936，中文照常显示)，
        #    仅把不可编码字符(如 emoji)降级为占位，避免 print 硬崩。
        #  - 重定向/管道(非 tty)：统一用 UTF-8，便于现代工具/文件读取(否则打包 exe 重定向
        #    时会写出 cp936 字节，UTF-8 读者看到乱码)。
        try:
            out = sys.stdout
            if out is not None:
                if out.isatty():
                    out.reconfigure(errors="replace")
                else:
                    out.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        from w3xtool.api import load_map
        try:
            md = load_map(sys.argv[2])
        except Exception as e:
            # 非法/损坏/空文件等：给一句友好提示，而非抛裸 traceback(GUI 已优雅处理，CLI 也对齐)
            print(f"无法解析地图：{type(e).__name__}: {e}")
            return
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
                print(f"  孤立自定义对象: {len(orphans)}（注意：引用覆盖低，疑为 SLK 优化图，"
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

"""深度质量审计：批量解析地图，报告内容正确性/完整性信号（不只看能否加载）。

用法： uv run python tools_audit.py [目录]   默认 C:/Users/zhongerbing/Downloads
"""
import sys, io, glob, os, struct, contextlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from w3xtool.api import load_map, commands_from_map, recipes_from_map

EXPECT_VER = {1, 2, 3}


def name_quality(objs):
    """返回 (有真名数, 无名/裸ID数, 乱码数)。"""
    good = bad = mojibake = 0
    for o in objs:
        nm = o.name or ""
        if "�" in nm:
            mojibake += 1
        if (not nm) or nm.startswith("ID:") or nm == o.obj_id or nm == o.base_id:
            bad += 1
        else:
            good += 1
    return good, bad, mojibake


def audit_one(mp):
    name = os.path.basename(mp)
    sz = round(os.path.getsize(mp) / 1048576, 1)
    warn = io.StringIO()
    try:
        with contextlib.redirect_stderr(warn):
            md = load_map(mp)
    except Exception as e:
        return dict(name=name, sz=sz, status="FAIL", err=repr(e)[:80])
    allobj = [o for v in md.objects.values() for o in v]
    good, bad, moji = name_quality(allobj)
    cats = {k: len(v) for k, v in md.objects.items() if v}
    try:
        ncmd = len(commands_from_map(md))
        nrec = len(recipes_from_map(md))
    except Exception:
        ncmd = nrec = -1
    warns = [l for l in warn.getvalue().splitlines() if l.strip()]
    return dict(name=name, sz=sz, status="OK", tot=len(allobj), cats=cats,
                good=good, bad=bad, moji=moji, ncmd=ncmd, nrec=nrec,
                scripts=list(md.scripts.keys()), warns=warns)


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/zhongerbing/Downloads"
    maps = sorted(glob.glob(d + "/*.w3x") + glob.glob(d + "/*.w3m") + glob.glob(d + "/*.w3n"))
    print(f"=== 审计 {len(maps)} 张图 @ {d} ===\n")
    fails, mojis, lowname, warned, noobj, noscript = [], [], [], [], [], []
    for mp in maps:
        r = audit_one(mp)
        if r["status"] == "FAIL":
            fails.append(r)
            print(f"[FAIL] {r['name']} ({r['sz']}MB) -> {r['err']}")
            continue
        tot, good, bad, moji = r["tot"], r["good"], r["bad"], r["moji"]
        rate = good / tot * 100 if tot else 0
        flag = ""
        if moji > 0:
            mojis.append(r); flag += f" ⚠乱码{moji}"
        if tot and rate < 80:
            lowname.append(r); flag += f" ⚠名字解析{rate:.0f}%"
        if r["warns"]:
            warned.append(r); flag += f" ⚠告警{len(r['warns'])}"
        if tot == 0:
            noobj.append(r); flag += " ⚠零对象"
        if not any(s in r["scripts"] for s in ("war3map.j", "war3map.lua")):
            noscript.append(r); flag += " ⚠无脚本"
        print(f"[OK] {r['name']} ({r['sz']}MB) 对象={tot} 真名={good}({rate:.0f}%) "
              f"指令={r['ncmd']} 配方={r['nrec']}{flag}")
        if r["warns"]:
            for w in r["warns"][:3]:
                print("        告警:", w)

    print("\n=== 汇总 ===")
    print(f"总计 {len(maps)} | 失败 {len(fails)} | 乱码 {len(mojis)} | "
          f"低解析率 {len(lowname)} | 有告警 {len(warned)} | 零对象 {len(noobj)} | 无脚本 {len(noscript)}")
    for tag, lst in [("失败", fails), ("乱码", mojis), ("低解析率", lowname),
                     ("零对象", noobj), ("无脚本", noscript)]:
        if lst:
            print(f"  [{tag}] " + ", ".join(x["name"] for x in lst))


if __name__ == "__main__":
    main()

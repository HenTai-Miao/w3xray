# -*- coding: utf-8 -*-
"""hero_chain: 版本无关的英雄背包结构启发式读取 (live_inventory 策略 B)。

原理 (经典 1.07~1.31 引擎通用, 不依赖绝对地址):
1. 少量物品中文名 (GBK) 作为锚点串 -> 全内存定位其实例;
2. "指向名字串的 dword" 就是对象定义(def)结构里的名字指针; 在其附近找同一物品的
   四码, 距离的众数 = def 内四码偏移 -> 由此把所有目录区四码换算成 def 起址;
3. 全内存找"指向 def 起址"的 dword, 排除 16 字节步长句柄哈希表后 = 活着的 CItem
   对象的 def 字段地址;
4. CItem 基址 = def 字段地址 - k (k 未知); 背包槽位数组 = 4~6 个连续 dword 指向
   若干 CItem 基址。用 delta 直方图一次性解出 k, 不做多次全扫;
5. 槽位数组拥有者附近若有指向单位 def 的指针 -> 英雄验证 (O002/单位表)。
"""

# pyright: reportMissingImports=false
import re
import sys

from collections import Counter, defaultdict

import numpy as np


def clean(s):
    """剥掉 |cXXXXXXXX / |r 颜色码。"""
    o, i = [], 0
    while i < len(s):
        if s.startswith("|c", i) and len(s) - i >= 10:
            i += 10
        elif s.startswith("|r", i):
            i += 2
        else:
            o.append(s[i])
            i += 1
    return "".join(o)


def _sample(names, want, min_len=3):
    cands = [
        (code, n)
        for code, n in names.items()
        if len(n) >= min_len and re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9·+-]+", n)
    ]
    cands.sort(key=lambda kv: -len(kv[1]))
    return cands[:want]


def _find_instances(regions, pats):
    """每个名字的全部出现位置; 去掉被更长名字包含的短命中。"""
    found = []
    for code, n in pats:
        enc = n.encode("gbk", errors="ignore")
        if len(enc) < 4:
            continue
        for base, data in regions:
            off = data.find(enc)
            while off != -1:
                found.append((base + off, len(enc), code))
                off = data.find(enc, off + 1)
    found.sort(key=lambda t: (t[0], -t[1]))
    out = []
    last_end = -1
    for addr, ln, code in found:
        if addr < last_end:
            continue
        out.append((addr, ln, code))
        last_end = addr + ln
    return out


def _u32(data):
    return np.frombuffer(data, dtype="<u4").astype(np.uint64)


def _sources_to(targets_arr, regions, window=0):
    """全内存一遍: 返回 (src, val) 其中 val == targets_arr 中某值。"""
    srcs_all, vals_all = [], []
    for base, data in regions:
        if len(data) < 4:
            continue
        arr = _u32(data)
        idx = np.searchsorted(targets_arr, arr)
        ok = idx < len(targets_arr)
        srcs = np.arange(arr.size, dtype=np.uint64) * 4 + base
        m = targets_arr[idx[ok]] == arr[ok]
        if m.any():
            srcs_all.append(srcs[ok][m])
            vals_all.append(arr[ok][m])
    if not srcs_all:
        return np.array([], dtype=np.uint64), np.array([], dtype=np.uint64)
    return np.concatenate(srcs_all), np.concatenate(vals_all)


def _sources_into_windows(starts, size, regions):
    """全内存一遍: 收集值落入任一 [s, s+size) 窗口的 dword -> (src, val, win_idx)。"""
    srcs_all, vals_all, idxs_all = [], [], []
    for base, data in regions:
        if len(data) < 4:
            continue
        arr = _u32(data)
        pos = np.searchsorted(starts, arr, side="right") - 1
        ok = (pos >= 0) & (arr <= starts[np.clip(pos, 0, len(starts) - 1)] + size)
        ok &= pos >= 0
        if not ok.any():
            continue
        srcs = np.arange(arr.size, dtype=np.uint64)[ok] * 4 + base
        srcs_all.append(srcs)
        vals_all.append(arr[ok])
        idxs_all.append(pos[ok].astype(np.int64))
    if not srcs_all:
        return (np.array([], dtype=np.uint64),) * 2 + (np.array([], dtype=np.int64),)
    return np.concatenate(srcs_all), np.concatenate(vals_all), np.concatenate(idxs_all)


def _learn_def_layout(
    regions, names, verbose=False, min_anchors=5, min_votes=3, fc_codes=None
):
    """返回 (d, off_nameptr) 或 None; fc_codes 指定时按其收集四码位置(单位表用)。"""
    anchors = _find_instances(regions, _sample(names, 80))
    if len(anchors) < min_anchors:
        if verbose:
            print(f"锚点串不足 ({len(anchors)})")
        return None
    addr_arr = np.array([a for a, _, _ in anchors], dtype=np.uint64)
    srcs, vals = _sources_to(addr_arr, regions)
    if verbose:
        print(f"锚点 {len(anchors)}, 名字指针来源 {len(srcs)}")
    if len(srcs) < min_anchors:
        return None
    fc_pos = defaultdict(list)
    if fc_codes:
        alt = b"|".join(
            re.escape(bytes(c)) for c in sorted(fc_codes, key=len, reverse=True)
        )
        pat = re.compile(rb"(?:" + alt + rb")" if alt else rb"$^")
    else:
        pat = re.compile(rb"I0..")
    for base, data in regions:
        for m in pat.finditer(data):
            fc_pos[m.group()].append(base + m.start())
    dist = Counter()
    anchor_addr2code = {a: c for a, _, c in anchors}
    for s, v in zip(srcs.tolist(), vals.tolist()):
        code = anchor_addr2code.get(v)
        if not code:
            continue
        for pos in fc_pos.get(code, ())[:8]:
            d = pos - s
            if -0x200 <= d <= 0x200 and d % 4 == 0:
                dist[d] += 1
    if verbose:
        print("名字指针->四码 距离 top:", dist.most_common(4))
    if not dist or dist.most_common(1)[0][1] < min_votes:
        return None
    d = dist.most_common(1)[0][0]
    # 再学 off_nameptr: 指向 def 头的指针落在名字指针字段(pivot)前 0x200 内
    pivots = np.array(
        sorted(
            {s for s, v in zip(srcs.tolist(), vals.tolist()) if anchor_addr2code.get(v)}
        ),
        dtype=np.uint64,
    )
    offs = Counter()
    if len(pivots):
        psrc, pval, _ = _sources_into_windows(pivots - np.uint64(0x200), 0x204, regions)
        for v2 in pval.tolist():
            # 指针目标在 pivot 下方: 找 >= v2 的最小 pivot (窗口主)
            i = int(np.searchsorted(pivots, np.uint64(v2), side="left"))
            if i >= len(pivots):
                continue
            off = int(pivots[i]) - v2
            if 0 <= off <= 0x200 and off % 4 == 0:
                offs[off] += 1
    off_np = (
        offs.most_common(1)[0][0]
        if offs and offs.most_common(1)[0][1] >= min_votes
        else 0
    )
    if verbose:
        print(f"def 布局: d={d} off_np={off_np} 投票 {offs.most_common(3)}")
    return d, off_np


def read_inventory(regions, names, unit_names=None, verbose=False):
    """返回 [{slot_array, verified, items: [{name, fourcc}]}]"""
    learned = _learn_def_layout(regions, names, verbose)
    if learned is None:
        if verbose:
            print("def 布局学习失败")
        return []
    d_item, off_np = learned
    # 目录桶 (四码密集区) = def 结构所在
    buck = defaultdict(set)
    hits = []
    for base, data in regions:
        for m in re.finditer(rb"I0..", data):
            a = base + m.start()
            hits.append((a, data[m.start() : m.start() + 4]))
            buck[a >> 16].add(data[m.start() : m.start() + 4])
    catb = {b for b, cs in buck.items() if len(cs) >= 6}
    def_starts = {}
    for a, code in hits:
        if (a >> 16) in catb:
            def_starts[a - d_item - off_np] = code
    if verbose:
        print(f"def 起址 {len(def_starts)} 个 (d={d_item}, off_np={off_np})")
    if len(def_starts) < 8:
        return []
    # CItem: 指向 def 起址的 dword; 排除 16 字节步长哈希表来源
    targets = np.array(sorted(def_starts), dtype=np.uint64)
    srcs, vals = _sources_to(targets, regions)
    if verbose:
        print(f"def 指针 {len(srcs)} 个")
    order = np.argsort(srcs)
    srcs, vals = srcs[order], vals[order]
    keep = np.ones(len(srcs), dtype=bool)
    if len(srcs) > 2:
        gaps = np.diff(srcs)
        run16 = gaps == 16
        for i in range(len(gaps) - 1):
            if run16[i] and run16[i + 1]:
                keep[i : i + 3] = False
    live_src = srcs[keep].tolist()
    live_val = vals[keep].tolist()
    if verbose:
        print(f"非哈希表来源 (CItem def字段) {len(live_src)}")
    if len(live_src) < 4:
        return []
    addr2code = {}
    for s, v in zip(live_src, live_val):
        addr2code[s] = def_starts[v]
    # 槽位数组: 一次窗口扫描 + delta 直方图解 k
    centers = np.array(sorted(addr2code), dtype=np.uint64)
    size = np.uint64(0x240)
    psrcs, pvals, widx = _sources_into_windows(
        centers - np.uint64(0x20), int(size) + 0x40, regions
    )
    results = []
    if len(psrcs):
        deltas = centers[widx] - pvals
        cand = Counter()
        for d in deltas.tolist():
            if 0 <= d <= 0x200 and d % 4 == 0:
                cand[d] += 1
        for k2, _cnt in cand.most_common(12):
            sel = deltas == np.uint64(k2)
            src_sel = psrcs[sel]
            val_sel = pvals[sel]
            order = np.argsort(src_sel)
            src_sel, val_sel = src_sel[order], val_sel[order]
            if len(src_sel) < 4:
                continue
            g = np.diff(src_sel)
            bnd = np.concatenate(([0], np.nonzero(g != 4)[0] + 1, [len(src_sel)]))
            for ri in range(len(bnd) - 1):
                s, e = int(bnd[ri]), int(bnd[ri + 1])
                if not (4 <= e - s <= 6):
                    continue
                items = []
                for t in val_sel[s:e].tolist():
                    code = None
                    for kk in range(0, 0x204, 4):
                        code = addr2code.get(t + kk)
                        if code:
                            break
                    if code:
                        nm = names.get(code)
                        nm = (
                            clean(nm)
                            if isinstance(nm, str)
                            else code.decode(errors="replace")
                        )
                    else:
                        nm = "?"
                    items.append(
                        {
                            "fourcc": code.decode(errors="replace") if code else "?",
                            "name": nm,
                        }
                    )
                results.append(
                    {
                        "slot_array": hex(int(src_sel[s])),
                        "k": k2,
                        "verified": False,
                        "items": items,
                    }
                )
    if not results:
        return []
    # 英雄验证: 槽位数组附近找指向单位 def 的指针
    if unit_names:
        ulearned = _learn_def_layout(
            regions,
            unit_names,
            verbose=False,
            min_anchors=1,
            min_votes=1,
            fc_codes=list(unit_names),
        )
        if ulearned is not None:
            d_unit, u_np = ulearned
            unit_fc = defaultdict(list)
            for base, data in regions:
                for code in unit_names:
                    off = data.find(code)
                    while off != -1:
                        unit_fc[code].append(base + off)
                        off = data.find(code, off + 1)
            udefs = []
            for code, poss in unit_fc.items():
                for p in poss[:4]:
                    udefs.append(p - d_unit - u_np)
            if udefs:
                ut = np.array(sorted(set(udefs)), dtype=np.uint64)
                usrcs, _uvals = _sources_to(ut, regions)
                for r in results:
                    sa = int(r["slot_array"], 16)
                    if np.any((usrcs > sa - 0x800) & (usrcs < sa + 0x800)):
                        r["verified"] = True
    results.sort(key=lambda r: (not r["verified"], -len(r["items"])))
    return results


def main():
    import argparse
    import json
    from .live_inventory import (
        find_war3_pid,
        load_names,
        load_snapshot,
        mem_setup,
        open_process,
        snapshot,
    )

    ap = argparse.ArgumentParser(description="结构启发式背包读取 (策略 B)")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--load-snapshot", help="离线快照目录")
    ap.add_argument("--save-snapshot", help="保存快照目录")
    args = ap.parse_args()
    if args.load_snapshot:
        regions = load_snapshot(args.load_snapshot)
        print("离线快照", sum(len(d) for _, d in regions) // 1048576, "MB")
    else:
        mem_setup()
        pids = find_war3_pid()
        if not pids:
            print("war3 未运行")
            return 1
        h = open_process(pids[0])
        regions, total = snapshot(h)
        print(f"pid {pids[0]} 快照 {total // 1048576}MB")
        if args.save_snapshot:
            from .live_inventory import save_snapshot

            print("存:", save_snapshot(regions, args.save_snapshot))
    names = load_names(args.pack)
    unit_names = load_names(args.pack, "单位")
    res = read_inventory(regions, names, unit_names=unit_names, verbose=True)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res else 2


if __name__ == "__main__":
    sys.exit(main())

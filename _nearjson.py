import pathlib

NL = chr(13) + chr(10)
p = pathlib.Path("gametool/pack_query_cli.py")
data = p.read_text(encoding="utf-8", newline="")

# ① 解析器函数 (插在 _FN_HEAD_RE 前)
old1 = '_FN_HEAD_RE = re.compile('
parser = (
    '_NEAR_ROW_RE = re.compile(' + NL
    + '    r"^\\s*(单位|装饰|装饰群|脚本单位|脚本物品):\\s*(.+?)\\s*\\[(\\w+)\\]' + NL
    + '    r"(?:\\s*×(\\d+))?\\s*@\\((-?[\\d.]+),(-?[\\d.]+)\\)(?:\\s*距(\\d+))?"' + NL
    + ')"' + NL
    + ')' + NL
    + NL
    + NL
)
assert data.count(old1) == 1, "anchor1"
data = data.replace(old1, parser + old1, 1)

# ② near --json 特判 (run_pack_query_cli 前的 _run_query_inner 里 again 分支后)
old2 = (
    "    if options.command == \"again\":" + NL
    + "        # again 的 pack 参数来自 memo, 当前 pack_dir 只作显示" + NL
    + "        lines = _query_again(pack, options.query, options.limit)" + NL
    + "        _emit_lines(lines, options.as_json)" + NL
    + "        return 0"
)
new2 = (
    "    if options.command == \"near\" and options.as_json:" + NL
    + "        # near 结构化输出: entries 数组供脚本/AI 消费 (文本行照附)" + NL
    + "        lines = _query_near(pack, options.query, options.limit)" + NL
    + "        entries = []" + NL
    + "        for line in lines:" + NL
    + "            m = _NEAR_ROW_RE.match(line)" + NL
    + "            if m:" + NL
    + "                entries.append(" + NL
    + "                    {" + NL
    + "                        \"kind\": m.group(1)," + NL
    + "                        \"name\": m.group(2).strip()," + NL
    + "                        \"code\": m.group(3)," + NL
    + "                        \"count\": int(m.group(4) or 1)," + NL
    + "                        \"x\": float(m.group(5))," + NL
    + "                        \"y\": float(m.group(6))," + NL
    + "                        \"dist\": int(m.group(7) or 0)," + NL
    + "                        \"detail\": line.strip()," + NL
    + "                    }" + NL
    + "                )" + NL
    + "        print(" + NL
    + "            json.dumps(" + NL
    + "                {\"section\": \"near\", \"entries\": entries, \"lines\": lines}," + NL
    + "                ensure_ascii=False," + NL
    + "            )" + NL
    + "        )" + NL
    + "        return 0 if len(entries) else 2" + NL
    + old2
)
assert data.count(old2) == 1, "anchor2"
data = data.replace(old2, new2, 1)
p.write_text(data, encoding="utf-8", newline="")
print("near json wired")

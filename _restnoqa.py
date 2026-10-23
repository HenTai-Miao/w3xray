import pathlib
import re
import subprocess

NL = chr(13) + chr(10)
diff = subprocess.run(
    ["git", "diff", "HEAD~1", "HEAD", "--", "gametool/", "tests/", "main.py", "tools/"],
    capture_output=True, text=True,
).stdout
REAL = ("BLE001", "PLC0415", "RUF012", "E402", "S110", "S603", "S608")
current_file = None
old_pending: list[str] = []
new_pending: list[str] = []
restore_count = 0
files_patched: set[str] = set()

def flush(f: str | None):
    global restore_count
    if f is None:
        return
    # 配对: 每个 -行带真 noqa, 找 + 行 = 去 noqa 的同语句
    for old in old_pending:
        m = re.match(r"^(.*?\S)(\s+# noqa: ([A-Z0-9, -]+))(\s+# .*)?$", old)
        if not m:
            continue
        codes = m.group(3)
        keep = [c for c in re.split(r"[,\s]+", codes) if c in REAL]
        if not keep:
            continue
        base = m.group(1)
        suffix = m.group(4) or ""
        suffix_clean = suffix.replace("BROAD_EXCEPT_OK", "BROAD_EXCEPT_OK")
        # 在 new_pending 里找去 noqa 后匹配的行
        for idx, new in enumerate(new_pending):
            new_body = re.sub(r"\s+# noqa: [A-Z0-9, -]+", "", new)
            if new_body == base + suffix_clean or new_body == base:
                new_pending[idx] = base + "  # noqa: " + ", ".join(keep) + suffix_clean
                restore_count += 1
                files_patched.add(f)
                break

for raw in diff.splitlines():
    if raw.startswith("diff --git"):
        flush(current_file)
        m = re.match(r"diff --git a/(.+?) b/(.+?)$", raw)
        current_file = m.group(2) if m else None
        old_pending, new_pending = [], []
    elif raw.startswith("---") or raw.startswith("+++") or raw.startswith("@@"):
        continue
    elif raw.startswith("-"):
        old_pending.append(raw[1:])
    elif raw.startswith("+"):
        new_pending.append(raw[1:])
flush(current_file)

for rel in files_patched:
    p = pathlib.Path(rel)
    p.write_text(p.read_text(encoding="utf-8", newline=""), encoding="utf-8", newline="")
print("wait — 上面只是统计; 重写为两阶段")

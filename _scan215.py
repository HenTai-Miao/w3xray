"""一次性: 逐个试摘 pyproject ignore 豁免, 统计摘除后暴露的 pyright 错误数。

ignore 是文件级全豁免 — 目标: 已被收录且行级防护到位的文件应摘除豁免,
恢复其 pyright 检查; 摘除后错误多的文件保留豁免并在名单旁注明原因。
"""
import json
import pathlib
import subprocess
import sys

IGNORE_FILES = [
    "tests/test_batch_runtime.py",
    "tests/test_external_listfile_gui.py",
    "tests/test_gui_casc_browser.py",
    "tests/test_gui_casc_worker.py",
    "tests/test_gui_export_worker.py",
    "tests/test_gui_object_filter_runner.py",
    "gametool/gui.py",
    "gametool/gui_casc_browser.py",
    "gametool/gui_export_actions.py",
    "gametool/gui_external_data.py",
    "gametool/gui_lifecycle.py",
    "gametool/gui_profile_settings.py",
    "gametool/gui_source_browser.py",
    "gametool/gui_topbar.py",
]

results = {}
for f in IGNORE_FILES:
    r = subprocess.run(
        [sys.executable, "-m", "basedpyright", "--outputjson", f],
        capture_output=True, text=True, timeout=600,
    )
    try:
        d = json.loads(r.stdout)
        errs = [x for x in d.get("generalDiagnostics", []) if x.get("severity") == "error"]
        results[f] = len(errs)
    except Exception as exc:
        results[f] = -1
    print(f"{results[f]:5}  {f}")

print("=== 零错误可摘 ===")
for f, n in results.items():
    if n == 0:
        print(" ", f)

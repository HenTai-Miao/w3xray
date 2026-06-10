"""AI 自改进编排：诊断→组装提示→调 AI→存建议。用假 echo CLI 离线验证全链路。"""
import os
import sys
import tempfile
import unittest

from w3xtool.aicli.improve import (attribute, build_prompt, load_prompt,
                                   save_suggestion)
from w3xtool.aicli.runner import AIProfile, AIResult
from w3xtool.api import GameObject, MapData
from w3xtool.audit import diagnose

PY = [sys.executable, "-X", "utf8"]


def _diag():
    md = MapData(path="p", name="测试图",
                 objects={"物品": [GameObject("物品", "w3t", "I001", "I001", "药水", False)]},
                 scripts={"war3map.j": "f"})
    return diagnose(md, ["war3map.w3u", "war3map.t"])   # w3u 缺口


class TestPromptHelpers(unittest.TestCase):
    def test_build_prompt_injects_report(self):
        out = build_prompt("前缀\n{report}\n后缀", _diag())
        self.assertIn("前缀", out)
        self.assertIn("测试图", out)        # 报告被注入
        self.assertNotIn("{report}", out)

    def test_load_prompt_reads_shipped_template(self):
        txt = load_prompt("attribution")
        self.assertIn("{report}", txt)      # 模板含占位


class TestSaveSuggestion(unittest.TestCase):
    def test_writes_report_and_ai_output(self):
        with tempfile.TemporaryDirectory() as d:
            res = AIResult(ok=True, stdout="AI 的修复建议在这里", exit_code=0)
            folder = save_suggestion(d, "测试图", "诊断报告正文", res)
            self.assertTrue(os.path.isdir(folder))
            files = os.listdir(folder)
            blob = "".join(open(os.path.join(folder, f), encoding="utf-8").read() for f in files)
            self.assertIn("诊断报告正文", blob)
            self.assertIn("AI 的修复建议在这里", blob)


class TestAttributeEndToEnd(unittest.TestCase):
    def test_attribute_with_fake_cli_creates_suggestion(self):
        # 假 CLI：把 stdin(=提示词) 原样吐回 → AI 输出里应含报告内容
        prof = AIProfile(name="echo",
                         command=[*PY, "-c", "import sys;print(sys.stdin.read())"],
                         input_mode="stdin")
        with tempfile.TemporaryDirectory() as d:
            folder, res = attribute(_diag(), prof, out_root=d)
            self.assertTrue(res.ok, res.error)
            self.assertTrue(os.path.isdir(folder))
            blob = "".join(open(os.path.join(folder, f), encoding="utf-8").read()
                           for f in os.listdir(folder))
            self.assertIn("测试图", blob)          # 报告进了提示、回显、并存档


if __name__ == "__main__":
    unittest.main()

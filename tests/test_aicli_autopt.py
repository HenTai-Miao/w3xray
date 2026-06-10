"""AI 全自动优化:抽 diff + 应用→测试→提交/回滚。用真实临时 git 仓库离线验证。"""
import os
import subprocess
import sys
import tempfile
import unittest

from w3xtool.aicli.autopt import apply_test_and_commit, extract_diff

PY = [sys.executable, "-X", "utf8"]
PASS = [*PY, "-c", "import sys;sys.exit(0)"]
FAIL = [*PY, "-c", "import sys;sys.exit(1)"]


class TestExtractDiff(unittest.TestCase):
    def test_fenced_diff_block(self):
        text = "随便说点\n```diff\ndiff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n```\n收尾"
        d = extract_diff(text)
        self.assertIn("diff --git a/x.py", d)
        self.assertNotIn("随便说点", d)

    def test_raw_diff_without_fence(self):
        text = "前言\ndiff --git a/y.py b/y.py\n--- a/y.py\n+++ b/y.py\n@@ -1 +1 @@\n-1\n+2\n"
        d = extract_diff(text)
        self.assertTrue(d.startswith("diff --git a/y.py"))

    def test_no_diff_returns_empty(self):
        self.assertEqual(extract_diff("这里完全没有补丁，只是普通文字"), "")


class TestApplyTestCommit(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self._git("init", "-q")
        self._git("config", "user.email", "t@t.t")
        self._git("config", "user.name", "t")
        with open(os.path.join(self.repo, "f.txt"), "w", encoding="utf-8") as fp:
            fp.write("hello\n")
        self._git("add", "-A")
        self._git("commit", "-qm", "init")

    def _git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")

    def _diff_change_f(self):
        # 把 f.txt 的 hello 改成 world 的统一 diff
        return ("diff --git a/f.txt b/f.txt\n--- a/f.txt\n+++ b/f.txt\n"
                "@@ -1 +1 @@\n-hello\n+world\n")

    def test_apply_pass_commits(self):
        r = apply_test_and_commit(self.repo, self._diff_change_f(), PASS, "改了 f")
        self.assertTrue(r.ok, r.message)
        self.assertEqual(r.stage, "committed")
        with open(os.path.join(self.repo, "f.txt"), encoding="utf-8") as fp:
            self.assertEqual(fp.read(), "world\n")        # 改动已落地
        self.assertIn("改了 f", self._git("log", "-1", "--pretty=%s").stdout)

    def test_tests_fail_rolls_back(self):
        r = apply_test_and_commit(self.repo, self._diff_change_f(), FAIL, "不该提交")
        self.assertFalse(r.ok)
        self.assertEqual(r.stage, "tests-failed")
        with open(os.path.join(self.repo, "f.txt"), encoding="utf-8") as fp:
            self.assertEqual(fp.read(), "hello\n")         # 已回滚
        self.assertNotIn("不该提交", self._git("log", "-1", "--pretty=%s").stdout)

    def test_unapplicable_diff_rolls_back(self):
        bad = ("diff --git a/f.txt b/f.txt\n--- a/f.txt\n+++ b/f.txt\n"
               "@@ -1 +1 @@\n-不存在的内容\n+x\n")
        r = apply_test_and_commit(self.repo, bad, PASS, "x")
        self.assertFalse(r.ok)
        self.assertEqual(r.stage, "apply-failed")
        with open(os.path.join(self.repo, "f.txt"), encoding="utf-8") as fp:
            self.assertEqual(fp.read(), "hello\n")         # 原样

    def test_dirty_tree_aborts(self):
        with open(os.path.join(self.repo, "f.txt"), "a", encoding="utf-8") as fp:
            fp.write("uncommitted\n")
        r = apply_test_and_commit(self.repo, self._diff_change_f(), PASS, "x")
        self.assertFalse(r.ok)
        self.assertEqual(r.stage, "dirty")                 # 保护未提交改动

    def test_empty_diff_no_op(self):
        r = apply_test_and_commit(self.repo, "", PASS, "x")
        self.assertFalse(r.ok)
        self.assertEqual(r.stage, "no-diff")


if __name__ == "__main__":
    unittest.main()

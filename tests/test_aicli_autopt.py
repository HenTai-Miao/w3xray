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

    def test_raw_diff_trailing_prose_truncated(self):
        text = ("diff --git a/z.py b/z.py\n--- a/z.py\n+++ b/z.py\n@@ -1 +1 @@\n-a\n+b\n"
                "\n以上就是修改说明，希望对你有帮助。")
        d = extract_diff(text)
        self.assertIn("+b", d)
        self.assertNotIn("以上就是修改说明", d)        # 尾部解释被截掉


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

    def test_rejects_diff_touching_tests(self):
        # AI 改测试以让坏改动"过门禁" → 必须拒绝（门禁要保持诚实）
        os.makedirs(os.path.join(self.repo, "tests"), exist_ok=True)
        with open(os.path.join(self.repo, "tests", "t.py"), "w", encoding="utf-8") as fp:
            fp.write("x=1\n")
        self._git("add", "-A")
        self._git("commit", "-qm", "add test")
        bad = ("diff --git a/tests/t.py b/tests/t.py\n--- a/tests/t.py\n+++ b/tests/t.py\n"
               "@@ -1 +1 @@\n-x=1\n+x=2\n")
        r = apply_test_and_commit(self.repo, bad, PASS, "改测试")
        self.assertFalse(r.ok)
        self.assertEqual(r.stage, "rejected-scope")
        with open(os.path.join(self.repo, "tests", "t.py"), encoding="utf-8") as fp:
            self.assertEqual(fp.read(), "x=1\n")        # 测试文件没被动

    def test_does_not_push_to_main(self):
        # 当前在 main 分支时不自动推送（防 AI 代码直推主干）
        self._git("branch", "-m", "main")
        r = apply_test_and_commit(self.repo, self._diff_change_f(), PASS, "在main改", push=True)
        self.assertTrue(r.ok, r.message)
        self.assertEqual(r.stage, "committed")
        self.assertIn("main", r.message)               # 提示未推送
        self.assertIn("在main改", self._git("log", "-1", "--pretty=%s").stdout)

    def test_commit_failure_rolls_back(self):
        # pre-commit 钩子拒绝 → 提交失败 → 应回滚（保持"始终干净"承诺）
        hook = os.path.join(self.repo, ".git", "hooks", "pre-commit")
        with open(hook, "w", encoding="utf-8", newline="\n") as fp:
            fp.write("#!/bin/sh\nexit 1\n")
        os.chmod(hook, 0o755)
        r = apply_test_and_commit(self.repo, self._diff_change_f(), PASS, "会失败")
        self.assertFalse(r.ok)
        self.assertEqual(r.stage, "commit-failed")
        with open(os.path.join(self.repo, "f.txt"), encoding="utf-8") as fp:
            self.assertEqual(fp.read(), "hello\n")       # 已回滚


if __name__ == "__main__":
    unittest.main()

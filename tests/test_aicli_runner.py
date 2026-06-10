"""通用 AI CLI 调用层：用一个假 CL(python 子进程)验证模板渲染/输入模式/超时/退出码。

不依赖真实 AI，可离线跑。
"""
import sys
import unittest

from w3xtool.aicli.runner import AIProfile, run_ai

# 假 CLI 用 -X utf8 强制 UTF-8 输出（真实 AI CLI 本就输出 UTF-8；
# 否则 Windows 子进程默认按 cp936 编码 stdout，与 runner 的 UTF-8 解码不符）。
PY = [sys.executable, "-X", "utf8"]


class TestRunAI(unittest.TestCase):
    def test_arg_mode_substitutes_prompt(self):
        # {prompt} 占位被替换进命令参数
        prof = AIProfile(
            name="fake",
            command=[*PY, "-c", "import sys;print('GOT:'+sys.argv[1])", "{prompt}"],
            input_mode="arg")
        r = run_ai(prof, "hello-世界")
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.exit_code, 0)
        self.assertIn("GOT:hello-世界", r.stdout)

    def test_stdin_mode_pipes_prompt(self):
        prof = AIProfile(
            name="fake",
            command=[*PY, "-c", "import sys;print('IN:'+sys.stdin.read().strip())"],
            input_mode="stdin")
        r = run_ai(prof, "from-stdin")
        self.assertTrue(r.ok, r.error)
        self.assertIn("IN:from-stdin", r.stdout)

    def test_file_mode_writes_prompt_to_tempfile(self):
        prof = AIProfile(
            name="fake",
            command=[*PY, "-c", "import sys;print('FILE:'+open(sys.argv[1],encoding='utf-8').read())", "{prompt_file}"],
            input_mode="file")
        r = run_ai(prof, "big-prompt-内容")
        self.assertTrue(r.ok, r.error)
        self.assertIn("FILE:big-prompt-内容", r.stdout)

    def test_nonzero_exit_marks_not_ok(self):
        prof = AIProfile(name="fail", command=[*PY, "-c", "import sys;sys.exit(3)"], input_mode="stdin")
        r = run_ai(prof, "x")
        self.assertFalse(r.ok)
        self.assertEqual(r.exit_code, 3)

    def test_timeout_returns_failure_not_hang(self):
        prof = AIProfile(
            name="slow",
            command=[*PY, "-c", "import time;time.sleep(5)"],
            input_mode="stdin", timeout=0.5)
        r = run_ai(prof, "x")
        self.assertFalse(r.ok)
        self.assertIn("超时", r.error)

    def test_missing_command_returns_failure(self):
        prof = AIProfile(name="nope", command=["definitely_not_a_real_cli_xyz", "{prompt}"], input_mode="arg")
        r = run_ai(prof, "x")
        self.assertFalse(r.ok)
        self.assertTrue(r.error)


if __name__ == "__main__":
    unittest.main()

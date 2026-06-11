"""单实例：再次启动时关掉上一个实例再重启。核心决策 _decide 为纯逻辑，
注入「是否存活 / 进程映像路径」依赖即可测，无需真造进程。"""
import os
import subprocess
import sys
import time
import unittest

from w3xtool.single_instance import _decide, _terminate, _image_path, _pid_alive


class TestDecide(unittest.TestCase):
    MY_PID = 1000
    MY_IMG = r"C:\app\魔兽地图提取器.exe"

    def _decide(self, lock, alive, images):
        return _decide(self.MY_PID, self.MY_IMG, lock,
                       alive=lambda p: alive.get(p, False),
                       image_of=lambda p: images.get(p))

    def test_no_lock_file_kills_nobody(self):
        self.assertIsNone(self._decide(None, {}, {}))

    def test_empty_lock_kills_nobody(self):
        self.assertIsNone(self._decide({}, {}, {}))

    def test_self_pid_not_killed(self):
        lock = {"pid": self.MY_PID, "image": self.MY_IMG}
        self.assertIsNone(self._decide(lock, {self.MY_PID: True}, {self.MY_PID: self.MY_IMG}))

    def test_dead_previous_instance_not_killed(self):
        lock = {"pid": 2000, "image": self.MY_IMG}
        self.assertIsNone(self._decide(lock, {2000: False}, {}))

    def test_live_previous_instance_is_killed(self):
        lock = {"pid": 2000, "image": self.MY_IMG}
        victim = self._decide(lock, {2000: True}, {2000: self.MY_IMG})
        self.assertEqual(victim, 2000)

    def test_reused_pid_not_killed(self):
        # pid 2000 现在是别的程序（映像变了）→ 绝不能误杀
        lock = {"pid": 2000, "image": self.MY_IMG}
        self.assertIsNone(
            self._decide(lock, {2000: True}, {2000: r"C:\windows\notepad.exe"}))

    def test_garbage_pid_field_kills_nobody(self):
        self.assertIsNone(self._decide({"pid": "oops"}, {}, {}))

    def test_same_basename_different_dir_not_killed(self):
        # 同名但在不同目录的可执行体不是"本程序的上一个实例"，不该误杀
        lock = {"pid": 2000, "image": r"D:\portable\魔兽地图提取器.exe"}
        self.assertIsNone(
            self._decide(lock, {2000: True}, {2000: r"D:\portable\魔兽地图提取器.exe"}))

    def test_path_compare_is_case_insensitive(self):
        # Windows 路径大小写不敏感：大小写不同的同一文件仍应判为同一实例 → 终止
        lock = {"pid": 2000, "image": self.MY_IMG.upper()}
        victim = self._decide(lock, {2000: True}, {2000: self.MY_IMG})
        self.assertEqual(victim, 2000)


@unittest.skipUnless(sys.platform == "win32", "终止逻辑用 Windows 句柄 API")
class TestTerminateImageGuard(unittest.TestCase):
    """_terminate 用句柄复核映像：杀对的、绝不因 pid 复用/篡改误杀别的。"""

    def _spawn(self):
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])

    def test_terminate_kills_matching_image(self):
        p = self._spawn()
        try:
            for _ in range(50):                 # 等子进程映像可查询
                img = _image_path(p.pid)
                if img:
                    break
                time.sleep(0.02)
            self.assertIsNotNone(img)
            _terminate(p.pid, img)
            self.assertFalse(_pid_alive(p.pid))   # 映像匹配 → 被终止
        finally:
            try:
                p.kill()
            except OSError:
                pass

    def test_terminate_skips_mismatched_image(self):
        p = self._spawn()
        try:
            time.sleep(0.1)
            _terminate(p.pid, r"C:\nonexistent\other.exe")  # 映像不符(模拟 pid 复用/篡改)
            self.assertTrue(_pid_alive(p.pid))    # 绝不误杀
        finally:
            try:
                p.kill()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()

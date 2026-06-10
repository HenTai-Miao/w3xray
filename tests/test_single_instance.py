"""单实例：再次启动时关掉上一个实例再重启。核心决策 _decide 为纯逻辑，
注入「是否存活 / 进程映像路径」依赖即可测，无需真造进程。"""
import unittest

from w3xtool.single_instance import _decide


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


if __name__ == "__main__":
    unittest.main()

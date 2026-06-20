"""单实例：再次启动时，先把上一个实例关掉，再让本次启动接管。

策略（按用户要求）：新启动的实例**杀掉旧实例**后自己继续运行，不允许多开。
做法是在临时目录维护一个锁文件，记录 {pid, image}：
- 启动时读锁文件，若上个 pid 仍存活、且该 pid 当前的映像路径与记录一致
  （证明没被系统回收复用成别的程序），就终止它，再写入本次 pid。
- 任何一步出错都**静默降级为不拦截**，绝不阻塞程序启动。

核心决策 _decide() 为纯函数（注入存活/映像查询），便于测试；Windows 的进程
查询/终止用 ctypes（本工具仅 Windows）。
"""
from __future__ import annotations

import json
import ntpath
import os
import sys
import tempfile
import time

_LOCK_NAME = "w3xray.instance.lock"


def _same_image(a, b) -> bool:
    """两条映像路径是否指向同一可执行体（Windows 大小写不敏感、规范化分隔符）。

    用**完整路径**而非仅文件名比较：不同目录下的同名 exe（便携版 vs 安装版、
    或攻击者放的同名进程）不算「本程序的上一个实例」，避免误杀。"""
    if not a or not b:
        return False
    return ntpath.normcase(ntpath.normpath(a)) == ntpath.normcase(ntpath.normpath(b))


def _decide(my_pid, my_image, lock_data, *, alive, image_of):
    """返回需要终止的旧实例 pid，或 None。纯逻辑，依赖经参数注入。

    仅当：锁里记录了别的 pid、它仍存活、且其当前完整映像路径与锁记录一致
    （未被 pid 复用）、且与本程序是同一可执行体时，才判定为「上一个本程序实例」。"""
    if not lock_data:
        return None
    old_pid = lock_data.get("pid")
    old_image = lock_data.get("image")
    if not isinstance(old_pid, int) or old_pid == my_pid:
        return None
    if not _same_image(old_image, my_image):
        return None                       # 锁记录的是别的可执行体（含同名不同目录），不动它
    if not alive(old_pid):
        return None                       # 旧实例已退出
    if not _same_image(image_of(old_pid), old_image):
        return None                       # pid 已被复用成别的进程，别误杀
    return old_pid


# ---- Windows 进程查询（ctypes，HANDLE 须设 restype 防 64 位截断）----
def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    k.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k.TerminateProcess.restype = wintypes.BOOL
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k, ctypes, wintypes


_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_TERMINATE = 0x0001
_WAIT_TIMEOUT = 0x102


def _image_via_handle(k, ctypes, wintypes, handle):
    buf = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buf))
    if k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
        return buf.value
    return None


def _pid_alive(pid: int) -> bool:
    try:
        k, _, _ = _kernel32()
        h = k.OpenProcess(_SYNCHRONIZE, False, pid)
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == _WAIT_TIMEOUT   # 仍在运行
        finally:
            k.CloseHandle(h)
    except Exception:
        return False


def _image_path(pid: int):
    try:
        k, ctypes, wintypes = _kernel32()
        h = k.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            return _image_via_handle(k, ctypes, wintypes, h)
        finally:
            k.CloseHandle(h)
    except Exception:
        return None


def _terminate(pid: int, expected_image: str, timeout: float = 3.0) -> None:
    """终止 pid，但先用**同一句柄**复核映像，杜绝 _decide 与终止之间 pid 被复用的竞态。

    OpenProcess 拿到的句柄指向具体进程对象；只要持有它，该 pid 不会在我们眼皮底下
    被复用成另一个进程。故"用此句柄查到的映像 == 期望映像"成立后再 TerminateProcess，
    即使 _decide 之后旧实例恰好退出、pid 被别的程序占用，也不会误杀。"""
    try:
        k, ctypes, wintypes = _kernel32()
        h = k.OpenProcess(_PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return
        try:
            if not _same_image(_image_via_handle(k, ctypes, wintypes, h), expected_image):
                return                        # 句柄指向的已不是目标程序（pid 复用/篡改）→ 不杀
            k.TerminateProcess(h, 1)
        finally:
            k.CloseHandle(h)
    except Exception:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.05)


def _self_image() -> str:
    """本进程的 OS 映像路径。用与校验旧实例相同的 API 取，保证两边可比
    （sys.executable 在 venv/启动器下可能与系统报告的路径不一致）。"""
    return _image_path(os.getpid()) or sys.executable


def _lock_path() -> str:
    return os.path.join(tempfile.gettempdir(), _LOCK_NAME)


def _read_lock(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_lock(path: str, pid: int, image: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "image": image}, f)
    except OSError:
        pass


def ensure_single_instance():
    """若已有本程序实例在运行则先终止它，再把本次进程登记为当前实例。

    返回被终止的 pid（无则 None）。全程 best-effort，任何异常都不阻塞启动。"""
    try:
        path = _lock_path()
        my_pid = os.getpid()
        my_image = _self_image()
        victim = _decide(my_pid, my_image, _read_lock(path),
                         alive=_pid_alive, image_of=_image_path)
        if victim is not None:
            _terminate(victim, my_image)      # 复核映像须与本程序一致(同一可执行体)
        _write_lock(path, my_pid, my_image)
        return victim
    except Exception:
        return None

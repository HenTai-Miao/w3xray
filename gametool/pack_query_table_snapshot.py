"""Delivery proofs for exact query bytes and script-directory observations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat


def table_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    # Windows path stat and fstat disagree on creation/change-time semantics.
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


@dataclass(frozen=True, slots=True)
class TableSourceSnapshot:
    path: Path
    identity: tuple[int, int, int, int] | None
    fingerprint: str = ""

    def verify(self) -> str:
        """Revalidate every byte and missing-file observation before delivery."""
        if self.identity is None:
            try:
                self.path.lstat()
            except FileNotFoundError:
                return ""
            except OSError:
                pass
        else:
            try:
                with self.path.open("rb") as handle:
                    before = os.fstat(handle.fileno())
                    fingerprint = hashlib.file_digest(handle, "sha256").hexdigest()
                    after = os.fstat(handle.fileno())
                if (
                    self.identity
                    == table_identity(before)
                    == table_identity(after)
                    == table_identity(self.path.stat())
                    and self.fingerprint == fingerprint
                ):
                    return ""
            except OSError:
                pass
        return (
            "来源完整字节、身份或存在状态在查询交付前变化；"
            "以上保留已读取证据，完整性未确认，请刷新后重查。"
        )


@dataclass(frozen=True, slots=True)
class ScriptDirectorySnapshot:
    path: Path
    identity: tuple[int, int, int, int] | None
    entries: tuple[str, ...] = ()
    readable: bool = True

    @classmethod
    def capture(cls, path: Path) -> ScriptDirectorySnapshot:
        """The returned inventory is also the inventory the source reader uses."""
        try:
            before = path.stat()
            if not stat.S_ISDIR(before.st_mode):
                return cls(path, table_identity(before), readable=False)

            def failed(error: OSError) -> None:
                raise error

            entries = tuple(
                sorted(
                    (directory / name).relative_to(path).as_posix()
                    for directory, _directories, names in path.walk(on_error=failed)
                    for name in names
                    if Path(name).suffix.lower() in (".j", ".lua", ".txt")
                )
            )
            identity = table_identity(before)
            return cls(path, identity, entries, identity == table_identity(path.stat()))
        except FileNotFoundError:
            return cls(path, None)
        except OSError:
            return cls(path, None, readable=False)

    def verify(self) -> str:
        current = self.capture(self.path)
        if self.readable and current == self:
            return ""
        return (
            "脚本目录身份、存在状态或完整来源清单在查询交付前变化/无法确认；"
            "以上保留已读取证据，完整性未确认，请刷新后重查。"
        )


QuerySourceSnapshot = TableSourceSnapshot | ScriptDirectorySnapshot

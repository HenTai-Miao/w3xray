"""Immutable script-pack bytes with complete delivery-time revalidation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat


SCRIPT_INDEX = "脚本调用参数索引.tsv"
SCRIPT_INPUTS = (
    SCRIPT_INDEX,
    "地图信息.txt",
    "脚本清单.txt",
    "组件诊断.tsv",
    "未知文件/加密脚本检测.txt",
)
SCRIPT_DIRECTORIES = ("脚本原始文本", "脚本可读文本")
_SCRIPT_SUFFIXES = frozenset({".j", ".lua", ".txt"})


@dataclass(frozen=True, slots=True)
class ScriptSnapshotProblem:
    source: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ScriptFileIdentity:
    relative: str
    state: str
    identity: tuple[int, int, int, int] | None = None
    fingerprint: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class ScriptFileSnapshot:
    relative: str
    state: str
    identity: tuple[int, int, int, int] | None = None
    fingerprint: str = ""
    payload: bytes = b""
    error: str = ""

    def observed_identity(self) -> ScriptFileIdentity:
        return ScriptFileIdentity(
            self.relative, self.state, self.identity, self.fingerprint, self.error
        )


@dataclass(frozen=True, slots=True)
class ScriptDirectorySnapshot:
    relative: str
    state: str
    identity: tuple[int, int, int, int] | None = None
    members: tuple[tuple[str, str], ...] = ()
    error: str = ""


@dataclass(frozen=True, slots=True)
class ScriptPackSnapshotIdentity:
    """JSON-safe immutable observations retained across campaign section runs."""

    pack: str
    files: tuple[ScriptFileIdentity, ...]
    directories: tuple[ScriptDirectorySnapshot, ...]


@dataclass(frozen=True, slots=True)
class ScriptPackSnapshot:
    pack: Path
    files: tuple[ScriptFileSnapshot, ...]
    directories: tuple[ScriptDirectorySnapshot, ...]
    problems: tuple[ScriptSnapshotProblem, ...]

    @property
    def original(self) -> bool:
        return any(
            item.relative == SCRIPT_DIRECTORIES[0] and item.state != "missing"
            for item in self.directories
        )

    @property
    def source_directory(self) -> str:
        return SCRIPT_DIRECTORIES[0 if self.original else 1]

    @property
    def initially_stable(self) -> bool:
        return not any(item.code == "snapshot.changed" for item in self.problems)

    def observed_identity(self) -> ScriptPackSnapshotIdentity:
        return ScriptPackSnapshotIdentity(
            str(self.pack.absolute()),
            tuple(item.observed_identity() for item in self.files),
            self.directories,
        )

    def verify(self) -> tuple[ScriptSnapshotProblem, ...]:
        return verify_script_pack(self.observed_identity())


def verify_script_pack(
    identity: ScriptPackSnapshotIdentity,
) -> tuple[ScriptSnapshotProblem, ...]:
    """Re-read every byte and missing observation against the original identity."""
    current = capture_script_pack(Path(identity.pack))
    old_files = {item.relative: item for item in identity.files}
    new_files = {item.relative: item.observed_identity() for item in current.files}
    old_dirs = {item.relative: item for item in identity.directories}
    new_dirs = {item.relative: item for item in current.directories}
    problems: list[ScriptSnapshotProblem] = []
    for relative in sorted(old_files.keys() | new_files.keys()):
        previous, observed = old_files.get(relative), new_files.get(relative)
        if previous != observed:
            problems.append(
                ScriptSnapshotProblem(
                    relative,
                    "snapshot.changed",
                    "来源完整字节、身份或存在状态在查询交付前变化；"
                    "已保留本次冻结证据，请刷新后重查。",
                )
            )
    for relative in sorted(old_dirs.keys() | new_dirs.keys()):
        if old_dirs.get(relative) != new_dirs.get(relative):
            problems.append(
                ScriptSnapshotProblem(
                    relative,
                    "snapshot.changed",
                    "脚本目录身份或完整成员清单在查询交付前变化；"
                    "未将原始来源降为旧包副本，请刷新后重查。",
                )
            )
    problems.extend(
        item for item in current.problems if item.code == "snapshot.changed"
    )
    return tuple(dict.fromkeys(problems))


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    # Windows path stat and fstat disagree on creation/change-time semantics.
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _reparse(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _checked_parents(pack: Path, relative: str) -> None:
    cursor = pack
    for part in Path(relative).parts[:-1]:
        cursor /= part
        info = cursor.lstat()
        if _reparse(info) or not stat.S_ISDIR(info.st_mode):
            raise OSError("来源父目录是链接或不是目录，未越过资料包路径边界")


def _file(pack: Path, relative: str) -> ScriptFileSnapshot:
    path = pack / relative
    try:
        _checked_parents(pack, relative)
        initial = path.lstat()
        if _reparse(initial) or not stat.S_ISREG(initial.st_mode):
            return ScriptFileSnapshot(
                relative, "unsafe", _identity(initial), error="来源不是普通文件或为链接"
            )
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            payload = handle.read()
            after = os.fstat(handle.fileno())
        final = path.lstat()
        _checked_parents(pack, relative)
        if (
            _reparse(final)
            or _identity(initial) != _identity(before)
            or _identity(before) != _identity(after)
            or _identity(after) != _identity(final)
        ):
            return ScriptFileSnapshot(
                relative, "changed", error="来源在读取完整字节时变化"
            )
        return ScriptFileSnapshot(
            relative,
            "file",
            _identity(after),
            hashlib.sha256(payload).hexdigest(),
            payload,
        )
    except FileNotFoundError:
        return ScriptFileSnapshot(relative, "missing")
    except OSError as error:
        return ScriptFileSnapshot(relative, "error", error=str(error))


def _directory(
    pack: Path, relative: str
) -> tuple[ScriptDirectorySnapshot, tuple[str, ...], tuple[str, ...]]:
    path = pack / relative
    try:
        _checked_parents(pack, relative)
        before = path.lstat()
        if _reparse(before) or not stat.S_ISDIR(before.st_mode):
            return (
                ScriptDirectorySnapshot(
                    relative,
                    "unsafe",
                    _identity(before),
                    error="脚本目录是链接或不是目录，未越过资料包路径边界",
                ),
                (),
                (),
            )
        members: list[tuple[str, str]] = []
        children: list[str] = []
        files: list[str] = []
        with os.scandir(path) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                kind = (
                    "unsafe"
                    if _reparse(info)
                    else "directory"
                    if stat.S_ISDIR(info.st_mode)
                    else "file"
                    if stat.S_ISREG(info.st_mode)
                    else "other"
                )
                members.append((entry.name, kind))
                child = relative + "/" + entry.name
                if kind == "directory":
                    children.append(child)
                elif (
                    kind == "unsafe"
                    or Path(entry.name).suffix.lower() in _SCRIPT_SUFFIXES
                ):
                    files.append(child)
        after = path.lstat()
        if _reparse(after) or _identity(before) != _identity(after):
            return (
                ScriptDirectorySnapshot(
                    relative, "changed", error="脚本目录在枚举完整成员时变化"
                ),
                (),
                (),
            )
        return (
            ScriptDirectorySnapshot(
                relative, "directory", _identity(after), tuple(sorted(members))
            ),
            tuple(sorted(children)),
            tuple(sorted(files)),
        )
    except FileNotFoundError:
        return ScriptDirectorySnapshot(relative, "missing"), (), ()
    except OSError as error:
        return ScriptDirectorySnapshot(relative, "error", error=str(error)), (), ()


def capture_script_pack(pack: Path) -> ScriptPackSnapshot:
    """Capture fixed metadata and both source-directory boundaries without writes."""
    pack = pack.absolute()
    directories: list[ScriptDirectorySnapshot] = []
    paths: set[str] = set(SCRIPT_INPUTS)
    pending: list[str] = list(reversed(SCRIPT_DIRECTORIES))
    while pending:
        directory, children, files = _directory(pack, pending.pop())
        directories.append(directory)
        pending.extend(reversed(children))
        paths.update(files)
    captured = tuple(_file(pack, path) for path in sorted(paths))
    problems = tuple(
        ScriptSnapshotProblem(
            item.relative,
            "snapshot.changed"
            if item.state in {"changed", "missing"}
            else "source.read",
            item.error or "来源已列入脚本目录，但读取完整字节时缺失",
        )
        for item in (*directories, *captured)
        if item.state not in {"directory", "file", "missing"}
        or isinstance(item, ScriptFileSnapshot)
        and item.state == "missing"
        and item.relative not in SCRIPT_INPUTS
    )
    return ScriptPackSnapshot(pack, captured, tuple(directories), problems)

"""Verified live-pack generations; incomplete evidence is never overwritten."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import stat
import tempfile

from .bounded_file import read_bounded_regular_file, sha256_regular_file
from .knowledge_results import KnowledgeWriteReport, KnowledgeWriteStatus
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteStatus

_MANIFEST = ".gamexray-live-pack.json"


@dataclass(frozen=True, slots=True)
class LivePackSource:
    path: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    sha256: str


def live_pack_source(path: str) -> LivePackSource:
    """Capture complete source bytes and identity before use or delivery."""
    source = Path(os.path.abspath(path))
    before = source.lstat()
    digest, identity = sha256_regular_file(source)
    after = source.lstat()
    if _identity(before) != _identity(after):
        raise OSError("地图文件在资料包准备期间改变，请重试")
    return LivePackSource(
        os.path.normcase(str(source)),
        identity.device,
        identity.inode,
        identity.size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        digest,
    )


def find_complete_live_pack(
    base: Path, source: LivePackSource, version: str
) -> Path | None:
    """Find an exact verified generation, including a prior successful retry."""
    try:
        siblings = sorted(
            (
                path
                for path in base.parent.iterdir()
                if path.name.startswith(base.name + "-generation-")
            ),
            key=lambda path: path.name,
            reverse=True,
        )
    except OSError:
        siblings = []
    for candidate in (base, *siblings):
        if complete_live_pack(candidate, source, version):
            return candidate
    return None


def allocate_live_pack(base: Path) -> Path:
    """Use a fresh empty target while retaining every prior attempt's files."""
    base.parent.mkdir(parents=True, exist_ok=True)
    if not _real_directory(base.parent.lstat()):
        raise OSError("资料包缓存父目录不是普通目录")
    try:
        base.mkdir()
        return base
    except FileExistsError:
        return Path(
            tempfile.mkdtemp(prefix=base.name + "-generation-", dir=base.parent)
        )


def complete_live_pack(root: Path, source: LivePackSource, version: str) -> bool:
    """Require source binding and every recorded artifact's current full hash."""
    try:
        if not _real_directory(root.lstat()):
            return False
        payload, _ = read_bounded_regular_file(root / _MANIFEST)
        manifest = json.loads(payload)
        if not isinstance(manifest, dict) or (
            manifest.get("schema") != 1
            or manifest.get("status") != KnowledgeWriteStatus.COMPLETE.value
            or manifest.get("version") != version
            or manifest.get("source") != asdict(source)
        ):
            return False
        files = manifest.get("files")
        return (
            isinstance(files, dict)
            and "对象字段.tsv" in files
            and files == _artifact_fingerprints(root)
        )
    except OSError, ValueError, TypeError:
        return False


def complete_live_pack_publication(
    root: Path, source: LivePackSource, version: str, report: KnowledgeWriteReport
) -> None:
    """Publish readiness only after the complete typed report reconciles."""
    if report.status is not KnowledgeWriteStatus.COMPLETE or not report.written_count:
        raise OSError("资料包发布未完整完成")
    files = _artifact_fingerprints(root)
    if (
        "对象字段.tsv" not in files
        or len(report.items) != len(files)
        or {item.path for item in report.items} != files.keys()
        or any(
            item.path not in files or files[item.path]["size"] != item.size
            for item in report.items
        )
    ):
        raise OSError("资料包写入结果与实际成果文件不一致")
    manifest = {
        "schema": 1,
        "status": report.status.value,
        "version": version,
        "source": asdict(source),
        "files": files,
    }
    result = write_text_safely(
        str(root),
        _MANIFEST,
        json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
    )
    if result.status is not SafeWriteStatus.WRITTEN:
        raise OSError(result.error or "无法写入资料包完成标记")
    if not complete_live_pack(root, source, version):
        raise OSError("资料包完成后复核失败，已保留本次结果，请重试")


def _artifact_fingerprints(root: Path) -> dict[str, dict[str, str | int]]:
    files: dict[str, dict[str, str | int]] = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        before = directory.lstat()
        if not _real_directory(before):
            raise OSError("资料包包含符号链接或非普通目录")
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                metadata = entry.stat(follow_symlinks=False)
                if _reparse(metadata):
                    raise OSError("资料包包含重解析点")
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(metadata.st_mode):
                    if relative == _MANIFEST:
                        continue
                    digest, identity = sha256_regular_file(path)
                    files[relative] = {"size": identity.size, "sha256": digest}
                else:
                    raise OSError("资料包包含非普通文件")
        if _identity(before) != _identity(directory.lstat()):
            raise OSError("资料包目录在复核期间改变")
    return files


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_mode,
    )


def _reparse(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _real_directory(metadata: os.stat_result) -> bool:
    return stat.S_ISDIR(metadata.st_mode) and not _reparse(metadata)

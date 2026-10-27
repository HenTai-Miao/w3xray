"""Real Windows long-path output, rollback, and ownership boundaries."""

from __future__ import annotations

from collections.abc import Iterator
import errno
import os
from pathlib import Path
import subprocess
import sys

import pytest

from gametool import durable_io, safe_output
from gametool.safe_output import SafeWriteStatus, safe_destination, write_bytes_safely


def _fixture_io(path: Path | str) -> str:
    value = str(path)
    return value if value.startswith("\\\\?\\") else "\\\\?\\" + value


def _units(path: Path | str) -> int:
    return len(str(path).encode("utf-16-le")) // 2


def _deep_root(tmp_path: Path, *, minimum: int = 300) -> Path:
    root = tmp_path
    while _units(root) < minimum:
        root /= "地图😀-" + "long-path-" * 4
    os.makedirs(_fixture_io(root), exist_ok=True)
    return root


def test_actual_stage_crossing_max_path_keeps_logical_result(tmp_path: Path) -> None:
    assert _units(tmp_path) < 240
    root = tmp_path / ("p" * (245 - _units(tmp_path) - 1))
    root.mkdir()
    assert _units(root) == 245
    destination = root / "报告.tsv"
    assert _units(destination) < 260
    result = write_bytes_safely(str(root), destination.name, b"complete\tbytes\r\n")
    assert result.status is SafeWriteStatus.WRITTEN, result.error
    assert result.path == str(destination)
    assert not result.path.startswith("\\\\?\\")
    assert Path(_fixture_io(destination)).read_bytes() == b"complete\tbytes\r\n"
    assert os.listdir(_fixture_io(root)) == [destination.name]


def test_actual_long_root_nested_unicode_output_and_destination_query(
    tmp_path: Path,
) -> None:
    root = _deep_root(tmp_path)
    relative = "文本😀/完整资料.tsv"
    expected = root / "文本😀" / "完整资料.tsv"
    data = '全量\t"内容"\r\n第二行\n'.encode()
    result = write_bytes_safely(str(root), relative, data)
    assert result.status is SafeWriteStatus.WRITTEN, result.error
    assert result.path == str(expected)
    assert result.size == len(data)
    assert Path(_fixture_io(expected)).read_bytes() == data
    assert safe_destination(str(root), relative) == str(expected)
    assert os.listdir(_fixture_io(expected.parent)) == [expected.name]


def test_explicit_extended_root_keeps_callers_logical_spelling(tmp_path: Path) -> None:
    root = _deep_root(tmp_path)
    explicit = _fixture_io(root)
    expected = str(Path(explicit) / "report.txt")
    result = write_bytes_safely(explicit, "report.txt", b"complete")
    assert result.status is SafeWriteStatus.WRITTEN, result.error
    assert result.path == expected
    assert safe_destination(explicit, "report.txt") == expected


@pytest.mark.parametrize("component", ["alias. ", "alias.", "alias..", "alias "])
def test_raw_root_rejection_cannot_overwrite_normalized_alias(
    tmp_path: Path, component: str
) -> None:
    alias = tmp_path / "alias"
    alias.mkdir()
    sentinel = alias / "leaf.bin"
    sentinel.write_bytes(b"preserve-alias")
    before = sentinel.stat()
    raw_root = str(tmp_path / component)
    assert safe_destination(raw_root, sentinel.name) is None
    result = write_bytes_safely(raw_root, sentinel.name, b"must-not-overwrite")
    assert result.status is SafeWriteStatus.UNSAFE
    assert "Windows" in result.error
    assert sentinel.read_bytes() == b"preserve-alias"
    after = sentinel.stat()
    assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    assert os.listdir(tmp_path) == [alias.name]


@pytest.mark.parametrize("prefix", ["//?/", "\\\\?/"])
def test_raw_mixed_namespace_cannot_be_normalized_into_a_write(
    tmp_path: Path, prefix: str
) -> None:
    alias = tmp_path / "namespace-alias"
    alias.mkdir()
    sentinel = alias / "leaf.bin"
    sentinel.write_bytes(b"preserve-namespace-alias")
    before = sentinel.stat()
    raw_root = prefix + str(alias).replace("\\", "/")
    assert safe_destination(raw_root, sentinel.name) is None
    result = write_bytes_safely(raw_root, sentinel.name, b"must-not-overwrite")
    assert result.status is SafeWriteStatus.UNSAFE
    assert "Windows" in result.error
    assert sentinel.read_bytes() == b"preserve-namespace-alias"
    after = sentinel.stat()
    assert (after.st_dev, after.st_ino, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_mtime_ns,
    )
    assert os.listdir(tmp_path) == [alias.name]


@pytest.mark.parametrize(
    "root", [".", "./relative", "nested/../relative", "../neighbor", "相对😀/../最终😀"]
)
def test_ordinary_relative_roots_preserve_navigation_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root: str
) -> None:
    working = tmp_path / "cwd"
    working.mkdir()
    monkeypatch.chdir(working)
    expected = str(Path(os.path.abspath(root)) / "leaf.bin")
    assert safe_destination(root, "leaf.bin") == expected
    result = write_bytes_safely(root, "leaf.bin", b"complete-relative-output")
    assert result.status is SafeWriteStatus.WRITTEN, result.error
    assert result.path == expected
    assert Path(expected).read_bytes() == b"complete-relative-output"


def test_actual_long_overwrite_preserves_old_bytes_until_complete(
    tmp_path: Path,
) -> None:
    root = _deep_root(tmp_path)
    destination = root / "state.json"
    Path(_fixture_io(destination)).write_bytes(b"old-complete")

    def chunks() -> Iterator[bytes]:
        yield b"new-"
        assert Path(_fixture_io(destination)).read_bytes() == b"old-complete"
        yield b"complete"

    result = safe_output.write_chunks_safely(str(root), destination.name, chunks())
    assert result.status is SafeWriteStatus.WRITTEN, result.error
    assert Path(_fixture_io(destination)).read_bytes() == b"new-complete"
    assert os.listdir(_fixture_io(root)) == [destination.name]


def test_actual_long_failed_commit_retains_exact_old_identity_for_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _deep_root(tmp_path)
    destination = root / "state.json"
    native = Path(_fixture_io(destination))
    native.write_bytes(b"old-complete")
    before = native.stat()
    sync_calls = 0

    def fail_commit(_path: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 2:
            raise OSError(errno.EIO, "fixture metadata commit failed")

    monkeypatch.setattr(durable_io, "sync_directory", fail_commit)
    result = write_bytes_safely(str(root), destination.name, b"new-complete")
    assert result.status is SafeWriteStatus.FAILED
    assert "fixture metadata commit failed" in result.error
    assert "recovery retained" in result.error
    assert native.read_bytes() == b"new-complete"
    (backup,) = Path(_fixture_io(root)).glob(".gamexray-backup-*.tmp")
    assert backup.read_bytes() == b"old-complete"
    after = backup.stat()
    assert (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size) == (
        before.st_dev,
        before.st_ino,
        before.st_mtime_ns,
        before.st_size,
    )
    assert sync_calls == 2
    assert set(os.listdir(_fixture_io(root))) == {destination.name, backup.name}


def test_actual_long_source_failure_removes_only_owned_stage(tmp_path: Path) -> None:
    root = _deep_root(tmp_path)
    destination = root / "state.json"
    native = Path(_fixture_io(destination))
    native.write_bytes(b"old-complete")
    before = native.stat()

    def chunks() -> Iterator[bytes]:
        yield b"partial"
        raise RuntimeError("fixture source failed")

    with pytest.raises(RuntimeError, match="fixture source failed"):
        safe_output.write_chunks_safely(str(root), destination.name, chunks())
    assert native.read_bytes() == b"old-complete"
    assert native.stat().st_ino == before.st_ino
    assert os.listdir(_fixture_io(root)) == [destination.name]


def test_actual_long_replaced_stage_is_rejected_and_foreign_file_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _deep_root(tmp_path)
    destination = root / "state.json"
    Path(_fixture_io(destination)).write_bytes(b"old-complete")
    original_check = safe_output._staged_path_error
    replaced: list[Path] = []

    def replace_closed_stage(path: str, identity: tuple[int, int]) -> str | None:
        if not replaced:
            staged = Path(_fixture_io(path))
            os.replace(staged, _fixture_io(root / "retained-owned-stage"))
            staged.write_bytes(b"foreign-replacement")
            replaced.append(staged)
        return original_check(path, identity)

    monkeypatch.setattr(safe_output, "_staged_path_error", replace_closed_stage)
    result = write_bytes_safely(str(root), destination.name, b"new-complete")
    assert result.status is SafeWriteStatus.UNSAFE
    assert "staged output changed" in result.error
    assert len(replaced) == 1
    assert replaced[0].read_bytes() == b"foreign-replacement"
    assert Path(_fixture_io(destination)).read_bytes() == b"old-complete"
    assert (
        Path(_fixture_io(root / "retained-owned-stage")).read_bytes() == b"new-complete"
    )


def test_actual_long_junction_escape_keeps_outside_fixture_unchanged(
    tmp_path: Path,
) -> None:
    import _winapi

    root = _deep_root(tmp_path)
    outside = tmp_path / "outside-owned-fixture"
    outside.mkdir()
    target = outside / "evidence.bin"
    target.write_bytes(b"outside-before")
    before = target.stat()
    junction = root / "redirected"
    _winapi.CreateJunction(str(outside), _fixture_io(junction))
    assert os.path.isjunction(_fixture_io(junction))
    assert safe_destination(str(root), "redirected/evidence.bin") is None
    result = write_bytes_safely(str(root), "redirected/evidence.bin", b"after")
    assert result.status is SafeWriteStatus.UNSAFE
    assert target.read_bytes() == b"outside-before"
    after = target.stat()
    assert (after.st_dev, after.st_ino, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_mtime_ns,
    )


@pytest.mark.parametrize(
    "relative",
    [
        "../escape",
        "..\\escape",
        "a/../escape",
        "a:name",
        "a. /x",
        "a./x",
        "a /x",
        "NUL.txt",
        "COM¹.txt",
        "x\x01y",
    ],
)
def test_long_path_conversion_never_bypasses_relative_name_rejection(
    tmp_path: Path, relative: str
) -> None:
    root = _deep_root(tmp_path)
    result = write_bytes_safely(str(root), relative, b"untrusted")
    assert result.status is SafeWriteStatus.UNSAFE
    assert result.error
    assert os.listdir(_fixture_io(root)) == []


@pytest.mark.parametrize(
    ("logical", "expected"),
    [
        (r"C:\地图😀\evidence.txt", "\\\\?\\C:\\地图😀\\evidence.txt"),
        (
            r"\\server\share\地图😀\evidence.txt",
            "\\\\?\\UNC\\server\\share\\地图😀\\evidence.txt",
        ),
        (
            r"\\?\UNC\server\share\地图😀\evidence.txt",
            "\\\\?\\UNC\\server\\share\\地图😀\\evidence.txt",
        ),
        (r"\\?\C:\地图😀\evidence.txt", "\\\\?\\C:\\地图😀\\evidence.txt"),
    ],
)
def test_drive_and_unc_io_spellings_preserve_unicode_without_accessing_network(
    logical: str, expected: str
) -> None:
    from gametool.windows_output_paths import native_output_path, logical_output_path

    assert native_output_path(logical) == expected
    assert native_output_path(logical_output_path(expected)) == expected


@pytest.mark.parametrize(
    "path",
    [
        r"\\.\PhysicalDrive0",
        r"\\?\GLOBALROOT\Device\HarddiskVolume1\out",
        r"C:relative",
        r"relative\out",
        r"C:\out\..\escape",
        r"C:\out\trailing.",
        r"C:\out\trailing ",
        r"C:\out\NUL.txt",
        r"C:\out\name:stream",
        r"\\?\C:\out/name",
    ],
)
def test_io_spelling_rejects_ambiguous_or_device_paths(path: str) -> None:
    from gametool.windows_output_paths import native_output_path

    with pytest.raises(ValueError, match="Windows"):
        native_output_path(path)


@pytest.mark.parametrize("deep", [False, True], ids=["short", "deep"])
def test_windows_public_name_exists_at_every_sync_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deep: bool
) -> None:
    root = _deep_root(tmp_path) if deep else tmp_path
    target = Path(_fixture_io(root / "public.bin"))
    target.write_bytes(b"old-complete")
    seen: list[bytes] = []
    original_sync = durable_io.sync_directory

    def observe(parent: Path) -> None:
        assert target.exists(), "public name disappeared at a metadata seam"
        payload = target.read_bytes()
        assert payload in {b"old-complete", b"new-complete"}
        seen.append(payload)
        original_sync(parent)

    monkeypatch.setattr(durable_io, "sync_directory", observe)
    result = write_bytes_safely(str(root), "public.bin", b"new-complete")
    assert result.status is SafeWriteStatus.WRITTEN, result.error
    assert seen == [b"old-complete", b"new-complete", b"new-complete"]
    assert target.read_bytes() == b"new-complete"
    assert os.listdir(_fixture_io(root)) == ["public.bin"]


def test_windows_first_sync_crash_preserves_public_name(tmp_path: Path) -> None:
    from gametool.dev_test import create_test_environment

    root = _deep_root(tmp_path)
    target = Path(_fixture_io(root / "public.bin"))
    target.write_bytes(b"old-complete")
    before = target.stat()
    script = (
        "import os,sys\n"
        "from gametool import durable_io\n"
        "from gametool.safe_output import write_bytes_safely\n"
        "def crash(_parent):\n"
        "    os._exit(73)\n"
        "durable_io.sync_directory=crash\n"
        "write_bytes_safely(sys.argv[1], 'public.bin', b'new-complete')\n"
        "raise AssertionError('crash seam was not reached')\n"
    )
    child = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script, str(root)],
        cwd=Path(__file__).resolve().parents[1],
        env=create_test_environment(),
        check=False,
        timeout=30,
        capture_output=True,
    )
    assert child.returncode == 73, child.stderr.decode("utf-8", errors="replace")
    assert target.exists(), "crash left the previously public name missing"
    assert target.read_bytes() == b"old-complete"
    assert target.stat().st_ino == before.st_ino
    (backup,) = Path(_fixture_io(root)).glob(".gamexray-backup-*.tmp")
    assert backup.read_bytes() == b"old-complete"
    assert backup.stat().st_ino == before.st_ino
    (stage,) = Path(_fixture_io(root)).glob(".gamexray-stage-*.tmp")
    assert stage.read_bytes() == b"new-complete"


def test_backup_link_failure_never_falls_back_to_moving_public_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import safe_output_path_publication as publication

    target = tmp_path / "public.bin"
    target.write_bytes(b"old-complete")
    before = target.stat()

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOTSUP, "fixture hard links unavailable")

    monkeypatch.setattr(publication.os, "link", unavailable)
    result = write_bytes_safely(str(tmp_path), target.name, b"new-complete")
    assert result.status is SafeWriteStatus.FAILED
    assert "hard links unavailable" in result.error
    assert target.read_bytes() == b"old-complete"
    assert target.stat().st_ino == before.st_ino
    assert os.listdir(tmp_path) == [target.name]


def test_foreign_public_target_at_backup_seam_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _deep_root(tmp_path)
    target = Path(_fixture_io(root / "public.bin"))
    target.write_bytes(b"old-complete")
    foreign = Path(_fixture_io(root / "foreign.bin"))
    foreign.write_bytes(b"foreign-complete")
    foreign_inode = foreign.stat().st_ino
    called = False

    def replace_target(_parent: Path) -> None:
        nonlocal called
        if not called:
            called = True
            os.replace(foreign, target)

    monkeypatch.setattr(durable_io, "sync_directory", replace_target)
    result = write_bytes_safely(str(root), "public.bin", b"new-complete")
    assert result.status is SafeWriteStatus.FAILED
    assert target.read_bytes() == b"foreign-complete"
    assert target.stat().st_ino == foreign_inode
    (backup,) = Path(_fixture_io(root)).glob(".gamexray-backup-*.tmp")
    assert backup.read_bytes() == b"old-complete"


@pytest.mark.parametrize("commit_failure", [False, True])
def test_foreign_backup_at_commit_is_never_deleted_or_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit_failure: bool
) -> None:
    root = _deep_root(tmp_path)
    target = Path(_fixture_io(root / "public.bin"))
    target.write_bytes(b"old-complete")
    retained = Path(_fixture_io(root / "retained-old.bin"))
    replacements: list[Path] = []
    sync_calls = 0

    def replace_backup(_parent: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 2:
            (backup,) = Path(_fixture_io(root)).glob(".gamexray-backup-*.tmp")
            os.replace(backup, retained)
            backup.write_bytes(b"foreign-backup")
            replacements.append(backup)
            if commit_failure:
                raise OSError(errno.EIO, "fixture commit failure")

    monkeypatch.setattr(durable_io, "sync_directory", replace_backup)
    result = write_bytes_safely(str(root), "public.bin", b"new-complete")
    assert result.status is SafeWriteStatus.FAILED
    assert target.read_bytes() == b"new-complete"
    assert replacements[0].read_bytes() == b"foreign-backup"
    assert retained.read_bytes() == b"old-complete"


def test_foreign_public_target_at_failed_commit_is_never_rolled_back_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _deep_root(tmp_path)
    target = Path(_fixture_io(root / "public.bin"))
    target.write_bytes(b"old-complete")
    foreign = Path(_fixture_io(root / "foreign.bin"))
    foreign.write_bytes(b"foreign-complete")
    foreign_inode = foreign.stat().st_ino
    sync_calls = 0

    def replace_target(_parent: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 2:
            os.replace(foreign, target)
            raise OSError(errno.EIO, "fixture commit failure")

    monkeypatch.setattr(durable_io, "sync_directory", replace_target)
    result = write_bytes_safely(str(root), "public.bin", b"new-complete")
    assert result.status is SafeWriteStatus.FAILED
    assert target.read_bytes() == b"foreign-complete"
    assert target.stat().st_ino == foreign_inode
    (backup,) = Path(_fixture_io(root)).glob(".gamexray-backup-*.tmp")
    assert backup.read_bytes() == b"old-complete"


def test_new_target_concurrent_creator_is_not_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import safe_output_path_publication as publication

    root = _deep_root(tmp_path)
    target = Path(_fixture_io(root / "public.bin"))
    original_rename = publication.os.rename

    def create_before_rename(source, destination) -> None:
        Path(destination).write_bytes(b"foreign-new-target")
        original_rename(source, destination)

    monkeypatch.setattr(publication.os, "rename", create_before_rename)
    result = write_bytes_safely(str(root), "public.bin", b"new-complete")
    assert result.status is SafeWriteStatus.FAILED
    assert target.read_bytes() == b"foreign-new-target"
    assert os.listdir(_fixture_io(root)) == [target.name]


def test_new_target_foreign_commit_replacement_is_not_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _deep_root(tmp_path)
    target = Path(_fixture_io(root / "public.bin"))
    foreign = Path(_fixture_io(root / "foreign.bin"))
    foreign.write_bytes(b"foreign-new-target")
    foreign_inode = foreign.stat().st_ino

    def replace_after_rename(_parent: Path) -> None:
        os.replace(foreign, target)
        raise OSError(errno.EIO, "fixture new-target commit failure")

    monkeypatch.setattr(durable_io, "sync_directory", replace_after_rename)
    result = write_bytes_safely(str(root), "public.bin", b"new-complete")
    assert result.status is SafeWriteStatus.FAILED
    assert target.read_bytes() == b"foreign-new-target"
    assert target.stat().st_ino == foreign_inode
    assert os.listdir(_fixture_io(root)) == [target.name]


def test_publication_entry_rechecks_callers_original_stage_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _deep_root(tmp_path)
    target = Path(_fixture_io(root / "public.bin"))
    target.write_bytes(b"old-complete")
    original_publish = safe_output.publish_staged_path
    foreign_stage: list[Path] = []

    def replace_at_entry(staged_path, destination, *, expected_stage_identity) -> None:
        stage = Path(staged_path)
        os.replace(stage, _fixture_io(root / "retained-stage"))
        stage.write_bytes(b"foreign-stage")
        foreign_stage.append(stage)
        original_publish(
            staged_path, destination, expected_stage_identity=expected_stage_identity
        )

    monkeypatch.setattr(safe_output, "publish_staged_path", replace_at_entry)
    result = write_bytes_safely(str(root), "public.bin", b"new-complete")
    assert result.status is SafeWriteStatus.FAILED
    assert "staged output identity changed" in result.error
    assert target.read_bytes() == b"old-complete"
    assert foreign_stage[0].read_bytes() == b"foreign-stage"
    assert Path(_fixture_io(root / "retained-stage")).read_bytes() == b"new-complete"


def test_backup_name_collision_preserves_existing_foreign_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import UUID
    from gametool import safe_output_path_publication as publication

    target = tmp_path / "public.bin"
    target.write_bytes(b"old-complete")
    backup = tmp_path / f".gamexray-backup-{UUID(int=0).hex}.tmp"
    backup.write_bytes(b"foreign-backup")
    monkeypatch.setattr(publication, "uuid4", lambda: UUID(int=0))
    result = write_bytes_safely(str(tmp_path), target.name, b"new-complete")
    assert result.status is SafeWriteStatus.FAILED
    assert target.read_bytes() == b"old-complete"
    assert backup.read_bytes() == b"foreign-backup"
    assert set(os.listdir(tmp_path)) == {target.name, backup.name}


def test_owned_delete_handle_blocks_post_proof_namespace_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import windows_output_paths as paths

    root = _deep_root(tmp_path)
    owned = Path(_fixture_io(root / "owned.bin"))
    owned.write_bytes(b"owned-data")
    before = owned.stat()
    foreign = Path(_fixture_io(root / "foreign.bin"))
    foreign.write_bytes(b"foreign-data")
    foreign_before = foreign.stat()
    retained = Path(_fixture_io(root / "moved-owned.bin"))
    original_mark = paths._mark_owned_for_deletion
    denied: list[str] = []

    def race_after_handle_proof(kernel, handle, path) -> None:
        with pytest.raises(PermissionError):
            os.replace(path, retained)
        denied.append("move-owned")
        with pytest.raises(PermissionError):
            os.replace(foreign, path)
        denied.append("replace-with-foreign")
        original_mark(kernel, handle, path)

    monkeypatch.setattr(paths, "_mark_owned_for_deletion", race_after_handle_proof)
    assert paths.remove_owned_output(str(owned), (before.st_dev, before.st_ino))
    assert denied == ["move-owned", "replace-with-foreign"]
    assert not owned.exists()
    assert not retained.exists()
    assert foreign.read_bytes() == b"foreign-data"
    assert foreign.stat().st_ino == foreign_before.st_ino


def test_owned_delete_handle_keeps_mismatched_and_missing_objects(
    tmp_path: Path,
) -> None:
    from gametool.windows_output_paths import remove_owned_output

    target = tmp_path / "foreign.bin"
    target.write_bytes(b"foreign-data")
    before = target.stat()
    assert not remove_owned_output(str(target), (before.st_dev, before.st_ino + 1))
    assert target.read_bytes() == b"foreign-data"
    assert target.stat().st_ino == before.st_ino
    assert not remove_owned_output(str(tmp_path / "missing.bin"), (0, 0))

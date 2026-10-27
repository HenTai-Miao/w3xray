"""Real Windows source-read boundaries for trusted description caches."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

import pytest

from gametool.trusted_description_cache import (
    TrustedDescriptionCacheError,
    load_trusted_description_cache,
)
from gametool import windows_source_reads
from gametool.dev_test import create_test_environment
from tests.description_cache_migration_fixture import LEGACY_RELATIVE
from tests.source_parent_swap_fixture import OpenFile, OpenPath
from tests.trusted_description_cache_fixture import published_cache


@pytest.mark.skipif(os.name != "nt", reason="requires Windows source-read boundary")
def test_windows_trusted_replay_preserves_proof_and_releases_source_handles(
    tmp_path: Path,
) -> None:
    """Normal replay retains exact proof and does not leave source paths locked."""
    root = published_cache(tmp_path)
    report = tmp_path / "legacy-output" / LEGACY_RELATIVE / "对象描述.tsv"
    verified = load_trusted_description_cache(root)
    assert (
        verified.cache.lookup("物品", "ratf", "扩展提示", None)[0].raw_value
        == "原版说明"
    )
    report.rename(report.with_suffix(".moved.tsv"))
    (tmp_path / "legacy-output").rename(tmp_path / "released-source")


@pytest.mark.skipif(os.name != "nt", reason="requires Windows source-read boundary")
def test_windows_trusted_replay_accepts_extended_source_paths(tmp_path: Path) -> None:
    """Extended path input retains Unicode evidence beyond Win32's short limit."""
    extended = Path("\\\\?\\" + str(tmp_path))
    for _ in range(4):
        extended /= "完整来源目录" * 8
    extended.mkdir(parents=True)
    assert len(str(extended)) > 260
    root = published_cache(extended)
    verified = load_trusted_description_cache(root)
    assert (
        verified.cache.lookup("物品", "ratf", "扩展提示", None)[0].raw_value
        == "原版说明"
    )
    (extended / "legacy-output").rename(extended / "released-source")


@pytest.mark.skipif(os.name != "nt", reason="requires Windows source-read boundary")
@pytest.mark.parametrize("component", ("source-root", "ancestor", "nested"))
def test_windows_trusted_replay_rejects_junction_source_components(
    tmp_path: Path,
    component: str,
) -> None:
    """Every directory level rejects a real junction to identical source bytes."""
    root = published_cache(tmp_path)
    source = tmp_path / "legacy-output"
    target = {
        "source-root": source,
        "ancestor": source / "地图",
        "nested": (source / LEGACY_RELATIVE),
    }[component]
    moved = tmp_path / "junction-target"
    target.rename(moved)
    created = subprocess.run(
        ("cmd.exe", "/d", "/c", "mklink", "/J", str(target), str(moved)),
        check=False,
        capture_output=True,
    )
    assert created.returncode == 0, created.stderr.decode(errors="replace")
    assert target.is_junction()

    with pytest.raises(TrustedDescriptionCacheError, match="source|symlink|regular"):
        _ = load_trusted_description_cache(root)
    target.rmdir()
    moved.rename(target)
    assert len(load_trusted_description_cache(root).cache.entries) == 1


@pytest.mark.skipif(os.name != "nt", reason="requires Windows source-read boundary")
def test_windows_trusted_replay_rejects_hardlinked_parent_aba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An identical-inode mirror must not hide an intermediate linked parent."""
    root = published_cache(tmp_path)
    report = tmp_path / "legacy-output" / LEGACY_RELATIVE / "对象描述.tsv"
    source_parent = tmp_path / "legacy-output" / "地图"
    moved_parent = tmp_path / "moved-map-parent"
    mirror = tmp_path / "hardlinked-parent"
    mirror_report = mirror / report.relative_to(source_parent)
    mirror_report.parent.mkdir(parents=True)
    mirror_report.hardlink_to(report)
    assert mirror_report.stat().st_ino == report.stat().st_ino
    events: list[str] = []
    monkeypatch.setattr(
        os,
        "open",
        _swapping_open_to_mirror(
            os.open, source_parent, moved_parent, mirror, report, events
        ),
    )

    with pytest.raises(TrustedDescriptionCacheError, match="source|symlink|regular"):
        _ = load_trusted_description_cache(root)
    assert events == ["parent swap blocked"]
    assert not source_parent.is_symlink()
    assert not moved_parent.exists()
    source_parent.rename(moved_parent)
    moved_parent.rename(source_parent)
    report.rename(report.with_suffix(".released.tsv"))


@pytest.mark.skipif(os.name != "nt", reason="requires Windows source-read boundary")
def test_windows_trusted_replay_rejects_short_source_read_and_releases_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Premature EOF cannot prove a complete file and must release its locks."""
    root = published_cache(tmp_path)
    source = tmp_path / "legacy-output"
    report = source / LEGACY_RELATIVE / "对象描述.tsv"
    report_identity = report.stat().st_ino
    real_read = os.read

    def short_read(descriptor: int, count: int) -> bytes:
        if os.fstat(descriptor).st_ino == report_identity:
            return b""
        return real_read(descriptor, count)

    monkeypatch.setattr(os, "read", short_read)
    with pytest.raises(TrustedDescriptionCacheError, match="changed while reading"):
        _ = load_trusted_description_cache(root)
    report.rename(report.with_suffix(".released.tsv"))
    source.rename(tmp_path / "released-source")
    tmp_path.rename(tmp_path.with_name(tmp_path.name + "-released"))


@pytest.mark.skipif(os.name != "nt", reason="requires Windows source-read boundary")
def test_windows_trusted_replay_rejects_nonregular_leaf_and_releases_handles(
    tmp_path: Path,
) -> None:
    """A directory in place of the report cannot be accepted or remain locked."""
    root = published_cache(tmp_path)
    source = tmp_path / "legacy-output"
    report = source / LEGACY_RELATIVE / "对象描述.tsv"
    report.unlink()
    report.mkdir()
    with pytest.raises(TrustedDescriptionCacheError, match="regular file"):
        _ = load_trusted_description_cache(root)
    report.rmdir()
    source.rename(tmp_path / "released-source")


@pytest.mark.skipif(os.name != "nt", reason="requires Windows source-read boundary")
def test_windows_trusted_replay_rejects_existing_writer_and_releases_handles(
    tmp_path: Path,
) -> None:
    """A writer already holding the source causes a closed, diagnosable failure."""
    root = published_cache(tmp_path)
    source = tmp_path / "legacy-output"
    report = source / LEGACY_RELATIVE / "对象描述.tsv"
    with report.open("r+b"):
        with pytest.raises(TrustedDescriptionCacheError, match="source.*unreadable"):
            _ = load_trusted_description_cache(root)
    assert len(load_trusted_description_cache(root).cache.entries) == 1
    report.rename(report.with_suffix(".released.tsv"))
    source.rename(tmp_path / "released-source")


@pytest.mark.skipif(os.name != "nt", reason="requires Windows source-read boundary")
def test_windows_trusted_replay_reports_close_failure_and_releases_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native close diagnostic retains the public error and releases ancestors."""
    root = published_cache(tmp_path)
    source = tmp_path / "legacy-output"
    report = source / LEGACY_RELATIVE / "对象描述.tsv"
    real_open = windows_source_reads._SourceApi.open
    real_close = windows_source_reads._SourceApi.close
    source_handles: set[int] = set()

    def tracked_open(
        api: windows_source_reads._SourceApi,
        path: Path,
        *,
        directory: bool = False,
    ) -> int:
        handle = real_open(api, path, directory=directory)
        if path == source:
            source_handles.add(handle)
        return handle

    def close_with_diagnostic(
        api: windows_source_reads._SourceApi, handle: int
    ) -> None:
        real_close(api, handle)
        if handle in source_handles:
            source_handles.remove(handle)
            raise OSError("native-close diagnostic")

    monkeypatch.setattr(windows_source_reads._SourceApi, "open", tracked_open)
    monkeypatch.setattr(windows_source_reads._SourceApi, "close", close_with_diagnostic)
    with pytest.raises(TrustedDescriptionCacheError, match="native-close diagnostic"):
        _ = load_trusted_description_cache(root)
    report.rename(report.with_suffix(".released.tsv"))
    source.rename(tmp_path / "released-source")
    tmp_path.rename(tmp_path.with_name(tmp_path.name + "-released"))


@pytest.mark.skipif(os.name != "nt", reason="requires Windows source-read boundary")
def test_windows_trusted_replay_accepts_traverse_only_source_and_restores_acl(
    tmp_path: Path,
) -> None:
    """A readable known report needs traversal, with the same native protection."""
    root = published_cache(tmp_path)
    source = tmp_path / "legacy-output"
    report = source / LEGACY_RELATIVE / "对象描述.tsv"
    probe = tmp_path / "traverse_only_probe.py"
    probe.write_text(
        dedent(
            """\
            import ctypes
            from pathlib import Path
            import sys
            from gametool import windows_source_reads as native
            from gametool.trusted_description_cache import (
                TrustedDescriptionCacheError, load_trusted_description_cache,
            )
            from tests.description_cache_migration_fixture import LEGACY_RELATIVE

            source = Path(sys.argv[1])
            cache = source.parent / "trusted"
            report = source / LEGACY_RELATIVE / "对象描述.tsv"
            assert report.read_bytes()
            try:
                list(source.iterdir())
            except PermissionError:
                pass
            else:
                raise AssertionError("fixture must deny directory listing")
            verified = load_trusted_description_cache(cache)
            assert verified.cache.lookup("物品", "ratf", "扩展提示", None)[0].raw_value == "原版说明"
            with native.WindowsSourceRoot.open(source):
                try:
                    source.rename(source.with_name("moved-source"))
                except PermissionError as error:
                    assert error.winerror == 32
                else:
                    raise AssertionError("protected source directory was renamed")
            api = native._SourceApi()
            writer = api.kernel.CreateFileW(
                native.native_output_path(str(source)), 0x82, 7, None, 3, 0x02200000, None,
            )
            if writer in (None, ctypes.c_void_p(-1).value):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                try:
                    load_trusted_description_cache(cache)
                except TrustedDescriptionCacheError as error:
                    assert "WinError 32" in str(error)
                else:
                    raise AssertionError("existing directory writer was accepted")
            finally:
                api.close(writer)
            assert len(load_trusted_description_cache(cache).cache.entries) == 1
            print("TRAVERSE_PROOF_AND_SHARING_VERIFIED")
            """
        ),
        encoding="utf-8",
    )
    controller = tmp_path / "traverse_only_acl.ps1"
    controller.write_text(
        dedent(
            """\
            param([string]$Directory, [string]$Script, [string]$Python)
            $ErrorActionPreference = 'Stop'
            # Set a stable protected baseline only on this new private fixture.
            $baseline = [System.IO.Directory]::GetAccessControl($Directory)
            $baseline.SetAccessRuleProtection($true, $true)
            [System.IO.Directory]::SetAccessControl($Directory, $baseline)
            $original = [System.IO.Directory]::GetAccessControl($Directory)
            $saved = $original.GetSecurityDescriptorSddlForm('All')
            $updated = [System.IO.Directory]::GetAccessControl($Directory)
            $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
            $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
                $sid, [System.Security.AccessControl.FileSystemRights]::ListDirectory,
                [System.Security.AccessControl.InheritanceFlags]::None,
                [System.Security.AccessControl.PropagationFlags]::None,
                [System.Security.AccessControl.AccessControlType]::Deny)
            $updated.AddAccessRule($rule)
            try {
                [System.IO.Directory]::SetAccessControl($Directory, $updated)
                & $Python -B -X utf8 $Script $Directory
                $code = $LASTEXITCODE
            } finally {
                $restore = [System.Security.AccessControl.DirectorySecurity]::new()
                $restore.SetSecurityDescriptorSddlForm($saved, [System.Security.AccessControl.AccessControlSections]::Access)
                [System.IO.Directory]::SetAccessControl($Directory, $restore)
                $after = [System.IO.Directory]::GetAccessControl($Directory)
                if ($saved -ne $after.GetSecurityDescriptorSddlForm('All')) {
                    throw 'Fixture ACL was not restored exactly'
                }
                Write-Output 'ACL_RESTORED_EXACT'
            }
            exit $code
            """
        ),
        encoding="utf-8",
    )
    env = create_test_environment()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        (
            str(
                Path(os.environ["SystemRoot"])
                / "System32/WindowsPowerShell/v1.0/powershell.exe"
            ),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(controller),
            "-Directory",
            str(source),
            "-Script",
            str(probe),
            "-Python",
            sys.executable,
        ),
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "TRAVERSE_PROOF_AND_SHARING_VERIFIED" in completed.stdout
    assert "ACL_RESTORED_EXACT" in completed.stdout
    assert root.is_dir()
    report.rename(report.with_suffix(".released.tsv"))
    source.rename(tmp_path / "released-source")


def _swapping_open_to_mirror(
    real_open: OpenFile,
    source_parent: Path,
    moved_parent: Path,
    mirror: Path,
    report: Path,
    events: list[str],
) -> OpenFile:
    def open_after_swap(
        path: OpenPath,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if events or os.fsdecode(path) != str(report):
            return real_open(path, flags, mode)
        try:
            source_parent.rename(moved_parent)
        except PermissionError:
            events.append("parent swap blocked")
            raise
        source_parent.symlink_to(mirror, target_is_directory=True)
        events.append("parent swapped")
        try:
            return real_open(path, flags, mode)
        finally:
            source_parent.unlink()
            moved_parent.rename(source_parent)
            events.append("parent restored")

    return open_after_swap

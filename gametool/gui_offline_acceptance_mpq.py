"""Authored real MPQ bytes and complete public GUI extraction acceptance."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import tkinter as tk
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

if TYPE_CHECKING:
    from .gui import App
    from .gui_offline_acceptance_support import _Fixtures


# This explicitly authored MPQ is data only. Its JASS text is never executed.
_ARCHIVE_BASE64 = (
    "TVBRGiAAAAB3BAAAAAADACAAAAAgAgAAIAAAAAkAAAAzMMN5KNkymLxzb5+yiE7pBY67ygwngh5wRuM4QNklf8Ku"
    "lLUDqwc0vwMhJfUfGwOkR1UPbXck0K5HEN2gVpCqxS349DJCJFqR7oAU+vvEettdwdttMmR/MoNHZD9FXrMmq5Oi"
    "7gWzKm53yC0dTGC7RjPz0NP3f7VSWFPb253kG9w71aCO0PPmc+XKvaDvTT2/SeBc6LwPz4k8ZLnb5mIRYMUcNi3N"
    "27/s2CkxtTGLLMYQC91dfQQ2fdx6dXIQsF51DLSn1Ouk13azAJshCaDPOtW7NEfYXJJGR8xTT2t7o2Fh9laNr+rY"
    "iRa6P/iL1nBbWizqBOHdBSXk9sn3gUo0/MP3tUmfFjuI7r4T0frCYZI3f6IEQ90dqabi0ZbXXdR1MO3VXnq5ab+o"
    "RanR2XH9FhcKpKNVc+sicLLPq68mnKyHWSlelgGAQ2WReHBp5FCP/UXjuOorIlkkBnCryEGcMOHXHP1i+n28KBuz"
    "hXum7MbO0om4wKPv3dp43EqSujGpQeHeErIvkfPWgr+FzlTbEajNwZbBNuPKgdrg438EJgdsTt5NxYirJG4rmShY"
    "cviRCBdv+lUeKNv3RTRtDHzoMp1a8D+f1ME+7TxyR9AAkMi7d5j6TebSXxANKAx41e+r31hgVBCbQXX9WX1HxRBU"
    "wF/GGQGPMwX3JYN8qKnBNjtlSD2l1gjKYw82+AFsP+lc1w21THdrPU8p489N7vLUnV/Mz6SyA0M28oJ45FQFASC7"
    "mObdX1tDDPkg6ZDi6gfvH3K6Ub3Y/64t+d/MfcvpIth0PbkevGWh20jyRW+Gs88af+nzlg6jnRk7PwMESyHvb5T/"
    "0gdF6SrI7vYqaHLfEBY76PMYSWkLG3VnD546zG2TIua7GQW5T2YafisPPqNylt1+ecz/eX06mE/eZi4YbhbLPz7j"
    "ELlpJnHiv/w9rk7JDliRuutLr7y9ebVWF43LibGnNKOpOUPPGD4QUNtojrJb6LXdmIYTMiurXQo8TT6TFO3PGgb5"
    "TBgq8CB6zv9tKnnfBrlcowbNhml6NBBVjuRgUrzVdPwbuJUrY5L4S5OkZ2bSyTiB+qLIbpZFquWOo3hcLOvwjtLJ"
    "OIH6oMJ4g1m8DfXvRtIxHt8lfL+WXG9hZAjpLhFvQZqh88atsKAWA5zkcIYsTFQ+17t9Tw4v0RoCp5POd4nCSvNp"
    "OURkxYvu61TLykbo0f9JgKtTvILVcsiCq27e/kBnq60nWvVhuXrKGYIrTDt/RVNbjJbDo3nTZg/oVReD04tTDx0M"
    "MSL7j0AV+n1PP/ULvAAgYQyAC9hJCRQrLno+zlMnmKuRz0hIfYthZAlox4bb0LWbyVPO+CCyc6Zd3u9+ZIPGd5z7"
    "HcZD8DGi+tR5q11mMj1tK9bgnrtc1nphZBNnS2hCc3n+f0OpPKHhp3gsTwVzH/kCvWTbg5lWwvvtytZNEE2e1a/S"
    "2Ai94xnQJpXtqx1q7fZKADATyGBk"
)
_EXPECTED: dict[str, Any] = {
    "fixture_sha256": "a1ec71f5dad5c74138461ec2079d48645b263712629d20e9f99f41c47b69fd47",
    "fixture_bytes": 1143,
    "fixture_authored_by": "GameXRay static audit; synthetic bytes and inert script text "
    "for static parsing/export only; never executed",
    "public_api": "gametool.api.export_all_files(source, output)",
    "gui": "Export all files action in gui_export_actions.py",
    "members": [
        {
            "block_index": 0,
            "hash_index": 6,
            "name": "war3map.j",
            "locale": 0,
            "platform": 0,
            "plaintext_hex": "66756e6374696f6e206d61696e2074616b6573206e6f7468696e672072657475726e73206e6f7468696e670a63616c6c205072656c6f616428224d6f64656c735c5c4865726f2e6d646c22290a63616c6c205072656c6f6164282261737365742e626c7022290a63616c6c205072656c6f616428224d697373696e674d6f64656c2e6d646c22290a656e6466756e6374696f6e0a",
            "plaintext_sha256": "170e17efda9640ae0e08b492119c7cf4c93bfb00b01b116ff8d0b68c4c12649b",
            "expected_path": "war3map.j",
            "expected_storage": "decoded original bytes",
            "expected_recovered_manifest_ok": False,
        },
        {
            "block_index": 1,
            "hash_index": 25,
            "name": "asset.blp",
            "locale": 0,
            "platform": 0,
            "plaintext_hex": "424c50312d6e65757472616c2d7061796c6f6164",
            "plaintext_sha256": "086941430bb49ef522316d0a16bbd912583d2ade4b0e5a184d16ee5729a59938",
            "expected_path": "asset.blp",
            "expected_storage": "decoded original bytes",
            "expected_recovered_manifest_ok": True,
        },
        {
            "block_index": 2,
            "hash_index": 26,
            "name": "asset.blp",
            "locale": 1033,
            "platform": 0,
            "plaintext_hex": "424c50312d6c6f63616c697a65642d303430392d7061796c6f6164",
            "plaintext_sha256": "f962f6bf4314bd704576771a29edd64cfc4e559df039768c59e7fddcb8d7028d",
            "expected_path": "RecoveredNames/blocks/block_000002-locale_0409-platform_00.blp",
            "expected_storage": "decoded original bytes",
            "expected_recovered_manifest_ok": True,
        },
        {
            "block_index": 3,
            "hash_index": 11,
            "name": "Models\\Hero.mdx",
            "locale": 0,
            "platform": 0,
            "plaintext_hex": "4d444c584d4f444c50000000496d706f727465644865726f000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000054455853150000000054657874757265735ce88bb1e99b842e626c7000",
            "plaintext_sha256": "cebd3b06a0d020cae066c6686a6706846eb531ed94986d5a134f3ac5b6fc4867",
            "expected_path": "Models/Hero.mdx",
            "expected_storage": "decoded original bytes",
            "expected_recovered_manifest_ok": True,
        },
        {
            "block_index": 4,
            "hash_index": 12,
            "name": "Models\\Hero_Portrait.mdx",
            "locale": 0,
            "platform": 0,
            "plaintext_hex": "4d444c582d6865726f2d706f7274726169742d7061796c6f6164",
            "plaintext_sha256": "0671139f776a4c9d1be0e54065562b1173fefae86a83e756823b9845b0e63f33",
            "expected_path": "Models/Hero_Portrait.mdx",
            "expected_storage": "decoded original bytes",
            "expected_recovered_manifest_ok": True,
        },
        {
            "block_index": 5,
            "hash_index": 14,
            "name": "war3mapImported\\ImportedHero.mdx",
            "locale": 0,
            "platform": 0,
            "plaintext_hex": "4d444c582d696d706f727465642d7061796c6f6164",
            "plaintext_sha256": "9c27427c37ce10c3faad7fb30646317a83bbe78e34953e00cd99a886ac407a26",
            "expected_path": "war3mapImported/ImportedHero.mdx",
            "expected_storage": "decoded original bytes",
            "expected_recovered_manifest_ok": True,
        },
        {
            "block_index": 6,
            "hash_index": 2,
            "name": "war3mapImported\\ImportedHero_Portrait.mdx",
            "locale": 0,
            "platform": 0,
            "plaintext_hex": "4d444c582d696d706f727465642d706f7274726169742d7061796c6f6164",
            "plaintext_sha256": "3f5da9a429e1b9aa55a42daae92c07adb618369313bfeaf79239344b34dc3bb5",
            "expected_path": "war3mapImported/ImportedHero_Portrait.mdx",
            "expected_storage": "decoded original bytes",
            "expected_recovered_manifest_ok": True,
        },
        {
            "block_index": 7,
            "hash_index": 31,
            "name": "Textures\\英雄.blp",
            "locale": 0,
            "platform": 0,
            "plaintext_hex": "424c50312d757466382d746578747572652d7061796c6f6164",
            "plaintext_sha256": "0b60f1db7d7e96182879a99aa1352f3005bf17af9459acf3e0bf8e308ad45672",
            "expected_path": "Textures/英雄.blp",
            "expected_storage": "decoded original bytes",
            "expected_recovered_manifest_ok": True,
        },
        {
            "block_index": 8,
            "hash_index": 1,
            "name": "Unreferenced.bin",
            "locale": 0,
            "platform": 0,
            "plaintext_hex": "756e6b6e6f776e2d73696e676c652d756e69742d656e637279707465642d7061796c6f6164",
            "plaintext_sha256": "54015904e200b805299c8fb0590180429b24b117f1f36934da35bd8d7b413f29",
            "expected_path": "UnknownRaw/File000008.mpqraw",
            "expected_storage": "raw ciphertext",
            "expected_recovered_manifest_ok": False,
            "stored_hex": "db839956c2fbedcad64d104d9ed5afd2d808bde319d02695edab1d6aedf64a003013c86064",
            "stored_sha256": "95fd245ca26aa1836ab608137736562c493eee783d25e2f900d70e4ef414afd5",
        },
    ],
    "must_not_exist": [
        "Models/Hero.mdl",
        "MissingModel.mdl",
        "MissingModel.mdx",
        "MissingModel_Portrait.mdx",
        "Unreferenced.bin",
    ],
    "manifest": "RecoveredNames/manifest.tsv",
    "manifest_ok_blocks": [1, 2, 3, 4, 5, 6, 7],
    "unknown_manifest": "UnknownRaw/manifest.tsv",
    "unknown_manifest_blocks": [8],
    "manifest_alias_identities": [
        {
            "block": 0,
            "locale": 0,
            "platform": 0,
            "hash_index": 6,
            "name": "war3map.j",
            "path": "war3map.j",
            "size": 148,
            "sha256": "170e17efda9640ae0e08b492119c7cf4c93bfb00b01b116ff8d0b68c4c12649b",
            "reason": "verified-entry-for-exported-block",
        },
        {
            "block": 7,
            "locale": 0,
            "platform": 0,
            "hash_index": 31,
            "name": "Textures\\鑻遍泟.blp",
            "path": "Textures/英雄.blp",
            "size": 25,
            "sha256": "0b60f1db7d7e96182879a99aa1352f3005bf17af9459acf3e0bf8e308ad45672",
            "reason": "verified-alternative-name-for-same-block",
        },
    ],
}


def archive_fixture_payloads() -> dict[str, bytes]:
    from .gui_offline_acceptance_support import _require

    payload = base64.b64decode(_ARCHIVE_BASE64, validate=True)
    _require(
        len(payload) == _EXPECTED["fixture_bytes"]
        and hashlib.sha256(payload).hexdigest() == _EXPECTED["fixture_sha256"],
        "明确作者 MPQ 夹具字节损坏",
    )
    return {
        "archive-recovery.w3x": payload,
        "archive-recovery.expected.json": (
            json.dumps(_EXPECTED, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }


def validate_archive_export(output: Path) -> None:
    """Check each independently authored payload and exact recovered identity."""
    from .gui_offline_acceptance_support import _require

    members = _EXPECTED["members"]
    for row in members:
        expected = bytes.fromhex(row.get("stored_hex", row["plaintext_hex"]))
        _require(
            (output / row["expected_path"]).read_bytes() == expected,
            f"导出块字节或 locale 归属不符: {row['block_index']}",
        )
    for name in _EXPECTED["must_not_exist"]:
        _require(not (output / name).exists(), f"无证据名称被误导出: {name}")
    raw = (output / _EXPECTED["manifest"]).read_text("utf-8")
    _require(
        all(line.startswith(("OK\t", "ALIAS\t")) for line in raw.splitlines()),
        "恢复 manifest 存在失败、跳过或未知状态",
    )
    rows = [
        dict(cell.split("=", 1) for cell in line.split("\t")[1:])
        for line in raw.splitlines()
        if line.startswith("OK\t")
    ]
    expected_rows = {
        row["block_index"]: row
        for row in members
        if row["expected_recovered_manifest_ok"]
    }
    _require(
        len(rows) == len(expected_rows)
        and {int(row["block"]) for row in rows} == set(expected_rows),
        "恢复 manifest 遗漏、重复或误认块",
    )
    for row in rows:
        expected = expected_rows[int(row["block"])]
        _require(
            int(row["locale"]) == expected["locale"]
            and int(row["platform"]) == expected["platform"]
            and json.loads(row["name"]) == expected["name"]
            and json.loads(row["path"]).replace("\\", "/") == expected["expected_path"]
            and row["sha256"] == expected["plaintext_sha256"]
            and int(row["size"]) == len(bytes.fromhex(expected["plaintext_hex"]))
            and row["type"] == Path(expected["expected_path"]).suffix.removeprefix(".")
            and int(row["hash_index"]) == expected["hash_index"],
            f"恢复 manifest 身份不符: {row['block']}",
        )
    aliases = [
        dict(cell.split("=", 1) for cell in line.split("\t")[1:])
        for line in raw.splitlines()
        if line.startswith("ALIAS\t")
    ]
    normalized_aliases = []
    for alias in aliases:
        normalized_aliases.append(
            {
                "block": int(alias["block"]),
                "locale": int(alias["locale"]),
                "platform": int(alias["platform"]),
                "hash_index": int(alias["hash_index"]),
                "name": json.loads(alias["name"]),
                "path": json.loads(alias["path"]).replace("\\", "/"),
                "size": int(alias["size"]),
                "sha256": alias["sha256"],
                "reason": alias["reason"],
            }
        )
    _require(
        sorted(normalized_aliases, key=lambda row: (row["block"], row["name"]))
        == sorted(
            _EXPECTED["manifest_alias_identities"],
            key=lambda row: (row["block"], row["name"]),
        ),
        "别名 manifest 遗漏、重复或错误归属已证明的 hash 条目",
    )
    all_files = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    _require(
        all_files
        == {row["expected_path"] for row in members}
        | {_EXPECTED["manifest"], _EXPECTED["unknown_manifest"]},
        "全部导出出现缺失或额外文件",
    )
    unknown = (output / _EXPECTED["unknown_manifest"]).read_text("utf-8")
    size = len(bytes.fromhex(members[-1]["stored_hex"]))
    _require(
        unknown
        == f"File000008.mpqraw\tblock=8\tcomp_size={size}\tfile_size={size}\tflags=0x81010000\traw_size={size}\treason=anonymous-block-unrecoverable\n",
        "未知加密块未保留准确的块身份、尺寸和原始输出证据",
    )


def exercise_archive_recovery(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from . import archive_export
    from .gui_offline_acceptance_support import (
        _require,
        _temporary_attribute,
        _wait_for,
    )
    from .gui_offline_acceptance_support import loaded_acceptance_map

    _ = owned
    destination = fixtures.root / "exports" / "archive-recovery"
    completed: list[tuple[str, int, str]] = []

    def finish(output: str, count: int, kind: str) -> None:
        completed.append((output, count, kind))

    def private_destination(*_args: object, **_kwargs: object) -> str:
        return str(destination)

    with (
        loaded_acceptance_map(app, fixtures.root / "archive-recovery.w3x"),
        _temporary_attribute(archive_export, "tmp_extract_dir", private_destination),
        _temporary_attribute(app, "_open_dir", finish),
    ):
        pending: list[tk.Misc] = [app]
        buttons: list[ctk.CTkButton] = []
        while pending:
            widget = pending.pop()
            if isinstance(widget, ctk.CTkButton) and widget.cget("text") == "导出全部":
                buttons.append(widget)
            pending.extend(widget.winfo_children())
        _require(len(buttons) == 1, "没有唯一的真实导出全部按钮")
        buttons[0].invoke()
        _wait_for(app, lambda: bool(completed), "真实全部归档导出", errors)
        _require(
            completed == [(str(destination), len(_EXPECTED["members"]) + 2, "文件")],
            "导出全部完成回调缺失或文件数量错误",
        )
        validate_archive_export(destination)

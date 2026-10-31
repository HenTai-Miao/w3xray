"""Read-only, complete offline inspection of explicitly selected War3Tools INIs.

The original bytes, every physical line, duplicate declarations and unknown
extensions remain evidence. No discovered executable, DLL, map or script is
opened as code. A final whole-set replay detects files added, removed or changed.
"""

from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import replace
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat

from .pack_query_numeric_values import decimal_value
from .save_text_encoding import (
    SAVE_TEXT_ENCODINGS,
    inspect_save_text,
    normalize_save_text_encoding,
)
from .war3tools_config_models import (
    War3ToolsBinding,
    War3ToolsConflict,
    War3ToolsDiagnostic,
    War3ToolsFile,
    War3ToolsInspection,
    War3ToolsInventoryEntry,
    War3ToolsRecord,
    War3ToolsSetting,
    War3ToolsSource,
)
from .war3tools_config_schema import (
    field_spec,
    keyboard_identity,
    section_category,
    slot_identity,
)
from .windows_output_paths import native_output_path, validate_output_root
from .windows_source_reads import WindowsSourceRoot


WAR3TOOLS_TEXT_ENCODINGS = SAVE_TEXT_ENCODINGS
_INTEGER = re.compile(r"[+-]?[0-9]+\Z")
_HEX = re.compile(r"[0-9a-fA-F]*\Z")
_PHYSICAL_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n|$)")


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
    )


def _unsafe(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _decode_source(
    payload: bytes, requested: str
) -> tuple[str | None, str, int, tuple[str, ...]]:
    """Auto accepts BOMs and strict UTF-8, never guesses a legacy code page."""
    markers = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff")
    selected = requested
    if requested == "auto" and not payload.startswith(markers):
        selected = "utf-8"
    decoded = inspect_save_text(payload, selected)
    notes = decoded.diagnostics
    if requested == "auto" and decoded.text is None:
        notes += (
            "自动模式只接受 BOM 声明或严格 UTF-8；已知旧编码时请明确选择 gb18030、utf-16-le 或 utf-16-be。",
        )
    return decoded.text, decoded.encoding, decoded.bom_bytes, notes


def _capture_source(
    path: Path, relative_path: str, requested: str
) -> tuple[War3ToolsSource, tuple[War3ToolsDiagnostic, ...]]:
    diagnostics: list[War3ToolsDiagnostic] = []
    payload = b""
    identity: tuple[int, ...] = ()
    stable = False
    read_complete = False
    try:
        source_io = native_output_path(str(path))
        with WindowsSourceRoot.open(path.parent) as held:
            with held.protect(PurePosixPath(path.name)):
                named = os.lstat(source_io)
                if _unsafe(named) or not stat.S_ISREG(named.st_mode):
                    raise ValueError("源必须是普通文件，不能是链接、重解析点或设备")
                identity = _identity(named)
                with open(source_io, "rb") as stream:
                    before = _identity(os.fstat(stream.fileno()))
                    payload = stream.read()
                    read_complete = True
                    after = _identity(os.fstat(stream.fileno()))
                    stream.seek(0)
                    repeated = hashlib.file_digest(stream, "sha256").hexdigest()
                    final = _identity(os.fstat(stream.fileno()))
                stable = (
                    before == after == final
                    and identity == _identity(os.lstat(source_io))
                    # Windows descriptor/path ctime have different clock domains.
                    and identity[:4] + identity[5:] == before[:4] + before[5:]
                    and len(payload) == named.st_size
                    and repeated == hashlib.sha256(payload).hexdigest()
                )
        if not stable:
            diagnostics.append(
                War3ToolsDiagnostic(
                    "source-unstable",
                    "error",
                    str(path),
                    "完整读取或复验期间来源发生变化；已读字节全部保留，请待原程序写入结束后重查。",
                )
            )
    except (OSError, ValueError) as exc:
        diagnostics.append(
            War3ToolsDiagnostic(
                "source-read",
                "error",
                str(path),
                f"无法稳定读取配置: {exc}",
            )
        )
        stable = False
    text, encoding, bom_bytes = None, "", 0
    if read_complete:
        text, encoding, bom_bytes, notes = _decode_source(payload, requested)
        diagnostics.extend(
            War3ToolsDiagnostic("source-encoding", "error", str(path), note)
            for note in notes
        )
    status = (
        "confirmed"
        if stable and text is not None
        else "encoding-error"
        if stable
        else "unstable"
        if read_complete
        else "read-error"
    )
    return War3ToolsSource(
        str(path),
        relative_path,
        hashlib.sha256(payload).hexdigest() if read_complete else "",
        len(payload),
        identity,
        base64.b64encode(payload).decode("ascii"),
        text,
        encoding,
        requested,
        bom_bytes,
        stable,
        status,
    ), tuple(diagnostics)


def _inventory(
    path: Path,
) -> tuple[
    tuple[War3ToolsInventoryEntry, ...],
    tuple[War3ToolsDiagnostic, ...],
    tuple[int, ...],
    bool,
]:
    """Full iterative traversal, including non-INI files and rejected entries."""
    entries: list[War3ToolsInventoryEntry] = []
    diagnostics: list[War3ToolsDiagnostic] = []
    root_identity: tuple[int, ...] = ()
    complete = True
    pending = [path]
    while pending:
        directory = pending.pop()
        try:
            with WindowsSourceRoot.open(directory):
                directory_io = native_output_path(str(directory))
                before = _identity(os.lstat(directory_io))
                if directory == path:
                    root_identity = before
                with os.scandir(directory_io) as scan:
                    children = sorted(
                        scan, key=lambda child: (child.name.casefold(), child.name)
                    )
                if not children:
                    diagnostics.append(
                        War3ToolsDiagnostic(
                            "empty-directory",
                            "info",
                            str(directory),
                            "目录为空；没有补造配置或扩展记录。",
                        )
                    )
                for child in children:
                    child_path = directory / child.name
                    relative = child_path.relative_to(path).as_posix()
                    try:
                        # Windows FindFirstFile metadata may lag a just-created
                        # directory and DirEntry.stat can expose dev/ino == 0.
                        # Compare fresh named identities in the same clock domain.
                        info = os.lstat(native_output_path(str(child_path)))
                        kind = (
                            "reparse"
                            if _unsafe(info)
                            else "directory"
                            if stat.S_ISDIR(info.st_mode)
                            else "file"
                            if stat.S_ISREG(info.st_mode)
                            else "special"
                        )
                        entries.append(
                            War3ToolsInventoryEntry(
                                str(child_path),
                                relative,
                                kind,
                                child_path.suffix.lower(),
                                info.st_size,
                                _identity(info),
                            )
                        )
                        if kind == "directory":
                            pending.append(child_path)
                        elif kind in {"reparse", "special"}:
                            complete = False
                            diagnostics.append(
                                War3ToolsDiagnostic(
                                    "inventory-unsafe-entry",
                                    "error",
                                    str(child_path),
                                    "保留此库存条目，不跟随链接、重解析点或特殊文件；该来源覆盖不完整。",
                                )
                            )
                    except OSError as exc:
                        complete = False
                        entries.append(
                            War3ToolsInventoryEntry(
                                str(child_path),
                                relative,
                                "unreadable",
                                child_path.suffix.lower(),
                                0,
                                (),
                            )
                        )
                        diagnostics.append(
                            War3ToolsDiagnostic(
                                "inventory-read", "error", str(child_path), str(exc)
                            )
                        )
                if before != _identity(os.lstat(directory_io)):
                    complete = False
                    diagnostics.append(
                        War3ToolsDiagnostic(
                            "inventory-unstable",
                            "error",
                            str(directory),
                            "目录在库存读取期间发生变化。",
                        )
                    )
        except (OSError, ValueError) as exc:
            complete = False
            diagnostics.append(
                War3ToolsDiagnostic("inventory-read", "error", str(directory), str(exc))
            )
    entries.sort(
        key=lambda entry: (entry.relative_path.casefold(), entry.relative_path)
    )
    return tuple(entries), tuple(diagnostics), root_identity, complete


def _parse_records(
    source: War3ToolsSource,
) -> tuple[tuple[War3ToolsRecord, ...], tuple[War3ToolsDiagnostic, ...]]:
    records: list[War3ToolsRecord] = []
    diagnostics: list[War3ToolsDiagnostic] = []
    section, occurrence = "", 0
    sections: dict[str, list[int]] = defaultdict(list)
    keys: dict[tuple[str, str], list[int]] = defaultdict(list)
    offset = source.bom_bytes
    for match in _PHYSICAL_LINE.finditer(source.raw_text or ""):
        raw = match.group(0)
        if not raw:
            continue
        line = len(records) + 1
        body = raw.rstrip("\r\n")
        stripped = body.strip(" \t")
        kind, key, value = "invalid", None, None
        if not stripped:
            kind = "blank"
        elif stripped.startswith((";", "#")):
            kind = "comment"
        elif stripped.startswith("["):
            header = re.fullmatch(r"\[([^\[\]\r\n]+)\]", stripped)
            if header is not None and header.group(1).strip(" \t"):
                section = header.group(1).strip(" \t")
                sections[section.casefold()].append(line)
                occurrence = len(sections[section.casefold()])
                kind = "section"
            else:
                # A malformed header cannot silently attach later keys to an old section.
                section, occurrence = "", 0
        elif "=" in body:
            raw_key, value = body.split("=", 1)
            key = raw_key.strip(" \t")
            if key and not any(ord(char) < 32 for char in key):
                kind = "entry"
                keys[(section.casefold(), key.casefold())].append(line)
                if not section:
                    diagnostics.append(
                        War3ToolsDiagnostic(
                            "entry-without-section",
                            "error",
                            source.path,
                            "键值行没有完整节名；保留原文，不继承损坏节名前的上下文。",
                            line,
                        )
                    )
        end = offset + len(raw.encode(source.encoding, errors="strict"))
        records.append(
            War3ToolsRecord(
                line, line, kind, raw, offset, end, section, occurrence, key, value
            )
        )
        offset = end
        if kind == "invalid":
            diagnostics.append(
                War3ToolsDiagnostic(
                    "malformed-line",
                    "error",
                    source.path,
                    "无法确认此行是完整 INI 声明；完整原文和字节区间已保留。",
                    line,
                )
            )
    for name, lines in sections.items():
        if len(lines) > 1:
            diagnostics.append(
                War3ToolsDiagnostic(
                    "duplicate-section",
                    "error",
                    source.path,
                    f"节名 {name!r} 重复或仅大小写不同，共 {len(lines)} 处；没有选择合并或覆盖规则。",
                    lines[0],
                    tuple(lines),
                )
            )
    for (_, key), lines in keys.items():
        if len(lines) > 1:
            diagnostics.append(
                War3ToolsDiagnostic(
                    "duplicate-key",
                    "error",
                    source.path,
                    f"同节键 {key!r} 重复或仅大小写不同，共 {len(lines)} 处；保留每个值，不选择最后一项。",
                    lines[0],
                    tuple(lines),
                )
            )
    return tuple(records), tuple(diagnostics)


def _key_code(value: str) -> int | None:
    text = value.strip(" \t")
    if _INTEGER.fullmatch(text) is None:
        return None
    digits = text.removeprefix("+").lstrip("0") or "0"
    if len(digits) > 3 or digits.startswith("-"):
        return None
    number = int(digits)
    return number if number <= 255 else None


def _key_name(code: int) -> str:
    if 48 <= code <= 57 or 65 <= code <= 90:
        return f"{chr(code)} (VK {code})"
    if 96 <= code <= 105:
        return f"NumPad {code - 96} (VK {code})"
    if 112 <= code <= 135:
        return f"F{code - 111} (VK {code})"
    names = {
        1: "鼠标左键",
        2: "鼠标右键",
        4: "鼠标中键",
        8: "Backspace",
        9: "Tab",
        13: "Enter",
        16: "Shift",
        17: "Ctrl",
        18: "Alt",
        27: "Esc",
        32: "Space",
        191: "VK_OEM_2（布局相关）",
    }
    return (
        f"{names[code]} (VK {code})" if code in names else f"键码 {code}（未解释键名）"
    )


def _settings(
    source: War3ToolsSource,
    records: tuple[War3ToolsRecord, ...],
    parse_notes: tuple[War3ToolsDiagnostic, ...],
) -> tuple[tuple[War3ToolsSetting, ...], tuple[War3ToolsDiagnostic, ...]]:
    settings: list[War3ToolsSetting] = []
    diagnostics: list[War3ToolsDiagnostic] = []
    ambiguous_sections = {
        record.section.casefold()
        for record in records
        if record.kind == "section" and record.section_occurrence > 1
    }
    ambiguous_lines = {
        line
        for note in parse_notes
        if note.code == "duplicate-key"
        for line in note.related_lines
    }
    for record in records:
        if record.kind != "entry" or record.key is None or record.value is None:
            continue
        spec = field_spec(source.relative_path, record.section, record.key)
        value = record.value.strip(" \t")
        state = "declared"
        interpreted: str | bool | None = None
        if spec is None:
            state = "unknown"
            diagnostics.append(
                War3ToolsDiagnostic(
                    "unknown-setting",
                    "info",
                    source.path,
                    f"未确认 [{record.section}] {record.key} 的语义；完整原值已保留。",
                    record.line,
                )
            )
        elif spec.kind == "switch":
            if value in {"0", "1"}:
                interpreted = value == "1"
            else:
                state = "invalid"
        elif spec.kind == "keycode":
            code = _key_code(value)
            if value == "" or code == 0:
                state = "unbound"
            elif code is None:
                state = "invalid"
            else:
                interpreted = _key_name(code)
        elif spec.kind in {"integer", "number"}:
            valid = (
                _INTEGER.fullmatch(value) is not None
                if spec.kind == "integer"
                else decimal_value(value) is not None and not value.startswith("'")
            )
            if valid:
                interpreted = value
            else:
                state = "invalid"
        elif spec.kind in {"utf8_hex", "opaque_hex", "color_hex"}:
            if (
                _HEX.fullmatch(value) is None
                or len(value) % 2
                or spec.kind == "color_hex"
                and len(value) != 8
            ):
                state = "invalid"
            elif spec.kind == "utf8_hex":
                try:
                    interpreted = bytes.fromhex(value).decode("utf-8", errors="strict")
                except UnicodeError:
                    state = "invalid"
            else:
                state = "opaque" if spec.kind == "opaque_hex" else "declared"
                interpreted = value
        else:
            interpreted = value
        if state == "invalid":
            diagnostics.append(
                War3ToolsDiagnostic(
                    "invalid-setting-value",
                    "error",
                    source.path,
                    f"字段 {record.key} 无法按已知 {spec.kind if spec else '未知'} 声明格式解释；没有补默认值。",
                    record.line,
                )
            )
        if (
            record.line in ambiguous_lines
            or record.section.casefold() in ambiguous_sections
        ):
            state, interpreted = "ambiguous", None
        settings.append(
            War3ToolsSetting(
                source.path,
                record.line,
                record.section,
                record.section_occurrence,
                record.key,
                record.value,
                spec.category
                if spec
                else section_category(source.relative_path, record.section)
                or "unknown",
                spec.kind if spec else "unknown",
                spec.label if spec else record.key,
                state,
                interpreted,
            )
        )
    return tuple(settings), tuple(diagnostics)


def _bindings(
    files: tuple[War3ToolsFile, ...],
) -> tuple[tuple[War3ToolsBinding, ...], tuple[War3ToolsDiagnostic, ...]]:
    bindings: list[War3ToolsBinding] = []
    diagnostics: list[War3ToolsDiagnostic] = []
    shortcuts = {
        "MenuShortcutKey": (
            "MenuShortcutEnabled",
            ("MenuShortcutModifierA", "MenuShortcutModifierB"),
        ),
        "BorderlessFullscreenShortcutKey": (
            None,
            ("BorderlessFullscreenShortcutModifiers",),
        ),
        "MinimapQuestionMarkSignalKey": ("MinimapQuestionMarkSignal", ()),
        "CameraUnitLockShortcutKey": (None, ("CameraUnitLockShortcutModifiers",)),
        "InventoryDropShortcutKey": (
            "InventoryDropEnabled",
            ("InventoryDropShortcutModifierMask",),
        ),
    }
    for file in files:
        groups: dict[tuple[str, int], dict[str, list[War3ToolsSetting]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for setting in file.settings:
            groups[(setting.section, setting.section_occurrence)][setting.key].append(
                setting
            )
        for (section, occurrence), fields in groups.items():

            def unique(key: str) -> War3ToolsSetting | None:
                rows = fields.get(key, [])
                return (
                    rows[0]
                    if len(rows) == 1 and rows[0].state not in {"ambiguous", "invalid"}
                    else None
                )

            for rows in fields.values():
                for setting in rows:
                    if setting.kind != "keycode" or setting.state == "unbound":
                        continue
                    slot = (
                        slot_identity(setting.key)
                        if setting.category == "keymapping"
                        else None
                    )
                    keyboard = (
                        keyboard_identity(setting.key)
                        if setting.category == "keymapping"
                        else None
                    )
                    if keyboard is not None and keyboard[0] == "Target":
                        continue
                    if (
                        slot is None
                        and keyboard is None
                        and setting.key not in shortcuts
                    ):
                        continue
                    group, index = setting.key, ""
                    target: str | None = None
                    enabled: bool | None = None
                    activation: list[str] = []
                    modifiers: list[str] = []
                    related = [setting.line]
                    state = "declared" if setting.state == "declared" else setting.state
                    if slot is not None or keyboard is not None:
                        toggle = unique("ConversionEnabled")
                        if toggle is not None and isinstance(toggle.interpreted, bool):
                            enabled = toggle.interpreted
                            related.append(toggle.line)
                        activation.append(
                            "ConversionEnabled="
                            + (str(int(enabled)) if enabled is not None else "未确定")
                        )
                        mode = unique("ConversionMode")
                        activation.append(
                            "ConversionMode="
                            + (mode.value if mode is not None else "未声明/歧义")
                        )
                        if slot is not None:
                            group, _, index = slot
                            target = f"{group}Slot{index}"
                            for role in ("Slot", "Repeat"):
                                companion = unique(f"{group}{role}{index}")
                                if companion is not None:
                                    related.append(companion.line)
                                    activation.append(f"{role}={companion.value}")
                                else:
                                    activation.append(f"{role}=未声明/歧义")
                        else:
                            assert keyboard is not None
                            group, index = "KeyboardMap", keyboard[1]
                            companion = unique(f"KeyboardMapTarget{index}")
                            if companion is not None and companion.state == "declared":
                                target = companion.value
                                related.append(companion.line)
                            else:
                                state = "incomplete"
                                diagnostics.append(
                                    War3ToolsDiagnostic(
                                        "binding-target-unresolved",
                                        "warning",
                                        file.source.path,
                                        f"{setting.key} 没有唯一非空目标键；保留来源键声明，不补目标。",
                                        setting.line,
                                    )
                                )
                        activation.append("组=" + group)
                    else:
                        toggle_name, modifier_names = shortcuts[setting.key]
                        toggle = (
                            unique(toggle_name) if toggle_name is not None else None
                        )
                        if toggle is not None and isinstance(toggle.interpreted, bool):
                            enabled = toggle.interpreted
                            related.append(toggle.line)
                        activation.append(
                            (toggle_name or "快捷键激活条件")
                            + "="
                            + (str(int(enabled)) if enabled is not None else "未确定")
                        )
                        for modifier_name in modifier_names:
                            modifier = unique(modifier_name)
                            modifiers.append(
                                modifier_name
                                + "="
                                + (modifier.value if modifier else "未声明/歧义")
                            )
                            if modifier is not None:
                                related.append(modifier.line)
                    code = _key_code(setting.value)
                    if code == 0 or not setting.value.strip(" \t"):
                        continue
                    bindings.append(
                        War3ToolsBinding(
                            file.source.path,
                            setting.line,
                            section,
                            occurrence,
                            group,
                            index,
                            setting.value,
                            code,
                            _key_name(code) if code is not None else "未确认键码",
                            target,
                            state,
                            enabled,
                            tuple(activation),
                            False,
                            tuple(modifiers),
                            tuple(related),
                        )
                    )
    return tuple(bindings), tuple(diagnostics)


def _conflicts(bindings: tuple[War3ToolsBinding, ...]) -> tuple[War3ToolsConflict, ...]:
    groups: dict[int, list[int]] = defaultdict(list)
    for index, binding in enumerate(bindings):
        if (
            binding.key_code is not None
            and binding.enabled is not False
            and binding.state not in {"invalid", "ambiguous"}
        ):
            groups[binding.key_code].append(index)
    return tuple(
        War3ToolsConflict(
            code,
            _key_name(code),
            "potential",
            "多个配置声明使用相同键码；激活模式、选中单位情境或修饰键规则尚未证实重叠，仅标为潜在冲突。",
            tuple(indexes),
        )
        for code, indexes in groups.items()
        if len(indexes) > 1
    )


def inspect_war3tools_config(
    path: str | Path, *, text_encoding: str = "auto"
) -> War3ToolsInspection:
    """Read a caller-selected INI or every INI in a caller-selected directory."""
    diagnostics: list[War3ToolsDiagnostic] = []
    files: list[War3ToolsFile] = []
    inventory: tuple[War3ToolsInventoryEntry, ...] = ()
    root_identity: tuple[int, ...] = ()
    selection_kind, requested = "unknown", "auto"
    absolute = os.fspath(path)
    inventory_complete, input_error = True, False
    try:
        requested = normalize_save_text_encoding(text_encoding)
        if not absolute:
            raise ValueError(
                "必须明确选择一个 INI 文件或目录；空路径不自动扫描当前目录"
            )
        validate_output_root(absolute)
        absolute = os.path.abspath(absolute)
        target = Path(absolute)
        info = os.lstat(native_output_path(absolute))
        if _unsafe(info):
            raise ValueError("选中来源是链接或重解析点；请明确选择实际普通文件/目录")
        if stat.S_ISDIR(info.st_mode):
            selection_kind = "directory"
            inventory, inventory_notes, root_identity, inventory_complete = _inventory(
                target
            )
            diagnostics.extend(inventory_notes)
            paths = [
                (Path(entry.path), entry.relative_path)
                for entry in inventory
                if entry.kind == "file" and entry.suffix == ".ini"
            ]
            if not paths:
                diagnostics.append(
                    War3ToolsDiagnostic(
                        "no-ini-files",
                        "error",
                        absolute,
                        "所选目录没有确认的 INI 文件；请明确选择 War3Tools 配置目录或单个 INI。",
                    )
                )
                input_error = True
        elif stat.S_ISREG(info.st_mode) and target.suffix.lower() == ".ini":
            selection_kind = "file"
            root_identity = _identity(info)
            inventory = (
                War3ToolsInventoryEntry(
                    absolute, target.name, "file", ".ini", info.st_size, root_identity
                ),
            )
            paths = [(target, target.name)]
        else:
            raise ValueError("请选择单个 .ini 普通文件或配置目录")
        for selected, relative in paths:
            source, source_notes = _capture_source(selected, relative, requested)
            records, parse_notes = _parse_records(source)
            settings, settings_notes = _settings(source, records, parse_notes)
            notes = source_notes + parse_notes + settings_notes
            complete = (
                source.raw_text is not None
                and source.stable
                and not any(note.severity == "error" for note in notes)
            )
            files.append(War3ToolsFile(source, records, settings, notes, complete))
            diagnostics.extend(notes)
    except (OSError, ValueError, TypeError) as exc:
        input_error, inventory_complete = True, False
        diagnostics.append(
            War3ToolsDiagnostic("input", "error", str(absolute), str(exc))
        )
    bindings, binding_notes = _bindings(tuple(files))
    diagnostics.extend(binding_notes)
    result = War3ToolsInspection(
        str(absolute),
        selection_kind,
        requested,
        inventory,
        tuple(files),
        bindings,
        _conflicts(bindings),
        tuple(diagnostics),
        inventory_complete,
        bool(files)
        and inventory_complete
        and all(file.complete for file in files)
        and not input_error,
        input_error,
        root_identity,
        bool(files)
        and inventory_complete
        and all(file.source.stable for file in files),
    )
    return revalidate_war3tools_inspection(result)


def revalidate_war3tools_inspection(result: War3ToolsInspection) -> War3ToolsInspection:
    """Replay source bytes and complete inventory without replacing old evidence."""
    diagnostics = list(result.diagnostics)
    additions: list[War3ToolsDiagnostic] = []
    files: list[War3ToolsFile] = []
    inventory_complete = result.inventory_complete
    for file in result.files:
        current, notes = _capture_source(
            Path(file.source.path), file.source.relative_path, result.text_encoding
        )
        same = (
            current.stable
            and current.identity == file.source.identity
            and current.sha256 == file.source.sha256
        )
        if not same:
            note = War3ToolsDiagnostic(
                "source-changed-before-delivery",
                "error",
                file.source.path,
                "交付前完整字节/身份复验失败；源可能改变、缺失或被占用，保留本次已读记录和原始字节，请重新检查。",
            )
            new_notes = tuple(
                note for note in notes if note.code != "source-encoding"
            ) + (note,)
            additions.extend(new_notes)
            files.append(
                replace(
                    file,
                    source=replace(file.source, stable=False, status="changed"),
                    diagnostics=tuple(dict.fromkeys(file.diagnostics + new_notes)),
                    complete=False,
                )
            )
        else:
            files.append(file)
    if result.selection_kind == "directory":
        current_inventory, notes, root_identity, complete = _inventory(
            Path(result.path)
        )
        if (
            not complete
            or current_inventory != result.inventory
            or root_identity != result.root_identity
        ):
            inventory_complete = False
            additions.extend(notes)
            additions.append(
                War3ToolsDiagnostic(
                    "inventory-changed-before-delivery",
                    "error",
                    result.path,
                    "完整目录库存/根身份复验失败，包含 INI 与其他扩展文件的新增、缺失或变化；原库存和已读配置保留，请重新检查。",
                )
            )
    stable = result.stable and not additions
    diagnostics.extend(additions)
    return replace(
        result,
        files=tuple(files),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        inventory_complete=inventory_complete,
        inspection_complete=result.inspection_complete and not additions,
        stable=stable,
    )


def war3tools_result_to_dict(result: War3ToolsInspection) -> dict[str, object]:
    return result.to_dict()


def format_war3tools_inspection(result: War3ToolsInspection) -> str:
    """Render every captured declaration and diagnostic without implicit limits."""
    return result.render()

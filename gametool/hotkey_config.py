"""Independent, read-only inspection of the statically reconstructed contract.

No target module is imported, and no configuration discovery or game interaction
occurs here. Flat syntax nodes preserve duplicate keys and arbitrary extensions.
"""

from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from .hotkey_config_models import (
    CompatibleBinding,
    HotkeyBinding,
    HotkeyDiagnostic,
    HotkeyDiff,
    HotkeyDifference,
    HotkeyInspection,
    HotkeyProfile,
    HotkeySource,
    JsonMember,
    JsonNode,
)
from .windows_output_paths import native_output_path
from .windows_source_reads import WindowsSourceRoot


GROUP_SLOTS = {"ability": 12, "item": 6, "spellbook": 12, "shop": 12}
LEGACY_GROUPS = {"command": "ability", "inventory": "item"}
MODIFIERS = ("CTRL", "ALT", "SHIFT", "WIN")
_BOOL_FIELDS = frozenset(
    (
        "enabled",
        "enforce_hotkeys",
        "pause_in_chat",
        "self_cast_enabled",
        "autocast_toggle_enabled",
        "mouse_lock_enabled",
        "right_repeat_enabled",
        "camera_enabled",
    )
)
_DELAYS = {
    "smartcast_delay_ms": (10, 500),
    "repeat_delay_ms": (25, 2000),
    "right_repeat_delay_ms": (25, 2000),
}
_MODIFIER_FIELDS = frozenset(
    (
        "self_cast_modifier",
        "autocast_modifier",
        "camera_distance_modifier",
        "camera_rotation_modifier",
        "camera_incline_modifier",
    )
)
_KEY_FIELDS = frozenset(
    (
        "suspend_hotkey",
        "mouse_lock_hotkey",
        "camera_rotate_up_key",
        "camera_rotate_down_key",
        "camera_incline_up_key",
        "camera_incline_down_key",
    )
)
PROFILE_FIELDS = (
    _BOOL_FIELDS
    | _MODIFIER_FIELDS
    | _KEY_FIELDS
    | _DELAYS.keys()
    | {"enabled_groups", "bindings"}
)
_BINDING_FIELDS = frozenset(
    (
        "binding_id",
        "source",
        "target",
        "enabled",
        "smartcast",
        "repeat",
        "slot_index",
        "group",
    )
)
_BINDING_DEFAULTS: dict[str, str | bool | None] = {
    "enabled": True,
    "smartcast": False,
    "repeat": False,
    "slot_index": None,
    "group": "command",
}
_MOUSE_KEYS = frozenset(("MOUSE4", "MOUSE5", "MIDDLE"))
_KEY_NAMES = (
    frozenset(
        "BACKSPACE TAB ENTER PAUSE CAPSLOCK ESC SPACE PAGEUP PAGEDOWN END HOME "
        "LEFT UP RIGHT DOWN INSERT DELETE NUM* NUM- NUM. NUM/ SEMICOLON EQUALS "
        "COMMA MINUS PERIOD SLASH BACKTICK LBRACKET BACKSLASH RBRACKET QUOTE".split()
    )
    | frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    | frozenset(f"F{i}" for i in range(1, 25))
    | frozenset(f"NUM{i}" for i in range(10))
)
_ALIASES = {
    "CONTROL": "CTRL",
    "CTL": "CTRL",
    "OPTION": "ALT",
    "WINDOWS": "WIN",
    "META": "WIN",
    "RETURN": "ENTER",
    "ESCAPE": "ESC",
    "PGUP": "PAGEUP",
    "PGDN": "PAGEDOWN",
    "DEL": "DELETE",
    "INS": "INSERT",
    "XBUTTON1": "MOUSE4",
    "XBUTTON2": "MOUSE5",
    **{f"NUMPAD{i}": f"NUM{i}" for i in range(10)},
}
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_STRING_DECODER = json.JSONDecoder()


@dataclass(slots=True)
class _Frame:
    kind: str
    start: int
    members: list[JsonMember]
    elements: list[int]
    state: str
    key: str = ""


def parse_hotkey_json(text: str) -> tuple[tuple[JsonNode, ...], int]:
    """Parse strict JSON with an explicit stack and exact numeric tokens."""
    nodes: list[JsonNode] = []
    stack: list[_Frame] = []
    root: int | None = None
    pos = 0

    def error(message: str) -> ValueError:
        return ValueError(f"JSON 字符偏移 {pos}: {message}")

    def attach(node: JsonNode) -> None:
        nonlocal root
        index = len(nodes)
        nodes.append(node)
        if not stack:
            root = index
        elif stack[-1].kind == "object":
            stack[-1].members.append(JsonMember(stack[-1].key, index))
            stack[-1].state = "comma"
        else:
            stack[-1].elements.append(index)
            stack[-1].state = "comma"

    while True:
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        if not stack and root is not None:
            if pos != len(text):
                raise error("根值后还有内容")
            return tuple(nodes), root
        if pos >= len(text):
            raise error("文件结束前 JSON 值未完成")
        frame = stack[-1] if stack else None
        token = text[pos]
        if frame is not None:
            closing = "}" if frame.kind == "object" else "]"
            if frame.state in {"first", "comma"} and token == closing:
                stack.pop()
                pos += 1
                attach(
                    JsonNode(
                        frame.kind,
                        frame.start,
                        pos,
                        members=tuple(frame.members),
                        elements=tuple(frame.elements),
                    )
                )
                continue
            if frame.state == "comma":
                if token != ",":
                    raise error("需要逗号或容器结束符")
                frame.state = "key" if frame.kind == "object" else "value"
                pos += 1
                continue
            if frame.kind == "object" and frame.state in {"first", "key"}:
                if token != '"':
                    raise error("对象键必须为字符串")
                try:
                    decoded_key, pos = _STRING_DECODER.raw_decode(text, pos)
                    if not isinstance(decoded_key, str):
                        raise error("对象键必须为字符串")
                    frame.key = decoded_key
                except ValueError as exc:
                    raise error(str(exc)) from exc
                frame.state = "colon"
                continue
            if frame.state == "colon":
                if token != ":":
                    raise error("对象键后需要冒号")
                frame.state = "value"
                pos += 1
                continue
        start = pos
        if token in "{[":
            stack.append(
                _Frame("object" if token == "{" else "array", pos, [], [], "first")
            )
            pos += 1
        elif token == '"':
            try:
                value, pos = _STRING_DECODER.raw_decode(text, pos)
                if not isinstance(value, str):
                    raise error("字符串未完成")
            except ValueError as exc:
                raise error(str(exc)) from exc
            attach(JsonNode("string", start, pos, value))
        elif token in "-0123456789":
            matched = _NUMBER.match(text, pos)
            if matched is None:
                raise error("无效数字")
            pos = matched.end()
            attach(JsonNode("number", start, pos, matched.group()))
        else:
            literal = next(
                (s for s in ("true", "false", "null") if text.startswith(s, pos)), None
            )
            if literal is None:
                raise error("无效 JSON 值；NaN/Infinity 不属于 JSON")
            pos += len(literal)
            attach(
                JsonNode(
                    "null" if literal == "null" else "boolean",
                    start,
                    pos,
                    {"true": True, "false": False, "null": None}[literal],
                )
            )


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
    )


def _capture_source(path: str | Path) -> tuple[HotkeySource, list[HotkeyDiagnostic]]:
    absolute = os.path.abspath(os.fspath(path))
    diagnostics: list[HotkeyDiagnostic] = []
    data = b""
    identity: tuple[int, ...] = ()
    stable = False
    try:
        target = Path(absolute)
        source_io = native_output_path(absolute)
        with WindowsSourceRoot.open(target.parent) as held:
            with held.protect(PurePosixPath(target.name)):
                named = os.lstat(source_io)
                if (
                    not stat.S_ISREG(named.st_mode)
                    or getattr(named, "st_file_attributes", 0)
                    & stat.FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise ValueError(
                        "源文件必须为普通文件；请明确选择链接指向的实际文件"
                    )
                with open(source_io, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    data = stream.read()
                    after = os.fstat(stream.fileno())
                    stream.seek(0)
                    repeated = hashlib.file_digest(stream, "sha256").hexdigest()
                    final = os.fstat(stream.fileno())
                identity = _identity(named)
                descriptor_identity = _identity(before)
                # Compare pathname/descriptor clocks within their own domains.
                # Native handles also protect every ancestor and the source leaf.
                stable = (
                    descriptor_identity == _identity(after) == _identity(final)
                    and identity == _identity(os.lstat(source_io))
                    and identity[:4] + identity[5:]
                    == descriptor_identity[:4] + descriptor_identity[5:]
                    and repeated == hashlib.sha256(data).hexdigest()
                )
        if not stable:
            diagnostics.append(
                HotkeyDiagnostic(
                    "source-unstable",
                    "error",
                    "$",
                    "源文件在读取/复验期间变化；保留已读字节，不声称检查完整。",
                )
            )
    except (OSError, ValueError) as exc:
        stable = False
        diagnostics.append(
            HotkeyDiagnostic("source-read", "error", "$", f"无法稳定读取源文件: {exc}")
        )
    text: str | None = None
    try:
        text = data.decode("utf-8")
    except UnicodeError as exc:
        diagnostics.append(
            HotkeyDiagnostic(
                "source-encoding",
                "error",
                "$",
                f"配置不是严格 UTF-8: {exc}；完整字节已保留为 raw_base64。",
            )
        )
    return HotkeySource(
        absolute,
        hashlib.sha256(data).hexdigest() if identity else "",
        len(data),
        stable,
        identity,
        base64.b64encode(data).decode("ascii"),
        text,
        data.startswith(b"\xef\xbb\xbf"),
    ), diagnostics


def revalidate_hotkey_source(source: HotkeySource) -> bool:
    """Re-read the explicit source and compare bytes and file identity."""
    current, diagnostics = _capture_source(source.path)
    return (
        not diagnostics
        and current.stable
        and current.identity == source.identity
        and current.sha256 == source.sha256
    )


def _members(nodes: tuple[JsonNode, ...], node: int, key: str) -> list[int]:
    return [member.node for member in nodes[node].members if member.key == key]


def _unique(nodes: tuple[JsonNode, ...], node: int, key: str) -> int | None:
    matches = _members(nodes, node, key)
    return matches[0] if len(matches) == 1 else None


def _value(nodes: tuple[JsonNode, ...], node: int | None) -> str | bool | None:
    return nodes[node].value if node is not None else None


def _string(nodes: tuple[JsonNode, ...], node: int | None) -> str | None:
    if node is not None and nodes[node].kind == "string":
        value = nodes[node].value
        return value if isinstance(value, str) else None
    return None


def _path(base: str, key: str) -> str:
    return base + "[" + json.dumps(key, ensure_ascii=True) + "]"


def _duplicate_diagnostics(
    nodes: tuple[JsonNode, ...], root: int
) -> list[HotkeyDiagnostic]:
    diagnostics: list[HotkeyDiagnostic] = []
    stack = [(root, "$")]
    while stack:
        node, path = stack.pop()
        value = nodes[node]
        if value.kind == "object":
            groups: dict[str, list[int]] = defaultdict(list)
            for index, member in enumerate(value.members):
                groups[member.key].append(index)
            for key, positions in groups.items():
                if len(positions) > 1:
                    diagnostics.append(
                        HotkeyDiagnostic(
                            "duplicate-json-key",
                            "error",
                            _path(path, key),
                            f"JSON 键重复 {len(positions)} 次；原顺序与每个值均保留，不选择赢家。",
                            tuple(
                                f"{_path(path, key)}#{i + 1}"
                                for i in range(len(positions))
                            ),
                        )
                    )
            occurrences: dict[str, int] = defaultdict(int)
            for member in value.members:
                occurrences[member.key] += 1
                child = _path(path, member.key)
                if len(groups[member.key]) > 1:
                    child += f"#{occurrences[member.key]}"
                stack.append((member.node, child))
        elif value.kind == "array":
            stack.extend(
                (child, f"{path}[{i}]") for i, child in enumerate(value.elements)
            )
    return diagnostics


def canonical_hotkey(value: str, *, allow_mouse: bool = True) -> str:
    """Independent transcription of the evidenced key grammar, without hooks."""
    normalized = re.sub(r"\++", "+", value.strip().upper().replace(" ", "")).strip("+")
    if not normalized:
        raise ValueError("空键或缺少主键")
    if re.search(r"(?:^|\+)NUM\+", value.strip().upper().replace(" ", "")):
        raise ValueError("NUM+ 与原工具加号分隔语法冲突；没有已证实的可用写法")
    modifiers: set[str] = set()
    primary: str | None = None
    for part in normalized.split("+"):
        token = _ALIASES.get(part, part)
        if token in MODIFIERS:
            modifiers.add(token)
        elif primary is not None:
            raise ValueError("包含多个主键")
        else:
            primary = token
    if primary is None:
        raise ValueError("缺少主键")
    if primary not in _KEY_NAMES and primary not in _MOUSE_KEYS:
        raise ValueError(
            f"原静态键表未声明 {primary!r}；标点使用 SEMICOLON/EQUALS 等名称"
        )
    if primary in _MOUSE_KEYS and not allow_mouse:
        raise ValueError("原工具此角色禁止鼠标键（MOUSE4/MOUSE5/MIDDLE）")
    return "+".join([*(m for m in MODIFIERS if m in modifiers), primary])


def _integer_in(nodes: tuple[JsonNode, ...], node: int, lower: int, upper: int) -> bool:
    value = nodes[node].value
    if (
        nodes[node].kind != "number"
        or not isinstance(value, str)
        or _INTEGER.fullmatch(value) is None
    ):
        return False
    # Width follows the declared schema range, never the untrusted number.
    positive = value.lstrip("-")
    return len(positive) <= len(str(upper)) and lower <= int(value) <= upper


def _field_value(
    nodes: tuple[JsonNode, ...], node: int, key: str, default: str | bool | None = None
) -> str | bool | None:
    indexes = _members(nodes, node, key)
    return (
        default
        if not indexes
        else _value(nodes, indexes[0])
        if len(indexes) == 1
        else None
    )


def _check_key(
    value: str,
    path: str,
    diagnostics: list[HotkeyDiagnostic],
    *,
    allow_mouse: bool,
    basis: str = "original_declaration",
) -> str | None:
    try:
        return canonical_hotkey(value, allow_mouse=allow_mouse)
    except ValueError as exc:
        diagnostics.append(
            HotkeyDiagnostic("key-parse", "error", path, str(exc), basis=basis)
        )
        return None


def _profile_types(
    nodes: tuple[JsonNode, ...],
    node: int,
    path: str,
    diagnostics: list[HotkeyDiagnostic],
) -> bool:
    diagnostics_start = len(diagnostics)
    missing = sorted(PROFILE_FIELDS - {m.key for m in nodes[node].members})
    if missing:
        diagnostics.append(
            HotkeyDiagnostic(
                "profile-defaults",
                "info",
                path,
                "未声明字段由原工具取静态默认；原声明仍保持缺失: " + ", ".join(missing),
                basis="static_compatibility",
            )
        )
    for member in nodes[node].members:
        key, child = member.key, nodes[member.node]
        field_path = _path(path, key)
        if key not in PROFILE_FIELDS:
            diagnostics.append(
                HotkeyDiagnostic(
                    "unknown-profile-field",
                    "warning",
                    field_path,
                    "未知扩展完整保留；原工具读取合同会忽略此字段。",
                )
            )
        elif key in _BOOL_FIELDS and child.kind != "boolean":
            diagnostics.append(
                HotkeyDiagnostic(
                    "field-type",
                    "error",
                    field_path,
                    "声明类型应为 bool；未按 Python 真值猜测或改写。",
                )
            )
        elif key in _DELAYS:
            low, high = _DELAYS[key]
            if not _integer_in(nodes, member.node, low, high):
                diagnostics.append(
                    HotkeyDiagnostic(
                        "delay-range",
                        "error",
                        field_path,
                        f"声明注解为整数 {low}..{high} ms；原工具使用 int(value) 后校验，可能接受部分非整数类型。此处不静默强制转换，完整原值已保留。",
                    )
                )
        elif key in _MODIFIER_FIELDS:
            if (
                child.kind != "string"
                or not isinstance(child.value, str)
                or child.value.upper() not in MODIFIERS
            ):
                diagnostics.append(
                    HotkeyDiagnostic(
                        "modifier",
                        "error",
                        field_path,
                        "独立修饰键必须为 CTRL/ALT/SHIFT/WIN（原校验允许大小写差异，不去空格）。",
                    )
                )
        elif key in _KEY_FIELDS:
            text = _string(nodes, member.node)
            if text is None:
                diagnostics.append(
                    HotkeyDiagnostic(
                        "field-type", "error", field_path, "按键声明应为字符串。"
                    )
                )
            else:
                _check_key(text, field_path, diagnostics, allow_mouse=False)
        elif key == "enabled_groups":
            if child.kind != "object":
                diagnostics.append(
                    HotkeyDiagnostic(
                        "field-type",
                        "error",
                        field_path,
                        "enabled_groups 应为对象；原工具会对其他类型退回全部启用，不能将其当作原声明。",
                    )
                )
            else:
                for group in child.members:
                    if group.key not in GROUP_SLOTS:
                        diagnostics.append(
                            HotkeyDiagnostic(
                                "unknown-group",
                                "warning",
                                _path(field_path, group.key),
                                "原工具 enabled_groups 只读取四个规范组名；此扩展被忽略。",
                            )
                        )
                    elif nodes[group.node].kind != "boolean":
                        diagnostics.append(
                            HotkeyDiagnostic(
                                "field-type",
                                "error",
                                _path(field_path, group.key),
                                "启用组声明应为 bool；原工具会按 Python 真值转换，本检查保留原值。",
                            )
                        )
    unique_roles = all(len(_members(nodes, node, key)) <= 1 for key in PROFILE_FIELDS)
    groups = _unique(nodes, node, "enabled_groups")
    if groups is not None and nodes[groups].kind == "object":
        unique_roles = unique_roles and all(
            len(_members(nodes, groups, group)) <= 1 for group in GROUP_SLOTS
        )
    return unique_roles and not any(
        diagnostic.severity == "error"
        or diagnostic.code in {"unknown-profile-field", "unknown-group"}
        for diagnostic in diagnostics[diagnostics_start:]
    )


def _migration(value: str | None) -> str | None:
    if value is None:
        return None
    for old, new in LEGACY_GROUPS.items():
        if value.startswith(old + "_"):
            return new + value[len(old) :]
    return value


def _read_binding(
    nodes: tuple[JsonNode, ...],
    node: int,
    ordinal: int,
    path: str,
    diagnostics: list[HotkeyDiagnostic],
) -> HotkeyBinding:
    values = nodes[node]
    if values.kind != "object":
        diagnostics.append(
            HotkeyDiagnostic(
                "binding-type", "error", path, "绑定记录应为对象；该完整值已保留。"
            )
        )
        return HotkeyBinding(
            ordinal, path, node, None, None, None, None, None, None, None, None
        )
    for required in ("binding_id", "source", "target"):
        if not _members(nodes, node, required):
            diagnostics.append(
                HotkeyDiagnostic(
                    "binding-required",
                    "error",
                    _path(path, required),
                    "原 BindingConfig 构造要求该字段；缺失时原工具不能完成读取。",
                )
            )
    for member in values.members:
        key = member.key
        kind = nodes[member.node].kind
        message = ""
        if key not in _BINDING_FIELDS:
            diagnostics.append(
                HotkeyDiagnostic(
                    "unknown-binding-field",
                    "warning",
                    _path(path, key),
                    "原工具忽略的绑定扩展；完整值保留。",
                )
            )
        elif key in {"enabled", "smartcast", "repeat"} and kind != "boolean":
            message = "应为 bool；未按真值转换。"
        elif key in {"binding_id", "source", "target", "group"} and kind != "string":
            message = "应为字符串；未强制转换。"
        elif (
            key == "slot_index"
            and kind != "null"
            and (
                kind != "number"
                or _INTEGER.fullmatch(str(nodes[member.node].value)) is None
            )
        ):
            message = "slot_index 应为整数或 null；bool 不属于槽序号。"
        if message:
            diagnostics.append(
                HotkeyDiagnostic("field-type", "error", _path(path, key), message)
            )
    binding_id = _string(nodes, _unique(nodes, node, "binding_id"))
    declared_group = _string(nodes, _unique(nodes, node, "group"))
    effective_group = declared_group if _members(nodes, node, "group") else "command"
    compatible_group = (
        LEGACY_GROUPS.get(effective_group, effective_group)
        if effective_group is not None
        else None
    )
    compatible_id = _migration(binding_id)
    if effective_group in LEGACY_GROUPS or binding_id != compatible_id:
        diagnostics.append(
            HotkeyDiagnostic(
                "legacy-role",
                "info",
                path,
                f"静态迁移投影: group {effective_group!r} → {compatible_group!r}, ID {binding_id!r} → {compatible_id!r}；原角色保留。",
                basis="static_compatibility",
            )
        )
    if compatible_group not in GROUP_SLOTS:
        diagnostics.append(
            HotkeyDiagnostic(
                "binding-group",
                "error",
                _path(path, "group"),
                "绑定组不属于 ability/item/spellbook/shop 或已证实的 command/inventory 迁移。",
            )
        )
    slot = _unique(nodes, node, "slot_index")
    if compatible_group in GROUP_SLOTS and (
        slot is None
        or not _integer_in(nodes, slot, 0, GROUP_SLOTS[compatible_group] - 1)
    ):
        diagnostics.append(
            HotkeyDiagnostic(
                "slot-range",
                "error",
                _path(path, "slot_index"),
                f"原类默认 slot_index=None，但最终 validate_profile 要求该组 0..{GROUP_SLOTS[compatible_group] - 1}，会拒绝 null/缺失；不从源数值分配槽。",
            )
        )
    source = _string(nodes, _unique(nodes, node, "source"))
    target = _string(nodes, _unique(nodes, node, "target"))
    canonical_source = (
        _check_key(source, _path(path, "source"), diagnostics, allow_mouse=True)
        if source is not None
        else None
    )
    canonical_target = (
        _check_key(target, _path(path, "target"), diagnostics, allow_mouse=False)
        if target
        else None
    )
    return HotkeyBinding(
        ordinal,
        path,
        node,
        binding_id,
        declared_group,
        compatible_id,
        compatible_group,
        source,
        target,
        canonical_source,
        canonical_target,
    )


def _projection(
    nodes: tuple[JsonNode, ...],
    bindings: tuple[HotkeyBinding, ...],
    path: str,
    diagnostics: list[HotkeyDiagnostic],
    *,
    blocked: bool,
) -> tuple[tuple[CompatibleBinding, ...], bool]:
    if blocked:
        diagnostics.append(
            HotkeyDiagnostic(
                "compatibility-ambiguous",
                "error",
                path,
                "绑定容器或已消费字段存在歧义/类型错误；不推导确定兼容方案。",
                basis="static_compatibility",
            )
        )
        return (), False
    # Compact schema constants independently transcribed from the static contract.
    keys = {
        "ability": "MSHADFGTQWER",
        "item": "123456",
        "spellbook": "QWERASDFZXCV",
        "shop": "QWERASDFZXCV",
    }
    defaults: dict[str, CompatibleBinding] = {}
    for group, source_keys in keys.items():
        for slot, key in enumerate(source_keys):
            name = f"{group}_{slot + 1}"
            defaults[name] = CompatibleBinding(
                name,
                key,
                key,
                True,
                False,
                False,
                slot,
                group,
                None,
                "",
                "default_added",
            )
    origins: dict[str, list[str]] = defaultdict(list)
    for binding in bindings:
        name = binding.compatible_id
        if name not in defaults:
            diagnostics.append(
                HotkeyDiagnostic(
                    "compatibility-dropped-id",
                    "warning",
                    binding.path,
                    f"原工具 normalize_bindings 会丢弃未知 ID {binding.binding_id!r}；原声明仍完整保留。",
                    basis="static_compatibility",
                )
            )
            continue
        assert name is not None
        origins[name].append(binding.path)
        fields = {
            key: _field_value(nodes, binding.node, key, value)
            for key, value in _BINDING_DEFAULTS.items()
        }
        slot_node = _unique(nodes, binding.node, "slot_index")
        slot_count = GROUP_SLOTS.get(binding.compatible_group or "")
        slot = (
            int(str(nodes[slot_node].value))
            if slot_node is not None
            and slot_count is not None
            and _integer_in(nodes, slot_node, 0, slot_count - 1)
            else None
        )
        target = binding.source if binding.target else binding.target
        if binding.target and binding.target != binding.source:
            diagnostics.append(
                HotkeyDiagnostic(
                    "compatibility-target-rewritten",
                    "warning",
                    binding.path,
                    f"原工具会把非空 target {binding.target!r} 重写为 source {binding.source!r}；这里仅展示投影。",
                    basis="static_compatibility",
                )
            )
        literal = (
            str(nodes[slot_node].value)
            if slot_node is not None and nodes[slot_node].kind == "number"
            else None
        )
        defaults[name] = CompatibleBinding(
            name,
            binding.source,
            target,
            fields["enabled"] if isinstance(fields["enabled"], bool) else None,
            fields["smartcast"] if isinstance(fields["smartcast"], bool) else None,
            fields["repeat"] if isinstance(fields["repeat"], bool) else None,
            slot,
            binding.compatible_group,
            binding.ordinal,
            binding.path,
            "declared" if slot is not None else "invalid_declared_slot",
            literal,
        )
    for name, paths in origins.items():
        if len(paths) > 1:
            diagnostics.append(
                HotkeyDiagnostic(
                    "compatibility-last-id-wins",
                    "warning",
                    path,
                    f"静态 normalize_bindings 对迁移后 ID {name!r} 取最后一行；前行只在投影中被覆盖。",
                    tuple(paths),
                    "static_compatibility",
                )
            )
    added = [
        value.binding_id for value in defaults.values() if value.origin_ordinal is None
    ]
    if added:
        diagnostics.append(
            HotkeyDiagnostic(
                "compatibility-default-slots",
                "info",
                path,
                f"原工具补齐 {len(added)} 个默认槽（固定合同共42槽）: "
                + ", ".join(added),
                basis="static_compatibility",
            )
        )
    return tuple(defaults.values()), all(
        value.state != "invalid_declared_slot" for value in defaults.values()
    )


def _group_enabled(
    nodes: tuple[JsonNode, ...], profile_node: int, group: str
) -> bool | None:
    container = _unique(nodes, profile_node, "enabled_groups")
    if container is None:
        return None if _members(nodes, profile_node, "enabled_groups") else True
    if nodes[container].kind != "object":
        return None
    field = _unique(nodes, container, group)
    return (
        (None if _members(nodes, container, group) else True)
        if field is None
        else bool(nodes[field].value)
        if nodes[field].kind == "boolean"
        else None
    )


def _conflicts(
    nodes: tuple[JsonNode, ...],
    profile_node: int,
    bindings: tuple[HotkeyBinding, ...],
    diagnostics: list[HotkeyDiagnostic],
) -> None:
    identities: dict[str, list[str]] = defaultdict(list)
    slots: dict[tuple[str, int], list[str]] = defaultdict(list)
    targets: dict[str, list[str]] = defaultdict(list)
    uncertain_paths: set[str] = set()
    keys: dict[str, dict[tuple[str, tuple[str, ...]], list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for binding in bindings:
        if binding.binding_id is not None:
            identities[binding.binding_id].append(binding.path)
        group = binding.compatible_group
        slot = _unique(nodes, binding.node, "slot_index")
        if (
            group in GROUP_SLOTS
            and slot is not None
            and _integer_in(nodes, slot, 0, GROUP_SLOTS[group] - 1)
        ):
            slots[(group, int(str(nodes[slot].value)))].append(binding.path)
        if binding.target:
            targets[binding.canonical_target or binding.target].append(binding.path)
        enabled = _field_value(nodes, binding.node, "enabled", True)
        group_enabled = (
            _group_enabled(nodes, profile_node, group) if group in GROUP_SLOTS else None
        )
        if (
            enabled is False
            or group not in GROUP_SLOTS
            or group_enabled is False
            or binding.canonical_source is None
        ):
            continue
        if enabled is not True or group_enabled is None:
            uncertain_paths.add(binding.path)
        parts = binding.canonical_source.split("+")
        keys[parts[-1]][(group, tuple(parts[:-1]))].append(binding.path)
    for name, paths in identities.items():
        if len(paths) > 1:
            diagnostics.append(
                HotkeyDiagnostic(
                    "duplicate-binding-id",
                    "error",
                    paths[0],
                    f"绑定身份 {name!r} 重复 {len(paths)} 次；原声明不合并，差异比较不选择赢家。",
                    tuple(paths),
                )
            )
    for (group, slot), paths in slots.items():
        if len(paths) > 1:
            diagnostics.append(
                HotkeyDiagnostic(
                    "duplicate-slot",
                    "warning",
                    paths[0],
                    f"原声明在 {group} 槽 {slot} 有 {len(paths)} 行；所有行保留，槽本身不作为绑定身份。",
                    tuple(paths),
                )
            )
    for target, paths in targets.items():
        if len(paths) > 1:
            diagnostics.append(
                HotkeyDiagnostic(
                    "duplicate-target",
                    "info",
                    paths[0],
                    f"原声明有 {len(paths)} 行使用相同 target {target!r}；原工具不禁止重复目标，且非空目标会在兼容投影中重写为各自行的 source。这里仅列出原目标声明，不判为非法。",
                    tuple(paths),
                )
            )
    _key_conflicts(keys, diagnostics, uncertain_paths=frozenset(uncertain_paths))


def _key_conflicts(
    keys: dict[str, dict[tuple[str, tuple[str, ...]], list[str]]],
    diagnostics: list[HotkeyDiagnostic],
    *,
    basis: str = "original_declaration",
    uncertain_paths: frozenset[str] = frozenset(),
) -> None:
    for primary, signatures in keys.items():
        entries = list(signatures.items())
        for i, ((group, modifiers), paths) in enumerate(entries):
            canonical = "+".join((*modifiers, primary))
            if len(paths) > 1:
                uncertain = any(path in uncertain_paths for path in paths)
                diagnostics.append(
                    HotkeyDiagnostic(
                        "possible-duplicate-source"
                        if uncertain
                        else "duplicate-source",
                        "warning" if uncertain else "error",
                        paths[0],
                        f"组 {group} 内源键 {canonical} 精确重复；启用状态不明，若这些绑定和组启用则发生重复，不能据异常标志推成禁用。"
                        if uncertain
                        else f"启用组 {group} 内源键 {canonical} 精确重复；原工具校验会拒绝此上下文。",
                        tuple(paths),
                        basis,
                    )
                )
            for (other_group, other_modifiers), other_paths in entries[i + 1 :]:
                if group != other_group and "item" not in {group, other_group}:
                    continue  # ability/spellbook/shop are exclusive contexts.
                union = set(modifiers) | set(other_modifiers)
                pressed = "+".join((*(m for m in MODIFIERS if m in union), primary))
                diagnostics.append(
                    HotkeyDiagnostic(
                        "possible-overlap",
                        "warning",
                        paths[0],
                        f"并发可能: {group} / {other_group} 在配置、组和绑定启用，且按住 {pressed} 时均满足修饰键子集匹配；命令组取决于当前界面，更多修饰键优先。",
                        tuple((*paths, *other_paths)),
                        basis,
                    )
                )


def _projection_conflicts(
    nodes: tuple[JsonNode, ...],
    profile_node: int,
    projection: tuple[CompatibleBinding, ...],
    path: str,
    diagnostics: list[HotkeyDiagnostic],
) -> None:
    keys: dict[str, dict[tuple[str, tuple[str, ...]], list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    uncertain_paths: set[str] = set()
    for binding in projection:
        group = binding.group
        if (
            not binding.enabled
            or group not in GROUP_SLOTS
            or _group_enabled(nodes, profile_node, group) is False
            or binding.source is None
        ):
            continue
        try:
            canonical = canonical_hotkey(binding.source)
        except ValueError:
            continue  # The declaration already carries its full parsing diagnostic.
        parts = canonical.split("+")
        origin = binding.origin_path or f"{path}/static_default[{binding.binding_id}]"
        if _group_enabled(nodes, profile_node, group) is None:
            uncertain_paths.add(origin)
        keys[parts[-1]][(group, tuple(parts[:-1]))].append(origin)
    _key_conflicts(
        keys,
        diagnostics,
        basis="static_compatibility",
        uncertain_paths=frozenset(uncertain_paths),
    )
    for field, fallback in (
        ("suspend_hotkey", "Ctrl+F12"),
        ("mouse_lock_hotkey", "Ctrl+F10"),
    ):
        key_node = _unique(nodes, profile_node, field)
        value = (
            _string(nodes, key_node)
            if key_node is not None
            else fallback
            if not _members(nodes, profile_node, field)
            else None
        )
        if value is None:
            continue
        try:
            special = canonical_hotkey(value, allow_mouse=False)
        except ValueError:
            continue
        parts = special.split("+")
        for (_group, modifiers), paths in keys.get(parts[-1], {}).items():
            pressed = set(parts[:-1]) | set(modifiers)
            condition = "+".join((*(m for m in MODIFIERS if m in pressed), parts[-1]))
            diagnostics.append(
                HotkeyDiagnostic(
                    "possible-control-overlap",
                    "warning",
                    _path(path, field),
                    f"全局控制键与启用绑定可能重叠：按住 {condition} 且绑定上下文生效时；原工具未对此组合给出冲突校验。",
                    tuple(paths),
                    "static_compatibility",
                )
            )


def _read_profile(
    nodes: tuple[JsonNode, ...],
    name: str,
    occurrence: int,
    node: int,
    path: str,
    diagnostics: list[HotkeyDiagnostic],
) -> HotkeyProfile:
    if nodes[node].kind != "object":
        diagnostics.append(
            HotkeyDiagnostic(
                "profile-type",
                "error",
                path,
                "方案值应为 ProfileConfig 对象；保留原值并停止兼容推导。",
            )
        )
        return HotkeyProfile(name, occurrence, path, node, (), (), False, False)
    profile_complete = _profile_types(nodes, node, path, diagnostics)
    binding_fields = _members(nodes, node, "bindings")
    bindings: list[HotkeyBinding] = []
    blocked = len(binding_fields) > 1
    for occurrence_index, container in enumerate(binding_fields):
        list_path = _path(path, "bindings") + (
            f"#{occurrence_index + 1}" if len(binding_fields) > 1 else ""
        )
        if nodes[container].kind != "array":
            diagnostics.append(
                HotkeyDiagnostic(
                    "bindings-type",
                    "error",
                    list_path,
                    "bindings 应为数组；原工具会对非数组补默认槽，本检查不把它当作已声明的绑定。",
                )
            )
            blocked = True
            continue
        for index, child in enumerate(nodes[container].elements):
            before = len(diagnostics)
            binding = _read_binding(
                nodes, child, index + 1, f"{list_path}[{index}]", diagnostics
            )
            bindings.append(binding)
            if nodes[child].kind != "object" or any(
                len(_members(nodes, child, key)) > 1 for key in _BINDING_FIELDS
            ):
                blocked = True
            if any(
                d.code in {"binding-required", "field-type"} and d.severity == "error"
                for d in diagnostics[before:]
            ):
                blocked = True
    rows = tuple(bindings)
    # Raw absence depends only on a single complete container and known raw IDs.
    # Slot/key/schema validity and compatibility normalization are independent.
    # Repeated ID values stay in the collection and are handled per identity by
    # diff; a missing or ambiguous ID role can hide any identity, so blocks absence.
    bindings_coverage_complete = (
        len(binding_fields) <= 1
        and all(nodes[container].kind == "array" for container in binding_fields)
        and all(binding.binding_id is not None for binding in rows)
    )
    _conflicts(nodes, node, rows, diagnostics)
    projection, complete = _projection(nodes, rows, path, diagnostics, blocked=blocked)
    if not profile_complete:
        complete = False
        diagnostics.append(
            HotkeyDiagnostic(
                "compatibility-profile-incomplete",
                "error",
                path,
                "ProfileConfig 字段存在类型、角色或未知扩展诊断，不能声明完整兼容方案；已确认绑定投影仍保留，启用状态不明时单列条件性冲突。",
                basis="static_compatibility",
            )
        )
    _projection_conflicts(nodes, node, projection, path, diagnostics)
    # Source mouse keys become forbidden targets in the original normalization.
    for row in projection:
        if row.origin_ordinal is not None and row.target:
            _check_key(
                row.target,
                row.origin_path + "/projected_target",
                diagnostics,
                allow_mouse=False,
                basis="static_compatibility",
            )
    return HotkeyProfile(
        name,
        occurrence,
        path,
        node,
        rows,
        projection,
        complete,
        bindings_coverage_complete,
    )


def inspect_hotkey_config(
    path: str | Path, *, profile: str | None = None
) -> HotkeyInspection:
    """Inspect only this explicit path; retain complete raw input and diagnostics."""
    source, diagnostics = _capture_source(path)
    nodes: tuple[JsonNode, ...] = ()
    root: int | None = None
    profiles: list[HotkeyProfile] = []
    input_error = not source.stable or source.utf8_text is None
    if not input_error and source.utf8_text is not None:
        text = source.utf8_text
        if source.utf8_bom:
            diagnostics.append(
                HotkeyDiagnostic(
                    "json-bom",
                    "error",
                    "$",
                    "原工具以 UTF-8 文本交给 json.loads；文件前导 BOM 会使原读取失败。检查器仅为恢复证据移除一次 BOM，raw 保持原字节。",
                )
            )
            text = text[1:]
        try:
            nodes, root = parse_hotkey_json(text)
        except ValueError as exc:
            diagnostics.append(
                HotkeyDiagnostic(
                    "json-invalid",
                    "error",
                    "$",
                    str(exc) + "；完整原文/字节仍在来源证据中。",
                )
            )
            input_error = True
    if root is not None:
        diagnostics.extend(_duplicate_diagnostics(nodes, root))
        if nodes[root].kind != "object":
            diagnostics.append(
                HotkeyDiagnostic(
                    "format-root",
                    "error",
                    "$",
                    "顶层应为 {language, active_profile, profiles:{name:ProfileConfig}} 对象；请选择配置 JSON。",
                )
            )
            input_error = True
        else:
            for key in ("language", "active_profile"):
                role = _unique(nodes, root, key)
                if role is None and not _members(nodes, root, key):
                    diagnostics.append(
                        HotkeyDiagnostic(
                            "app-default",
                            "info",
                            _path("$", key),
                            "该顶层字段缺失；原工具会使用静态默认/回退，原声明保持缺失。",
                            basis="static_compatibility",
                        )
                    )
                elif role is not None and nodes[role].kind != "string":
                    diagnostics.append(
                        HotkeyDiagnostic(
                            "field-type",
                            "error",
                            _path("$", key),
                            "应为字符串；完整原值保留。",
                        )
                    )
                elif (
                    key == "language"
                    and role is not None
                    and _value(nodes, role) not in {"auto", "zh", "en"}
                ):
                    diagnostics.append(
                        HotkeyDiagnostic(
                            "language",
                            "error",
                            _path("$", key),
                            "静态合同语言为 auto/zh/en。",
                        )
                    )
            for member in nodes[root].members:
                if member.key not in {"language", "active_profile", "profiles"}:
                    diagnostics.append(
                        HotkeyDiagnostic(
                            "unknown-app-field",
                            "warning",
                            _path("$", member.key),
                            "未知顶层扩展完整保留；原工具会忽略该字段。",
                        )
                    )
            containers = _members(nodes, root, "profiles")
            if not containers:
                diagnostics.append(
                    HotkeyDiagnostic(
                        "format-profiles",
                        "error",
                        "$",
                        "缺少 profiles 方案对象，无法确认是该静态配置格式；请检查文件。",
                    )
                )
                input_error = True
            for container_index, container in enumerate(containers):
                base = '$["profiles"]' + (
                    f"#{container_index + 1}" if len(containers) > 1 else ""
                )
                if nodes[container].kind != "object":
                    diagnostics.append(
                        HotkeyDiagnostic(
                            "format-profiles",
                            "error",
                            base,
                            "profiles 应为以方案名为键的对象。",
                        )
                    )
                    input_error = True
                    continue
                counts: dict[str, int] = defaultdict(int)
                total_names: dict[str, int] = defaultdict(int)
                for member in nodes[container].members:
                    total_names[member.key] += 1
                for member in nodes[container].members:
                    counts[member.key] += 1
                    member_path = _path(base, member.key)
                    if total_names[member.key] > 1:
                        member_path += f"#{counts[member.key]}"
                    profiles.append(
                        _read_profile(
                            nodes,
                            member.key,
                            counts[member.key],
                            member.node,
                            member_path,
                            diagnostics,
                        )
                    )
            if not profiles and containers:
                diagnostics.append(
                    HotkeyDiagnostic(
                        "profiles-empty",
                        "warning",
                        '$["profiles"]',
                        "原声明无方案；原工具会生成 Default，未把生成值当作用户声明。",
                        basis="static_compatibility",
                    )
                )
            active = _string(nodes, _unique(nodes, root, "active_profile"))
            if (
                active is not None
                and len([p for p in profiles if p.name == active]) != 1
            ):
                diagnostics.append(
                    HotkeyDiagnostic(
                        "active-profile",
                        "error",
                        '$["active_profile"]',
                        f"活动方案 {active!r} 未对应唯一已声明方案；原工具可能回退，检查器不选择。",
                    )
                )
    total = len(profiles)
    if profile is not None:
        selected = [p for p in profiles if p.name == profile]
        if len(selected) != 1:
            diagnostics.append(
                HotkeyDiagnostic(
                    "profile-selector",
                    "error",
                    '$["profiles"]',
                    f"--profile {profile!r} 匹配 {len(selected)} 个方案声明；请使用唯一名称。",
                )
            )
            input_error = True
        profiles = selected
    if source.stable and not revalidate_hotkey_source(source):
        source = replace(source, stable=False)
        diagnostics.append(
            HotkeyDiagnostic(
                "source-changed-before-delivery",
                "error",
                "$",
                "分析后来源复验失败；请等待写入结束后重新检查。",
            )
        )
        input_error = True
    complete = not input_error and not any(
        d.code
        in {"duplicate-json-key", "profile-type", "binding-type", "binding-required"}
        for d in diagnostics
    )
    return HotkeyInspection(
        source,
        nodes,
        root,
        tuple(profiles),
        total,
        profile,
        tuple(diagnostics),
        complete,
        input_error,
    )


def raw_hotkey_node(result: HotkeyInspection, node: int) -> str:
    """Exact raw JSON token/span, including every extension and repeated key."""
    text = result.source.utf8_text or ""
    if result.source.utf8_bom:
        text = text[1:]
    value = result.nodes[node]
    return text[value.start : value.end]


def _signatures(result: HotkeyInspection) -> tuple[str, ...]:
    signatures: list[str] = []
    for node in result.nodes:
        if node.kind == "object":
            content: object = sorted(
                (member.key, signatures[member.node]) for member in node.members
            )
        elif node.kind == "array":
            content = [signatures[index] for index in node.elements]
        else:
            content = node.value
        signatures.append(
            hashlib.sha256(
                json.dumps(
                    [node.kind, content], ensure_ascii=True, separators=(",", ":")
                ).encode("ascii")
            ).hexdigest()
        )
    return tuple(signatures)


def diff_hotkey_configs(old_path: str | Path, new_path: str | Path) -> HotkeyDiff:
    """Compare unique original profile/binding identities and full field values."""
    old, new = inspect_hotkey_config(old_path), inspect_hotkey_config(new_path)
    diagnostics: list[HotkeyDiagnostic] = []
    differences: list[HotkeyDifference] = []
    complete = old.inspection_complete and new.inspection_complete
    old_signatures, new_signatures = _signatures(old), _signatures(new)

    def change(path: str, before: int | None, after: int | None) -> None:
        if (
            before is not None
            and after is not None
            and old_signatures[before] == new_signatures[after]
        ):
            return
        differences.append(
            HotkeyDifference(
                path,
                "added"
                if before is None
                else "removed"
                if after is None
                else "changed",
                raw_hotkey_node(old, before) if before is not None else None,
                raw_hotkey_node(new, after) if after is not None else None,
                before,
                after,
            )
        )

    def compare_fields(
        before: int, after: int, path: str, exclude: frozenset[str] = frozenset()
    ) -> None:
        nonlocal complete
        old_fields: dict[str, list[int]] = defaultdict(list)
        new_fields: dict[str, list[int]] = defaultdict(list)
        for member in old.nodes[before].members:
            if member.key not in exclude:
                old_fields[member.key].append(member.node)
        for member in new.nodes[after].members:
            if member.key not in exclude:
                new_fields[member.key].append(member.node)
        for key in sorted(old_fields.keys() | new_fields.keys()):
            left, right = old_fields[key], new_fields[key]
            if len(left) > 1 or len(right) > 1:
                complete = False
                diagnostics.append(
                    HotkeyDiagnostic(
                        "diff-ambiguous-field",
                        "error",
                        _path(path, key),
                        f"旧/新字段出现 {len(left)}/{len(right)} 次；保留全部声明，不选择赢家。",
                    )
                )
            else:
                change(
                    _path(path, key),
                    left[0] if left else None,
                    right[0] if right else None,
                )

    if (
        old.root is not None
        and new.root is not None
        and old.nodes[old.root].kind == new.nodes[new.root].kind == "object"
    ):
        compare_fields(old.root, new.root, "$", frozenset({"profiles"}))
    old_profiles: dict[str, list[HotkeyProfile]] = defaultdict(list)
    new_profiles: dict[str, list[HotkeyProfile]] = defaultdict(list)
    for result, grouped in ((old, old_profiles), (new, new_profiles)):
        for row in result.profiles:
            grouped[row.name].append(row)
    for name in sorted(old_profiles.keys() | new_profiles.keys()):
        left, right = old_profiles[name], new_profiles[name]
        path = _path('$["profiles"]', name)
        if len(left) > 1 or len(right) > 1:
            complete = False
            diagnostics.append(
                HotkeyDiagnostic(
                    "diff-ambiguous-profile",
                    "error",
                    path,
                    f"旧/新方案身份出现 {len(left)}/{len(right)} 次；所有原值保留，不比较该歧义身份。",
                )
            )
            continue
        if not left or not right:
            opposite = old if not left else new
            if not opposite.inspection_complete:
                complete = False
                diagnostics.append(
                    HotkeyDiagnostic(
                        "diff-incomplete-absence",
                        "error",
                        path,
                        "对侧输入不完整，不能把未确认方案称为新增/删除。",
                    )
                )
            else:
                change(
                    path,
                    left[0].node if left else None,
                    right[0].node if right else None,
                )
            continue
        previous, current = left[0], right[0]
        if (
            old.nodes[previous.node].kind != "object"
            or new.nodes[current.node].kind != "object"
        ):
            complete = False
            continue
        compare_fields(previous.node, current.node, path, frozenset({"bindings"}))
        old_containers = _members(old.nodes, previous.node, "bindings")
        new_containers = _members(new.nodes, current.node, "bindings")
        if (
            len(old_containers) <= 1
            and len(new_containers) <= 1
            and bool(old_containers) != bool(new_containers)
        ):
            change(
                _path(path, "bindings_declaration"),
                old_containers[0] if old_containers else None,
                new_containers[0] if new_containers else None,
            )
        old_bindings: dict[str, list[HotkeyBinding]] = defaultdict(list)
        new_bindings: dict[str, list[HotkeyBinding]] = defaultdict(list)
        for profile_row, grouped in ((previous, old_bindings), (current, new_bindings)):
            for binding in profile_row.bindings:
                if binding.binding_id is None:
                    complete = False
                    diagnostics.append(
                        HotkeyDiagnostic(
                            "diff-missing-binding-identity",
                            "error",
                            binding.path,
                            "绑定没有唯一字符串 binding_id；完整原声明可查看，不能按位置猜测。",
                        )
                    )
                else:
                    grouped[binding.binding_id].append(binding)
        for binding_id in sorted(old_bindings.keys() | new_bindings.keys()):
            before_rows, after_rows = old_bindings[binding_id], new_bindings[binding_id]
            binding_path = _path(_path(path, "bindings_by_id"), binding_id)
            if len(before_rows) > 1 or len(after_rows) > 1:
                complete = False
                diagnostics.append(
                    HotkeyDiagnostic(
                        "diff-ambiguous-binding",
                        "error",
                        binding_path,
                        f"旧/新绑定身份出现 {len(before_rows)}/{len(after_rows)} 次；不选择前行或后行。",
                        tuple(row.path for row in (*before_rows, *after_rows)),
                    )
                )
            elif before_rows and after_rows:
                compare_fields(before_rows[0].node, after_rows[0].node, binding_path)
            elif (
                not before_rows
                and previous.bindings_coverage_complete
                and old.source.stable
                and not old.input_error
            ):
                change(binding_path, None, after_rows[0].node)
            elif (
                not after_rows
                and current.bindings_coverage_complete
                and new.source.stable
                and not new.input_error
            ):
                change(binding_path, before_rows[0].node, None)
            else:
                complete = False
                diagnostics.append(
                    HotkeyDiagnostic(
                        "diff-incomplete-binding-absence",
                        "error",
                        binding_path,
                        "对侧绑定容器不完整，不能称为新增/删除。",
                    )
                )
        # A missing/invalid binding container is evidence even when no ID exists.
        for result, row in ((old, previous), (new, current)):
            containers = _members(result.nodes, row.node, "bindings")
            if len(containers) > 1 or any(
                result.nodes[index].kind != "array" for index in containers
            ):
                complete = False
                diagnostics.append(
                    HotkeyDiagnostic(
                        "diff-invalid-bindings",
                        "error",
                        row.path,
                        "绑定容器歧义或类型错误；保留完整容器证据。",
                    )
                )
    for label, result in (("old", old), ("new", new)):
        if not result.source.stable or not revalidate_hotkey_source(result.source):
            complete = False
            diagnostics.append(
                HotkeyDiagnostic(
                    "diff-source-changed",
                    "error",
                    label,
                    "完整比较交付前来源复验失败，请重新比较。",
                )
            )
    return HotkeyDiff(
        old, new, tuple(differences), tuple(diagnostics), complete, bool(differences)
    )

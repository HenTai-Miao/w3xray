"""Explicit observed INI vocabulary; unknown keys never inherit guessed roles.

Names describe configuration declarations only. Numeric modes, modifier masks,
packed profile data and signal coordinates have no reconstructed execution
contract and are deliberately not decoded into runtime behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re


@dataclass(frozen=True, slots=True)
class FieldSpec:
    category: str
    kind: str
    label: str


_SCHEMA: dict[str, dict[str, FieldSpec]] = {}


def _declare(category: str, kind: str, names: str) -> None:
    fields = _SCHEMA.setdefault(category, {})
    for name in names.split():
        fields[name] = FieldSpec(category, kind, name)


_declare(
    "camera",
    "switch",
    "DistanceEnabled DistanceParameterEnabled TiltEnabled RotationEnabled "
    "FarZEnabled FogZEnabled MapReadbackEnabled",
)
_declare("camera", "number", "Distance DistanceStep Tilt Rotation FarZ FogZ")
_declare("camera", "integer", "CameraMapProfileCount")
_declare("camera", "utf8_hex", "MapNameHex")
_declare(
    "cooldown",
    "switch",
    "Enabled SendCooldownInfo SendMoreWar3Info SendMoreWar3InfoFullTooltip "
    "SendGroundItemInfo SendGroundItemSignal ShowAlliedAbilities ShowAllUnitAbilities",
)
_declare(
    "cooldown",
    "integer",
    "SendCooldownModifier SendCooldownKey SendCooldownTarget HeroNameMode "
    "MaximumDisplayedSeconds FontSize OutlineSize",
)
_declare("cooldown", "color_hex", "FontColor OutlineColor")
_declare(
    "features",
    "switch",
    "ExtendedChatInput UnicodeClipboardPaste War3MemoryDisplay DeathDamageSummary "
    "AlliedMinimapRouteDisplay SkillCastApproachRouteDisplay MinimapRouteEndpointCircle "
    "MinimapHeroPortraitDisplay MinimapNonPlayerUnitPortraits PigGifPlayer "
    "ForceExitWatchdog CrashDumpEnabled ImportantBuffSoundEnabled ShowKkSensitiveWords "
    "DetailedCombatDisplay HealthManaRegenerationDisplay AdaptiveHealthValueColor "
    "OverheadResourceDisplay AdjustResourceTradeAmount War3MemoryFreeDrag "
    "War3MemoryPositionConfigured War3FpsDisplay War3FpsFreeDrag War3FpsPositionConfigured "
    "AttackTargetLine AttackTargetLineSelectedTargetOnly AttackRangeEnabled "
    "AttackRangeCustomRangeEnabled CameraUnitLockEnabled ImportantBuffReminder "
    "ImportantBuffPositionAdjust ImportantBuffPositionConfigured "
    "MinimapHeroPortraitPlayerColorBorder HideKkPlatformLogo FontAtlasRepair "
    "GroundItemDetailedTooltip InventoryDropEnabled DamageFloatingEnabled "
    "DamageFloatingShowSmallDamage DamageFloatingShowOverkillDamage "
    "InventoryDropSellAtShop MouseLeftRepeatEnabled MouseRightRepeatEnabled "
    "OverheadResourceHideNativeUnitTooltip OverheadResourceHideInformationPanel "
    "OverheadResourceShowNonHeroUnits OverheadResourceShowPlayerName "
    "OverheadResourceShowHeroName OverheadResourceShowNonHeroName "
    "OverheadResourceShowHeroLevel OverheadResourceRoundedPanels "
    "OverheadResourceHeroLevelSideAlwaysVisible OverheadResourceHeroLevelHideSimulated "
    "OverheadResourceHeroLevelHideNonPlayerUnits OverheadResourceShowLife "
    "OverheadResourceShowMana OverheadResourceShowOwnerPrimaryResource "
    "OverheadResourceShowOwnerSecondaryResource OverheadResourceShowAllUnitResources",
)
_declare(
    "features",
    "integer",
    "MinimapHeroPortraitSize MinimapHeroPortraitShape MinimapHeroPortraitBorderSize "
    "PigGifPlayerCount ImportantBuffSoundSelection HealthManaRegenerationDecimalPlaces "
    "HealthManaRegenerationDigits HealthManaRegenerationDisplayMode "
    "HealthManaValueDisplayMode TradeGoldAmount TradeLumberAmount War3MemoryFontSize "
    "War3FpsFontSize AttackRangeGroupCount AttackRangeSelectedGroup AttackRangeNextGroupId "
    "CameraUnitLockShortcutModifiers ImportantBuffFontSize ImportantBuffCount "
    "HealthManaRegenerationTextScalePercent DamageFloatingUnits DamageFloatingNumberMode "
    "DamageFloatingFontSize DamageFloatingDurationMs DamageFloatingSpeed DamageFloatingAngle "
    "InventoryDropSlotMask InventoryDropShortcutModifierMask MouseRepeatIntervalMs "
    "OverheadResourceTextScalePercent OverheadResourceDisplayMode "
    "OverheadResourceHeroLevelDisplayMode OverheadResourceHeroLevelFontSize "
    "OverheadResourceRoundedPanelRadius OverheadResourceHealthManaValueDisplayMode",
)
_declare(
    "features",
    "number",
    "ImportantBuffSoundVolume War3MemoryPositionX War3MemoryPositionY War3FpsPositionX "
    "War3FpsPositionY AttackRangeCustomRange ImportantBuffPositionX ImportantBuffPositionY",
)
_declare(
    "features",
    "color_hex",
    "War3MemoryFontColor War3FpsFontColor AttackTargetLineColor AttackRangeColor "
    "ImportantBuffFontColor DamageFloatingPhysicalColor DamageFloatingMagicalColor",
)
_declare("features", "keycode", "CameraUnitLockShortcutKey InventoryDropShortcutKey")
_declare(
    "keymapping",
    "switch",
    "ConversionEnabled CombinedEffectEnabled SuppressPreviousRightClickRestore",
)
_declare(
    "keymapping",
    "integer",
    "ConversionMode RepeatMode RepeatIntervalMs SmartCastMode ProfileCount SelectedProfile",
)
_declare("keymapping", "utf8_hex", "NameHex")
_declare("keymapping", "opaque_hex", "DataHex")
_declare("minimap", "integer", "MinimapSignalProfileCount MinimapSignalSelectedProfile")
_declare("minimap", "switch", "MinimapQuestionMarkSignal")
_declare("minimap", "keycode", "MinimapQuestionMarkSignalKey")
_declare(
    "settings",
    "switch",
    "MenuShortcutEnabled WelcomeEnabled VersionUpdateNoticeEnabled GameEntryPigSoundEnabled "
    "ConversionWarningEnabled BorderlessFullscreen MapModuleNavigationCollapsed",
)
_declare(
    "settings",
    "integer",
    "MenuShortcutModifierA MenuShortcutModifierB UiScalePercent "
    "BorderlessFullscreenShortcutModifiers",
)
_declare("settings", "keycode", "MenuShortcutKey BorderlessFullscreenShortcutKey")
_declare("settings", "text", "Language")
_declare(
    "ui",
    "switch",
    "HideBlackBars HideControlPanel HideTimeOfDayIndicator BuffDurationDisplayEnabled "
    "FreeBuffPositionEnabled BuffPositionConfigured HealthBarColorEnabled "
    "ManaBarEnabled ManaBarHeroOnly",
)
_declare(
    "ui",
    "integer",
    "BlackBarDisplayLogic BlackBarMultiboardMode BuffDurationFontSize BuffDurationOutlineSize "
    "HealthBarVisibilityLogic ManaBarVisibilityLogic",
)
_declare(
    "ui",
    "number",
    "BuffPositionOffsetX BuffPositionOffsetY BuffIconScale HealthBarHeight "
    "HealthBarWidth ManaBarHeight",
)
_declare(
    "ui",
    "color_hex",
    "BuffDurationFontColor BuffDurationOutlineColor HealthValueFontColor ManaValueFontColor "
    "HealthBarYourColor HealthBarAllyColor HealthBarEnemyColor HealthBarNeutralAggressiveColor "
    "HealthBarNeutralPassiveColor ManaBarColor",
)
_declare(
    "ground_item_highlight",
    "integer",
    "FormatVersion Count NextId SelectedGroupId Id SelectedProfileId",
)
_declare("ground_item_highlight", "utf8_hex", "NameUtf8")
_declare("ground_item_highlight", "switch", "Enabled")

_LABELS = {
    "ExtendedChatInput": "扩展聊天输入",
    "UnicodeClipboardPaste": "Unicode 剪贴板粘贴",
    "CrashDumpEnabled": "崩溃转储开关",
    "ConversionEnabled": "改键总开关",
    "Distance": "镜头距离声明",
    "DistanceStep": "镜头距离步长声明",
    "Tilt": "镜头倾角声明",
    "Rotation": "镜头旋转声明",
    "FarZ": "镜头远裁剪声明",
    "FogZ": "镜头雾距离声明",
    "SendCooldownInfo": "发送冷却信息开关",
    "SendGroundItemInfo": "发送地面物品信息开关",
    "SendGroundItemSignal": "发送地面物品信号开关",
    "MaximumDisplayedSeconds": "冷却显示秒数上限声明",
    "MenuShortcutKey": "菜单快捷键码",
    "MinimapQuestionMarkSignalKey": "小地图问号信号键码",
    "DataHex": "未解释的方案二进制十六进制数据",
    "NameHex": "UTF-8 十六进制方案名",
    "MapNameHex": "UTF-8 十六进制地图名",
    "NameUtf8": "UTF-8 十六进制名称",
}

_SLOT = re.compile(
    r"(Skill|ShopSkill|UnitSkill|BuildingSkill|SpellbookSkill|Item)(Key|Slot|Repeat)([0-9]+)\Z"
)
_KEYBOARD = re.compile(r"KeyboardMap(Source|Target)([0-9]+)\Z")
_SIGNAL = re.compile(r"MinimapSignalProfile([0-9]+)(NameHex|Points|Preset)\Z")
_PIG = re.compile(
    r"PigGifPlayer(ImageOnly|WindowConfigured|WindowX|WindowY|WindowWidth|WindowHeight)([0-9]+)\Z"
)


def section_category(relative_path: str, section: str) -> str:
    """Bind section vocabulary to its observed filename or extension family."""
    path = PurePosixPath(relative_path.replace("\\", "/"))
    name = path.name.lower()
    pairs = {
        "camera.ini": ("Camera", "camera"),
        "cooldown.ini": ("Cooldown", "cooldown"),
        "features.ini": ("Features", "features"),
        "keymapping.ini": ("Conversion", "keymapping"),
        "minimapsignals.ini": ("MinimapSignals", "minimap"),
        "settings.ini": ("Settings", "settings"),
        "ui.ini": ("UI", "ui"),
    }
    declared = pairs.get(name)
    if declared is not None and section == declared[0]:
        return declared[1]
    if name == "camera.ini" and re.fullmatch(r"CameraMapProfile[0-9]+", section):
        return "camera"
    if name == "keymapping.ini" and re.fullmatch(r"ConversionProfile[0-9]+", section):
        return "keymapping"
    if name == "index.ini" and (
        section == "Catalog" or re.fullmatch(r"Group[0-9]+(?:Profile[0-9]+)?", section)
    ):
        return "ground_item_highlight"
    if re.fullmatch(r"profile-[0-9]+\.ini", name) and section == "Profile":
        return "ground_item_highlight"
    return ""


def field_spec(relative_path: str, section: str, key: str) -> FieldSpec | None:
    category = section_category(relative_path, section)
    if category == "keymapping":
        profile_field = key in {"NameHex", "DataHex"}
        if (section == "Conversion") == profile_field:
            return None
    if category == "camera" and (
        section == "Camera"
        and key == "MapNameHex"
        or section != "Camera"
        and key == "CameraMapProfileCount"
    ):
        return None
    if category == "ground_item_highlight":
        if section == "Catalog":
            permitted = {"FormatVersion", "Count", "NextId", "SelectedGroupId"}
        elif section == "Profile":
            permitted = {"FormatVersion", "NameUtf8", "Enabled", "Count"}
        elif "Profile" in section:
            permitted = {"Id", "NameUtf8"}
        else:
            permitted = {"Id", "NameUtf8", "Count", "SelectedProfileId"}
        if key not in permitted:
            return None
    spec = _SCHEMA.get(category, {}).get(key)
    if spec is not None:
        return FieldSpec(category, spec.kind, _LABELS.get(key, spec.label))
    if category == "keymapping" and section == "Conversion":
        slot = _SLOT.fullmatch(key)
        if slot is not None:
            role = slot.group(2)
            return FieldSpec(category, "keycode" if role == "Key" else "integer", key)
        if _KEYBOARD.fullmatch(key):
            return FieldSpec(category, "keycode", key)
    if category == "minimap":
        signal = _SIGNAL.fullmatch(key)
        if signal is not None:
            kind = {"NameHex": "utf8_hex", "Points": "opaque_hex", "Preset": "integer"}[
                signal.group(2)
            ]
            return FieldSpec(category, kind, key)
    if category == "features":
        pig = _PIG.fullmatch(key)
        if pig is not None:
            kind = (
                "switch"
                if pig.group(1) in {"ImageOnly", "WindowConfigured"}
                else "integer"
            )
            return FieldSpec(category, kind, key)
    return None


def slot_identity(key: str) -> tuple[str, str, str] | None:
    match = _SLOT.fullmatch(key)
    return (match.group(1), match.group(2), match.group(3)) if match else None


def keyboard_identity(key: str) -> tuple[str, str] | None:
    match = _KEYBOARD.fullmatch(key)
    return (match.group(1), match.group(2)) if match else None

"""Save/object API catalog for static script investigation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ApiInfo:
    mechanism: str
    operation: str


_EXPLICIT_SAVE_APIS: Final = {
    "InitGameCache": ApiInfo("GameCache", "打开缓存"),
    "SaveGameCache": ApiInfo("GameCache", "保存缓存"),
    "StoreInteger": ApiInfo("GameCache", "写整数"),
    "StoreReal": ApiInfo("GameCache", "写实数"),
    "StoreBoolean": ApiInfo("GameCache", "写布尔"),
    "StoreString": ApiInfo("GameCache", "写字符串"),
    "StoreUnit": ApiInfo("GameCache", "写单位"),
    "GetStoredInteger": ApiInfo("GameCache", "读整数"),
    "GetStoredReal": ApiInfo("GameCache", "读实数"),
    "GetStoredBoolean": ApiInfo("GameCache", "读布尔"),
    "GetStoredString": ApiInfo("GameCache", "读字符串"),
    "GetStoredUnit": ApiInfo("GameCache", "读单位"),
    "FlushGameCache": ApiInfo("GameCache", "清空缓存"),
    "FlushStoredMission": ApiInfo("GameCache", "清空区段"),
    "SaveInteger": ApiInfo("Hashtable", "写整数"),
    "SaveReal": ApiInfo("Hashtable", "写实数"),
    "SaveBoolean": ApiInfo("Hashtable", "写布尔"),
    "SaveStr": ApiInfo("Hashtable", "写字符串"),
    "LoadInteger": ApiInfo("Hashtable", "读整数"),
    "LoadReal": ApiInfo("Hashtable", "读实数"),
    "LoadBoolean": ApiInfo("Hashtable", "读布尔"),
    "LoadStr": ApiInfo("Hashtable", "读字符串"),
    "HaveSavedInteger": ApiInfo("Hashtable", "检查整数"),
    "RemoveSavedInteger": ApiInfo("Hashtable", "删除整数"),
    "FlushChildHashtable": ApiInfo("Hashtable", "清空子表"),
    "FlushParentHashtable": ApiInfo("Hashtable", "清空哈希表"),
    "PreloadGenStart": ApiInfo("Preload", "开始生成"),
    "PreloadGenEnd": ApiInfo("Preload", "结束生成"),
    "PreloadGenClear": ApiInfo("Preload", "清空生成"),
    "Preload": ApiInfo("Preload", "写入预载"),
    "BlzSendSyncData": ApiInfo("Sync", "同步数据"),
    "BlzTriggerRegisterPlayerSyncEvent": ApiInfo("Sync", "注册同步"),
    "SyncStoredInteger": ApiInfo("Sync", "同步缓存整数"),
    "SyncStoredReal": ApiInfo("Sync", "同步缓存实数"),
    "SyncStoredBoolean": ApiInfo("Sync", "同步缓存布尔"),
    "SyncStoredString": ApiInfo("Sync", "同步缓存字符串"),
    "GetPlayerName": ApiInfo("PlayerKey", "读取玩家名"),
    "GetHandleId": ApiInfo("HandleKey", "读取句柄ID"),
    "StringHash": ApiInfo("HashKey", "字符串哈希"),
    "DzAPI_Map_SaveServerValue": ApiInfo("PlatformSave", "写服务器值"),
    "DzAPI_Map_GetServerValue": ApiInfo("PlatformSave", "读服务器值"),
    "DzAPI_Map_StoreInteger": ApiInfo("PlatformSave", "写整数"),
    "DzAPI_Map_GetStoredInteger": ApiInfo("PlatformSave", "读整数"),
    "DzAPI_Map_SavePublicArchive": ApiInfo("PlatformSave", "写公共档案"),
    "DzAPI_Map_GetPublicArchive": ApiInfo("PlatformSave", "读公共档案"),
    "KKAPI_SaveServerValue": ApiInfo("PlatformSave", "写服务器值"),
    "KKAPI_GetServerValue": ApiInfo("PlatformSave", "读服务器值"),
}
_OBJECT_APIS: Final = {
    "CreateUnit": "单位",
    "CreateUnitAtLoc": "单位",
    "BlzCreateUnitWithSkin": "单位",
    "UnitAddAbility": "技能",
    "UnitRemoveAbility": "技能",
    "CreateItem": "物品",
    "CreateItemLoc": "物品",
    "UnitAddItemById": "物品",
    "CreateDestructable": "可破坏物",
    "CreateDestructableZ": "可破坏物",
}
_PREFIX_OPERATIONS: Final = (
    ("HaveSaved", "检查"),
    ("RemoveSaved", "删除"),
    ("Save", "写"),
    ("Load", "读"),
)
_PRIMITIVE_SUFFIXES: Final = {"Integer", "Real", "Boolean", "Str"}


def save_api_info(name: str) -> ApiInfo | None:
    """Return static save API classification for a native/function name."""
    explicit = _EXPLICIT_SAVE_APIS.get(name)
    if explicit is not None:
        return explicit
    generic = _generic_hashtable_info(name)
    if generic is not None:
        return generic
    return None


def object_api_category(name: str) -> str | None:
    """Return object-ID category for known object-creating native calls."""
    return _OBJECT_APIS.get(name)


def is_hashtable_key_api(name: str) -> bool:
    """Return whether a save API uses hashtable parent/child key arguments."""
    info = save_api_info(name)
    return info is not None and info.mechanism == "Hashtable" and not name.startswith("Flush")


def _generic_hashtable_info(name: str) -> ApiInfo | None:
    for prefix, verb in _PREFIX_OPERATIONS:
        if not name.startswith(prefix):
            continue
        suffix = name[len(prefix):]
        if not _is_hashtable_suffix(suffix):
            continue
        label = "句柄" if suffix.endswith("Handle") else _suffix_label(suffix)
        return ApiInfo("Hashtable", f"{verb}{label}")
    return None


def _is_hashtable_suffix(suffix: str) -> bool:
    return suffix in _PRIMITIVE_SUFFIXES or suffix == "Handle" or suffix.endswith("Handle")


def _suffix_label(suffix: str) -> str:
    labels = {
        "Integer": "整数",
        "Real": "实数",
        "Boolean": "布尔",
        "Str": "字符串",
    }
    return labels.get(suffix, suffix)

"""Pure metadata-declared field roles shared by objects and pack queries."""

from collections.abc import Mapping
from typing import Final

from .object_layers import split_field_column


TECH_SCALAR_LABELS: Final[Mapping[str, str]] = {
    "glvl": "最大等级",
    "gglb": "基础金",
    "gglm": "金增量",
    "glmb": "基础木",
    "glmm": "木增量",
}
# UpgradeMetaData.slk ID -> field, from the project's pinned war3-objectdata
# snapshot dc5e2da21217dba8e5f750c1e867d691ab193ec1 (rows 12..16).
_TECH_SCALAR_KEYS: Final[Mapping[str, str]] = {
    "maxlevel": "glvl",
    "goldbase": "gglb",
    "goldmod": "gglm",
    "lumberbase": "glmb",
    "lumbermod": "glmm",
    **{key: key for key in TECH_SCALAR_LABELS},
}
_BASE_TECH_SCALAR_KEYS: Final[Mapping[str, str]] = {
    label: key for key, label in TECH_SCALAR_LABELS.items()
}


def tech_scalar_key(key: str, *, base_label: str = "") -> str | None:
    """Return the exact declared scalar code; base labels require caller proof."""
    return _TECH_SCALAR_KEYS.get(
        split_field_column(key)[0].casefold().removeprefix("binary:")
    ) or _BASE_TECH_SCALAR_KEYS.get(base_label)

"""Validated retained-generation names for one publication transaction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .description_cache_publication_errors import DescriptionCachePublicationError
from .description_cache_publication_models import RetainedCacheRole


_RETAINED_PREFIX: Final = ".w3xray-description-cache-retained-"
_HEX: Final = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class RetainedCacheNames:
    """Exact retained sibling names for one transaction identifier."""

    parent: Path
    transaction_id: str

    def __post_init__(self) -> None:
        if len(self.transaction_id) != 32 or any(
            character not in _HEX for character in self.transaction_id
        ):
            raise DescriptionCachePublicationError(
                "transaction identifier must be 32 lowercase hex digits"
            )

    def path(self, role: RetainedCacheRole) -> Path:
        return self.parent / f"{_RETAINED_PREFIX}{self.transaction_id}-{role.value}"


__all__ = ("RetainedCacheNames",)

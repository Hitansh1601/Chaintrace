"""Adapter contract: a data source turns something into a validated ImportResult."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..importer import ImportResult


class TransactionSource(ABC):
    """All adapters are read-only by contract: they may fetch, never write or sign."""

    name: str = "source"
    read_only: bool = True

    @abstractmethod
    def load(self) -> ImportResult:
        """Return validated transfers (plus rejected rows) from this source."""

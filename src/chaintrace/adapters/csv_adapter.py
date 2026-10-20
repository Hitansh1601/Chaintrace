"""Default adapter: local CSV files and the bundled synthetic dataset."""
from __future__ import annotations

from ..importer import ImportResult, load_transactions
from ..schema import ValidationConfig
from .base import TransactionSource


class CsvAdapter(TransactionSource):
    name = "csv"

    def __init__(self, source, config: ValidationConfig | None = None, source_name: str | None = None):
        self._source = source
        self._config = config
        self._source_name = source_name

    def load(self) -> ImportResult:
        return load_transactions(self._source, self._config, self._source_name)

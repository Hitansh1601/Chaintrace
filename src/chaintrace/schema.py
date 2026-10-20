"""Canonical schema, constants, errors and shared helpers for ChainTrace."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

SCHEMA_VERSION = "1.0"

# Columns an input CSV must provide. ``transfer_index`` is optional (defaults to 0).
REQUIRED_COLUMNS: tuple[str, ...] = (
    "tx_hash",
    "block_number",
    "timestamp",
    "from_address",
    "to_address",
    "asset",
    "amount",
    "data_source",
)

# Columns of a validated, normalised transfer table.
CANONICAL_COLUMNS: tuple[str, ...] = (
    "evidence_ref",
    "tx_hash",
    "transfer_index",
    "block_number",
    "timestamp",
    "from_address",
    "to_address",
    "asset",
    "amount",
    "amount_raw",
    "data_source",
)

# Deterministic chronological order used everywhere.
SORT_KEYS: list[str] = ["timestamp", "block_number", "tx_hash", "transfer_index"]


class StatementKind(str, Enum):
    """The three evidence classes that reports keep strictly separate."""

    FACT = "observed_fact"
    INDICATOR = "derived_indicator"
    HYPOTHESIS = "investigator_hypothesis"


DISCLAIMERS: tuple[str, ...] = (
    "ChainTrace is read-only: it analyses transaction data supplied to it and never "
    "creates transactions or handles private keys.",
    "Observed facts describe only the loaded dataset, which may be incomplete.",
    "Derived indicators are heuristic leads for further investigation, not findings "
    "of wrongdoing.",
    "Graph proximity is not proof of identity, criminality, or common ownership. "
    "No address in this report is attributed to a named person.",
    "Investigator hypotheses are the analyst's own and remain unverified unless "
    "independently corroborated.",
)


@dataclass(frozen=True)
class ValidationConfig:
    """Patterns used to validate identifiers. Defaults are EVM-style."""

    address_regex: str = r"^0x[0-9a-fA-F]{40}$"
    tx_hash_regex: str = r"^0x[0-9a-fA-F]{64}$"


class SchemaError(ValueError):
    """Input cannot be interpreted as a transaction table at all."""


class EvidenceReferenceError(ValueError):
    """A finding or note cites an evidence reference absent from the dataset."""

    def __init__(self, unresolved):
        self.unresolved = sorted(set(unresolved))
        preview = ", ".join(self.unresolved[:5])
        more = "" if len(self.unresolved) <= 5 else f" (+{len(self.unresolved) - 5} more)"
        super().__init__(f"unresolved evidence reference(s): {preview}{more}")


class StaleAnalysisError(RuntimeError):
    """The stored analysis run no longer matches the case's transaction data."""


def normalize_address(address: str) -> str:
    return str(address).strip().lower()

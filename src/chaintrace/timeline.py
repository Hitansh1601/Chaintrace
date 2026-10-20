"""Chronological transaction timeline."""
from __future__ import annotations

import pandas as pd

from .findings import Indicator
from .schema import SORT_KEYS, normalize_address

TIMELINE_COLUMNS = [
    "block_number",
    "timestamp",
    "tx_hash",
    "from_address",
    "to_address",
    "amount",
    "asset",
    "data_source",
    "evidence_ref",
]


def build_timeline(
    df: pd.DataFrame,
    address: str | None = None,
    indicators: list[Indicator] | None = None,
) -> pd.DataFrame:
    """Sorted timeline, optionally restricted to one address and tagged with indicator IDs."""
    data = df
    if address:
        addr = normalize_address(address)
        data = data[(data["from_address"] == addr) | (data["to_address"] == addr)]
    data = data.sort_values(SORT_KEYS, kind="mergesort")
    out = data[TIMELINE_COLUMNS].reset_index(drop=True)
    if indicators is not None:
        by_ref: dict[str, list[str]] = {}
        for ind in indicators:
            for ref in ind.evidence_refs:
                by_ref.setdefault(ref, []).append(ind.indicator_id)
        out["indicator_ids"] = out["evidence_ref"].map(lambda r: ";".join(sorted(by_ref.get(r, []))))
    return out

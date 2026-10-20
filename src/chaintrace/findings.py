"""Evidence model: observed facts, derived indicators (investigator hypotheses live in
the case store as notes). Every statement lists the evidence references behind it."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from .schema import StatementKind, normalize_address

H_BURST = "transaction_burst"
H_VALUE = "unusual_value_change"
H_MULTIHOP = "rapid_multihop"
H_REPEAT = "repeated_interaction"
HEURISTIC_NAMES = (H_BURST, H_VALUE, H_MULTIHOP, H_REPEAT)
PRIORITIES = ("high", "medium", "low")  # review priority, NOT a risk or guilt score


def stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10].upper()
    return f"{prefix}-{digest}"


def short_addr(address: str) -> str:
    return f"{address[:6]}…{address[-4:]}" if len(address) > 12 else address


def fmt_amount(value: float) -> str:
    text = f"{value:,.6f}".rstrip("0").rstrip(".")
    return text or "0"


def fmt_totals(totals: dict[str, float]) -> str:
    return ", ".join(f"{fmt_amount(v)} {k}" for k, v in sorted(totals.items())) or "n/a"


def fmt_ts(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S UTC")


@dataclass
class Indicator:
    """A heuristic lead. Not a conclusion: see ``explanation`` and ``caveats``."""

    indicator_id: str
    heuristic: str
    title: str
    priority: str
    explanation: str
    caveats: str
    addresses: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    parameters: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    kind: str = StatementKind.INDICATOR.value

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["addresses"] = list(self.addresses)
        data["evidence_refs"] = list(self.evidence_refs)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Indicator":
        return cls(
            indicator_id=data["indicator_id"],
            heuristic=data["heuristic"],
            title=data["title"],
            priority=data["priority"],
            explanation=data["explanation"],
            caveats=data["caveats"],
            addresses=tuple(data["addresses"]),
            evidence_refs=tuple(data["evidence_refs"]),
            parameters=dict(data.get("parameters", {})),
            metrics=dict(data.get("metrics", {})),
            kind=data.get("kind", StatementKind.INDICATOR.value),
        )


@dataclass
class Fact:
    """An observed fact: computed directly from loaded rows, no inference."""

    fact_id: str
    statement: str
    scope: str  # "dataset" or "address"
    addresses: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    kind: str = StatementKind.FACT.value

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["addresses"] = list(self.addresses)
        data["evidence_refs"] = list(self.evidence_refs)
        return data


def derive_dataset_fact(df: pd.DataFrame) -> Fact:
    if df.empty:
        return Fact(stable_id("FACT", "dataset-empty"), "The loaded dataset contains no transfers.", "dataset", (), ())
    addresses = set(df["from_address"]) | set(df["to_address"])
    statement = (
        f"The loaded dataset contains {len(df)} transfers involving {len(addresses)} addresses "
        f"in asset(s) {', '.join(sorted(df['asset'].unique()))}, from {fmt_ts(df['timestamp'].min())} "
        f"to {fmt_ts(df['timestamp'].max())}. Data source label(s): "
        f"{'; '.join(sorted(df['data_source'].unique()))}. This describes only the loaded data, "
        "not the full on-chain history of any address."
    )
    return Fact(stable_id("FACT", "dataset", len(df), df["evidence_ref"].min()), statement, "dataset", (), ())


def derive_address_fact(df: pd.DataFrame, address: str) -> Fact | None:
    addr = normalize_address(address)
    sent = df[df["from_address"] == addr]
    recv = df[df["to_address"] == addr]
    if sent.empty and recv.empty:
        return None
    both = pd.concat([sent, recv]).drop_duplicates("evidence_ref").sort_values("timestamp")
    counterparties = (set(sent["to_address"]) | set(recv["from_address"])) - {addr}
    sent_tot = {k: float(v) for k, v in sent.groupby("asset")["amount"].sum().items()}
    recv_tot = {k: float(v) for k, v in recv.groupby("asset")["amount"].sum().items()}
    statement = (
        f"In the loaded data, address {addr} appears in {len(both)} transfers "
        f"({len(sent)} as sender, {len(recv)} as recipient) with {len(counterparties)} distinct "
        f"counterparties; first seen {fmt_ts(both['timestamp'].min())}, last seen "
        f"{fmt_ts(both['timestamp'].max())}. Sent totals: {fmt_totals(sent_tot)}. "
        f"Received totals: {fmt_totals(recv_tot)}. This is a statement about the loaded data only."
    )
    return Fact(
        stable_id("FACT", "address", addr, len(both)),
        statement,
        "address",
        (addr,),
        tuple(both["evidence_ref"]),
    )

"""Transparent, rule-based heuristics.

Each detector is a small pure function over the canonical transfer table. Every rule,
threshold and the transfers that triggered it are recorded in the resulting
``Indicator`` so an analyst can re-check the logic by hand. Indicators are leads, not
verdicts: each carries explicit caveats about benign explanations.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, fields

import numpy as np
import pandas as pd

from .findings import (
    H_BURST,
    H_MULTIHOP,
    H_REPEAT,
    H_VALUE,
    PRIORITIES,
    Indicator,
    fmt_amount,
    fmt_totals,
    fmt_ts,
    short_addr,
    stable_id,
)
from .schema import CANONICAL_COLUMNS, SORT_KEYS, normalize_address

_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


@dataclass
class HeuristicConfig:
    # Transaction burst
    burst_min_transfers: int = 8
    burst_window_minutes: float = 10.0
    burst_min_counterparties: int = 4
    # Unusual value change (spike vs the sender's own recent history, per asset)
    spike_factor: float = 10.0
    spike_min_history: int = 5
    spike_lookback: int = 20
    # Rapid multi-hop forwarding
    multihop_min_transfers: int = 4
    multihop_max_delay_minutes: float = 30.0
    multihop_min_retention: float = 0.7
    multihop_max_depth: int = 10
    multihop_max_branching: int = 5
    multihop_max_chains: int = 200
    # Repeated interactions with analyst-selected (watchlist) addresses
    repeat_min_interactions: int = 5

    def validate(self) -> "HeuristicConfig":
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{f.name} must be a number")
            if value <= 0:
                raise ValueError(f"{f.name} must be positive")
            if f.type == "int" and int(value) != value:
                raise ValueError(f"{f.name} must be an integer")
        if self.multihop_min_retention > 1:
            raise ValueError("multihop_min_retention must be in (0, 1]")
        if self.burst_min_counterparties > self.burst_min_transfers:
            raise ValueError("burst_min_counterparties cannot exceed burst_min_transfers")
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "HeuristicConfig":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown heuristic parameter(s): {sorted(unknown)}")
        return cls(**data).validate()


# ----------------------------------------------------------------------------- helpers
def _prep(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in CANONICAL_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"transfer table is missing column(s): {', '.join(missing)}")
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        raise ValueError("timestamp column must be datetime-typed (use the importer)")
    return df.sort_values(SORT_KEYS, kind="mergesort").reset_index(drop=True)


def _secs(series: pd.Series) -> np.ndarray:
    return (series - _EPOCH).dt.total_seconds().to_numpy(dtype=float)


def _dur(seconds: float) -> str:
    seconds = int(round(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    return f"{minutes}m {sec}s" if minutes else f"{sec}s"


def _totals(seg: pd.DataFrame) -> dict[str, float]:
    return {k: float(v) for k, v in seg.groupby("asset")["amount"].sum().sort_index().items()}


# ------------------------------------------------------------------------------ bursts
def detect_bursts(df: pd.DataFrame, cfg: HeuristicConfig | None = None) -> list[Indicator]:
    """Many transfers from (or to) one address inside a short window."""
    cfg = (cfg or HeuristicConfig()).validate()
    df = _prep(df)
    out: list[Indicator] = []
    window = cfg.burst_window_minutes * 60
    for direction, key, other in (
        ("outgoing", "from_address", "to_address"),
        ("incoming", "to_address", "from_address"),
    ):
        for addr, g in df.groupby(key, sort=True):
            if len(g) < cfg.burst_min_transfers:
                continue
            secs = _secs(g["timestamp"])
            n, i = len(g), 0
            while i < n:
                j = i
                while j + 1 < n and secs[j + 1] - secs[i] <= window:
                    j += 1
                if j - i + 1 >= cfg.burst_min_transfers:
                    seg = g.iloc[i : j + 1]
                    if seg[other].nunique() >= cfg.burst_min_counterparties:
                        out.append(_burst_indicator(addr, direction, other, seg, secs[j] - secs[i], cfg))
                        i = j + 1  # non-overlapping windows
                        continue
                i += 1
    return out


def _burst_indicator(addr, direction, other, seg, duration, cfg) -> Indicator:
    cps = sorted(seg[other].unique())
    refs = tuple(seg["evidence_ref"])
    verb, prep = ("sent", "to") if direction == "outgoing" else ("received", "from")
    totals = _totals(seg)
    explanation = (
        f"Address {addr} {verb} {len(seg)} transfers {prep} {len(cps)} distinct counterparties "
        f"within {_dur(duration)} (first {fmt_ts(seg['timestamp'].min())}, last "
        f"{fmt_ts(seg['timestamp'].max())}); combined value {fmt_totals(totals)}. "
        f"Rule: at least {cfg.burst_min_transfers} transfers and {cfg.burst_min_counterparties} "
        f"distinct counterparties inside a {cfg.burst_window_minutes:g}-minute window."
    )
    caveats = (
        "Bursts are common in legitimate activity (payroll or batch payouts, airdrops, exchange "
        "withdrawals, wallet or contract batching). This is a lead to review in context, not "
        "evidence of wrongdoing."
    )
    return Indicator(
        indicator_id=stable_id("IND", H_BURST, direction, addr, *refs),
        heuristic=H_BURST,
        title=f"{direction.capitalize()} burst: {len(seg)} transfers in {_dur(duration)} ({short_addr(addr)})",
        priority="high" if len(seg) >= 2 * cfg.burst_min_transfers else "medium",
        explanation=explanation,
        caveats=caveats,
        addresses=(addr,),
        evidence_refs=refs,
        parameters={
            "burst_min_transfers": cfg.burst_min_transfers,
            "burst_window_minutes": cfg.burst_window_minutes,
            "burst_min_counterparties": cfg.burst_min_counterparties,
        },
        metrics={
            "direction": direction,
            "transfer_count": int(len(seg)),
            "distinct_counterparties": len(cps),
            "counterparties": cps[:50],
            "duration_seconds": float(duration),
            "window_start": seg["timestamp"].min().isoformat(),
            "window_end": seg["timestamp"].max().isoformat(),
            "totals_by_asset": totals,
        },
    )


# ------------------------------------------------------------------------ value changes
def detect_value_anomalies(df: pd.DataFrame, cfg: HeuristicConfig | None = None) -> list[Indicator]:
    """A transfer far larger than the sender's own recent median (same asset)."""
    cfg = (cfg or HeuristicConfig()).validate()
    df = _prep(df)
    out: list[Indicator] = []
    for (addr, asset), g in df.groupby(["from_address", "asset"], sort=True):
        if len(g) <= cfg.spike_min_history:
            continue
        amounts = g["amount"].to_numpy(dtype=float)
        refs = g["evidence_ref"].tolist()
        for k in range(cfg.spike_min_history, len(g)):
            lo = max(0, k - cfg.spike_lookback)
            baseline = float(np.median(amounts[lo:k]))
            if baseline <= 0 or amounts[k] < cfg.spike_factor * baseline:
                continue
            ratio = float(amounts[k] / baseline)
            row = g.iloc[k]
            evidence = (refs[k], *refs[lo:k])  # flagged transfer first, then its baseline
            explanation = (
                f"Address {addr} sent {fmt_amount(amounts[k])} {asset} to {row['to_address']} at "
                f"{fmt_ts(row['timestamp'])}. The median of its previous {k - lo} {asset} transfers "
                f"in the loaded data is {fmt_amount(baseline)} {asset}, so this transfer is "
                f"{ratio:.1f}x that baseline. Rule: at least {cfg.spike_factor:g}x the median of up to "
                f"{cfg.spike_lookback} prior transfers, with at least {cfg.spike_min_history} prior transfers."
            )
            caveats = (
                "Large one-off transfers have many benign causes (treasury moves, purchases, "
                "consolidation, change of wallet). The baseline only reflects the loaded data and "
                "ignores activity outside it."
            )
            out.append(
                Indicator(
                    indicator_id=stable_id("IND", H_VALUE, addr, asset, *evidence),
                    heuristic=H_VALUE,
                    title=f"Value spike: {fmt_amount(amounts[k])} {asset} is {ratio:.0f}x baseline ({short_addr(addr)})",
                    priority="high" if ratio >= 3 * cfg.spike_factor else "medium",
                    explanation=explanation,
                    caveats=caveats,
                    addresses=(addr, row["to_address"]),
                    evidence_refs=evidence,
                    parameters={
                        "spike_factor": cfg.spike_factor,
                        "spike_min_history": cfg.spike_min_history,
                        "spike_lookback": cfg.spike_lookback,
                    },
                    metrics={
                        "primary_ref": refs[k],
                        "asset": asset,
                        "amount": float(amounts[k]),
                        "baseline_median": baseline,
                        "ratio": ratio,
                        "baseline_transfer_count": int(k - lo),
                    },
                )
            )
    return out


# ------------------------------------------------------------------------- multi-hop
def detect_rapid_multihop(df: pd.DataFrame, cfg: HeuristicConfig | None = None) -> list[Indicator]:
    """Time-respecting chains A->B->C->... where each hop forwards most of the value quickly."""
    cfg = (cfg or HeuristicConfig()).validate()
    df = _prep(df)
    out: list[Indicator] = []
    max_delay = cfg.multihop_max_delay_minutes * 60
    for asset, grp in df.groupby("asset", sort=True):
        g = grp.reset_index(drop=True)
        n = len(g)
        secs = _secs(g["timestamp"])
        frm, to = g["from_address"].tolist(), g["to_address"].tolist()
        amt = g["amount"].to_numpy(dtype=float)
        refs = g["evidence_ref"].tolist()
        by_sender: dict[str, list[int]] = defaultdict(list)
        for idx, sender in enumerate(frm):
            by_sender[sender].append(idx)

        succ: dict[int, list[int]] = {}
        for i in range(n):
            nxt: list[int] = []
            for j in by_sender.get(to[i], []):
                if j <= i:
                    continue
                if secs[j] - secs[i] > max_delay:
                    break
                if amt[j] <= amt[i] * (1 + 1e-9) and amt[j] >= cfg.multihop_min_retention * amt[i]:
                    nxt.append(j)
                if len(nxt) >= cfg.multihop_max_branching:
                    break
            succ[i] = nxt
        non_heads = {j for lst in succ.values() for j in lst}
        heads = [i for i in range(n) if i not in non_heads and succ[i]]

        chains: list[list[int]] = []

        def dfs(path: list[int], visited: set[str]) -> None:
            if len(chains) >= cfg.multihop_max_chains:
                return
            last = path[-1]
            options = (
                [j for j in succ[last] if to[j] not in visited]
                if len(path) < cfg.multihop_max_depth
                else []
            )
            if not options:
                if len(path) >= cfg.multihop_min_transfers:
                    chains.append(list(path))
                return
            for j in options:
                path.append(j)
                visited.add(to[j])
                dfs(path, visited)
                visited.discard(to[j])
                path.pop()

        for h in heads:
            dfs([h], {frm[h], to[h]})

        for path in chains:
            addresses = (frm[path[0]], *[to[i] for i in path])
            evidence = tuple(refs[i] for i in path)
            elapsed = float(secs[path[-1]] - secs[path[0]])
            retention = float(amt[path[-1]] / amt[path[0]])
            explanation = (
                f"{len(path)} consecutive {asset} transfers form a forwarding chain "
                f"{' -> '.join(addresses)}. Each hop starts within {cfg.multihop_max_delay_minutes:g} "
                f"minutes of the previous one and forwards between {cfg.multihop_min_retention:.0%} and "
                f"100% of the value received. The chain took {_dur(elapsed)} end to end; "
                f"{fmt_amount(amt[path[0]])} {asset} entered and {fmt_amount(amt[path[-1]])} {asset} "
                f"left the final hop ({retention:.1%} retained)."
            )
            caveats = (
                "Rapid forwarding also occurs in legitimate flows (custodial or payment-processor "
                "sweeps, wallet migrations, relayers). Matching amounts and timing do not establish "
                "that the same party controls the addresses on the chain."
            )
            out.append(
                Indicator(
                    indicator_id=stable_id("IND", H_MULTIHOP, asset, *evidence),
                    heuristic=H_MULTIHOP,
                    title=f"Rapid multi-hop chain: {len(path)} hops in {_dur(elapsed)} ({asset})",
                    priority="high" if len(path) >= cfg.multihop_min_transfers + 2 else "medium",
                    explanation=explanation,
                    caveats=caveats,
                    addresses=addresses,
                    evidence_refs=evidence,
                    parameters={
                        "multihop_min_transfers": cfg.multihop_min_transfers,
                        "multihop_max_delay_minutes": cfg.multihop_max_delay_minutes,
                        "multihop_min_retention": cfg.multihop_min_retention,
                        "multihop_max_depth": cfg.multihop_max_depth,
                        "multihop_max_branching": cfg.multihop_max_branching,
                    },
                    metrics={
                        "asset": asset,
                        "hops": len(path),
                        "elapsed_seconds": elapsed,
                        "amount_in": float(amt[path[0]]),
                        "amount_out": float(amt[path[-1]]),
                        "retention": retention,
                    },
                )
            )
    return out


# ----------------------------------------------------------------- repeated interactions
def detect_repeated_interactions(
    df: pd.DataFrame,
    cfg: HeuristicConfig | None = None,
    watchlist: list[str] | None = None,
) -> list[Indicator]:
    """Counterparties that transact with an analyst-selected address repeatedly."""
    cfg = (cfg or HeuristicConfig()).validate()
    df = _prep(df)
    out: list[Indicator] = []
    selected = sorted({normalize_address(a) for a in (watchlist or []) if a and str(a).strip()})
    for w in selected:
        sub = df[((df["from_address"] == w) | (df["to_address"] == w)) & (df["from_address"] != df["to_address"])]
        if sub.empty:
            continue
        sub = sub.assign(_cp=np.where(sub["from_address"] == w, sub["to_address"], sub["from_address"]))
        for cp, g in sub.groupby("_cp", sort=True):
            if len(g) < cfg.repeat_min_interactions:
                continue
            sent = int((g["from_address"] == w).sum())
            received = len(g) - sent
            refs = tuple(g["evidence_ref"])
            span_days = (g["timestamp"].max() - g["timestamp"].min()).total_seconds() / 86400
            totals = _totals(g)
            both_ways = sent > 0 and received > 0
            explanation = (
                f"Selected address {w} and {cp} exchanged {len(g)} transfers ({sent} from the selected "
                f"address, {received} to it) between {fmt_ts(g['timestamp'].min())} and "
                f"{fmt_ts(g['timestamp'].max())} ({span_days:.1f} days); combined value {fmt_totals(totals)}. "
                f"Rule: at least {cfg.repeat_min_interactions} transfers between the pair."
            )
            caveats = (
                "Repeated two-way transfers can reflect ordinary commerce, subscriptions, "
                "exchange deposits and withdrawals, or the analyst's own test transfers. "
                "Interaction frequency does not show common ownership or intent."
            )
            out.append(
                Indicator(
                    indicator_id=stable_id("IND", H_REPEAT, w, cp, *refs),
                    heuristic=H_REPEAT,
                    title=f"Repeated interaction: {len(g)} transfers between {short_addr(w)} and {short_addr(cp)}",
                    priority="high" if len(g) >= 2 * cfg.repeat_min_interactions else "medium",
                    explanation=explanation,
                    caveats=caveats,
                    addresses=(w, cp),
                    evidence_refs=refs,
                    parameters={"repeat_min_interactions": cfg.repeat_min_interactions, "watchlist": selected},
                    metrics={
                        "transfer_count": len(g),
                        "sent_by_selected": sent,
                        "received_by_selected": received,
                        "bidirectional": both_ways,
                        "span_days": float(span_days),
                        "totals_by_asset": totals,
                    },
                )
            )
    return out


def run_all(
    df: pd.DataFrame,
    cfg: HeuristicConfig | None = None,
    watchlist: list[str] | None = None,
) -> list[Indicator]:
    """Run every detector; output order is deterministic (priority, heuristic, id)."""
    cfg = (cfg or HeuristicConfig()).validate()
    df = _prep(df)
    found = [
        *detect_bursts(df, cfg),
        *detect_value_anomalies(df, cfg),
        *detect_rapid_multihop(df, cfg),
        *detect_repeated_interactions(df, cfg, watchlist),
    ]
    rank = {p: i for i, p in enumerate(PRIORITIES)}
    return sorted(found, key=lambda i: (rank[i.priority], i.heuristic, i.indicator_id))

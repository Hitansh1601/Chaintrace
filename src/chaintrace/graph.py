"""Filtering and directed-graph construction (NetworkX)."""
from __future__ import annotations

from collections import deque

import networkx as nx
import pandas as pd

from .schema import normalize_address

DIRECTIONS = ("both", "out", "in")


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def filter_transactions(
    df: pd.DataFrame,
    start=None,
    end=None,
    assets: list[str] | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
) -> pd.DataFrame:
    """Filter by time window, asset and transfer value. Bounds are inclusive."""
    if start is not None and end is not None and _utc(start) > _utc(end):
        raise ValueError("start must not be after end")
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise ValueError("min_amount must not exceed max_amount")
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df["timestamp"] >= _utc(start)
    if end is not None:
        mask &= df["timestamp"] <= _utc(end)
    if assets is not None:
        mask &= df["asset"].isin({a.strip().upper() for a in assets})
    if min_amount is not None:
        mask &= df["amount"] >= min_amount
    if max_amount is not None:
        mask &= df["amount"] <= max_amount
    return df[mask].reset_index(drop=True)


def build_graph(df: pd.DataFrame) -> nx.DiGraph:
    """Aggregate transfers into a directed graph (one edge per sender->recipient pair)."""
    graph = nx.DiGraph()
    if df.empty:
        return graph
    for (src, dst), grp in df.groupby(["from_address", "to_address"], sort=True):
        graph.add_edge(
            src,
            dst,
            tx_count=int(len(grp)),
            total_by_asset={k: float(v) for k, v in grp.groupby("asset")["amount"].sum().items()},
            first_seen=grp["timestamp"].min(),
            last_seen=grp["timestamp"].max(),
            evidence_refs=sorted(grp["evidence_ref"]),
        )
    sent = df["from_address"].value_counts()
    received = df["to_address"].value_counts()
    for node in graph.nodes:
        graph.nodes[node]["sent_count"] = int(sent.get(node, 0))
        graph.nodes[node]["received_count"] = int(received.get(node, 0))
    return graph


def neighborhood(graph: nx.DiGraph, seed: str, depth: int, direction: str = "both") -> nx.DiGraph:
    """Subgraph of addresses within ``depth`` hops of ``seed``.

    ``direction``: ``out`` follows funds forward, ``in`` traces backward, ``both`` either.
    """
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
        raise ValueError("depth must be a non-negative integer")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}")
    seed = normalize_address(seed)
    if seed not in graph:
        raise KeyError(f"address not present in graph: {seed}")
    seen = {seed: 0}
    queue = deque([seed])
    while queue:
        node = queue.popleft()
        if seen[node] == depth:
            continue
        neighbours: set[str] = set()
        if direction in ("out", "both"):
            neighbours |= set(graph.successors(node))
        if direction in ("in", "both"):
            neighbours |= set(graph.predecessors(node))
        for nxt in sorted(neighbours):
            if nxt not in seen:
                seen[nxt] = seen[node] + 1
                queue.append(nxt)
    sub = graph.subgraph(seen).copy()
    for node, hops in seen.items():
        sub.nodes[node]["hops_from_seed"] = hops
    return sub

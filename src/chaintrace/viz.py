"""Plotly figures for the graph explorer and the timeline."""
from __future__ import annotations

import networkx as nx
import pandas as pd
import plotly.graph_objects as go

from .findings import fmt_totals, short_addr

MAX_ARROWS = 250


def node_label(address: str, labels: dict[str, str] | None = None) -> str:
    label = (labels or {}).get(address)
    return f"{label} ({short_addr(address)})" if label else short_addr(address)


def graph_figure(
    graph: nx.DiGraph,
    seed: str | None = None,
    flagged: set[str] | None = None,
    labels: dict[str, str] | None = None,
) -> go.Figure:
    """Directed transfer graph. Deterministic layout; layout distance carries no meaning."""
    labels, flagged = labels or {}, flagged or set()
    fig = go.Figure()
    if graph.number_of_nodes() == 0:
        fig.update_layout(title="No transfers match the current filters", height=300)
        return fig
    pos = nx.spring_layout(graph, seed=42)
    ex: list = []
    ey: list = []
    mx, my, mt = [], [], []
    drawable = [(u, v, d) for u, v, d in graph.edges(data=True) if u != v]
    for u, v, data in drawable:
        (x0, y0), (x1, y1) = pos[u], pos[v]
        ex += [x0, x1, None]
        ey += [y0, y1, None]
        mx.append((x0 + x1) / 2)
        my.append((y0 + y1) / 2)
        mt.append(
            f"{node_label(u, labels)} → {node_label(v, labels)}<br>{data['tx_count']} transfer(s)"
            f"<br>{fmt_totals(data['total_by_asset'])}<br>{data['first_seen']:%Y-%m-%d %H:%M} → {data['last_seen']:%Y-%m-%d %H:%M} UTC"
        )
        if len(drawable) <= MAX_ARROWS:
            fig.add_annotation(
                x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=3, arrowsize=1, arrowwidth=1, arrowcolor="#8c959f", standoff=9, text="",
            )
    fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=1, color="#8c959f"), hoverinfo="none", showlegend=False))
    fig.add_trace(go.Scatter(x=mx, y=my, mode="markers", marker=dict(size=9, opacity=0), hoverinfo="text", text=mt, showlegend=False))
    nodes = list(graph.nodes)
    colors = ["#cf222e" if n == seed else "#d4a72c" if n in flagged else "#0969da" for n in nodes]
    sizes = [14 + 3 * min(graph.degree(n), 10) for n in nodes]
    hover = [
        f"{node_label(n, labels)}<br>{n}<br>sent {graph.nodes[n].get('sent_count', 0)} · received "
        f"{graph.nodes[n].get('received_count', 0)} (in loaded data)" for n in nodes
    ]
    fig.add_trace(
        go.Scatter(
            x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes], mode="markers+text",
            text=[labels.get(n, short_addr(n)) if len(nodes) <= 40 else "" for n in nodes],
            textposition="top center", textfont=dict(size=9), hoverinfo="text", hovertext=hover,
            marker=dict(color=colors, size=sizes, line=dict(width=1, color="white")), showlegend=False,
        )
    )
    fig.update_layout(
        height=620, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False), yaxis=dict(visible=False), hovermode="closest",
        title=dict(text="Red = seed · amber = appears in an indicator · edges show observed transfers only", font=dict(size=12)),
    )
    return fig


def timeline_figure(timeline: pd.DataFrame, labels: dict[str, str] | None = None) -> go.Figure:
    labels = labels or {}
    fig = go.Figure()
    if timeline.empty:
        fig.update_layout(title="No transfers to display", height=300)
        return fig
    for asset, grp in timeline.groupby("asset"):
        fig.add_trace(
            go.Scatter(
                x=grp["timestamp"], y=grp["amount"], mode="markers", name=asset,
                hovertext=[
                    f"{r.evidence_ref}<br>{node_label(r.from_address, labels)} → {node_label(r.to_address, labels)}"
                    f"<br>{r.amount:g} {r.asset} · block {r.block_number}" for r in grp.itertuples()
                ],
                hoverinfo="text",
            )
        )
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10), yaxis=dict(title="amount", type="log"),
                      xaxis=dict(title="time (UTC)"), title=dict(text="Transfers over time (log amount scale)", font=dict(size=12)))
    return fig

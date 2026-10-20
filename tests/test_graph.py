import pytest
from helpers import addr, frame

from chaintrace.graph import build_graph, filter_transactions, neighborhood


def chain():  # 1 -> 2 -> 3 -> 4 -> 5
    return frame([(1, 2, 0, 5), (2, 3, 60, 5), (3, 4, 120, 5), (4, 5, 180, 5)])


def test_edges_are_directed_and_aggregated():
    df = frame([(1, 2, 0, 1), (1, 2, 60, 2), (2, 1, 90, 0.5), (1, 2, 120, 7, "USDC")])
    g = build_graph(df)
    assert g.number_of_nodes() == 2 and g.number_of_edges() == 2
    e = g[addr(1)][addr(2)]
    assert e["tx_count"] == 3 and e["total_by_asset"] == {"ETH": 3.0, "USDC": 7.0} and len(e["evidence_refs"]) == 3
    assert g.has_edge(addr(2), addr(1)) and g.nodes[addr(1)]["sent_count"] == 3


def test_empty_graph():
    assert build_graph(chain().iloc[0:0]).number_of_nodes() == 0


@pytest.mark.parametrize("depth,expected", [(0, {1}), (1, {1, 2}), (2, {1, 2, 3}), (9, {1, 2, 3, 4, 5})])
def test_hop_depth_out(depth, expected):
    sub = neighborhood(build_graph(chain()), addr(1), depth, "out")
    assert set(sub.nodes) == {addr(n) for n in expected}


def test_direction_in_and_both():
    g = build_graph(chain())
    assert set(neighborhood(g, addr(3), 1, "in").nodes) == {addr(2), addr(3)}
    assert set(neighborhood(g, addr(3), 1, "out").nodes) == {addr(3), addr(4)}
    assert set(neighborhood(g, addr(3), 1, "both").nodes) == {addr(2), addr(3), addr(4)}
    assert neighborhood(g, addr(3), 2, "both").nodes[addr(5)]["hops_from_seed"] == 2


def test_star_and_cycle_patterns():
    star = build_graph(frame([(1, n, n, 1) for n in range(2, 8)]))
    assert star.out_degree(addr(1)) == 6 and len(neighborhood(star, addr(1), 1, "out")) == 7
    cyc = build_graph(frame([(1, 2, 0, 1), (2, 3, 1, 1), (3, 1, 2, 1)]))
    assert set(neighborhood(cyc, addr(1), 5, "out").nodes) == {addr(1), addr(2), addr(3)}


def test_self_transfer_is_a_self_loop():
    g = build_graph(frame([(1, 1, 0, 1)]))
    assert g.has_edge(addr(1), addr(1))


def test_seed_is_normalised_and_unknown_seed_raises():
    g = build_graph(chain())
    assert addr(1) in neighborhood(g, addr(1).upper().replace("0X", "0x"), 1).nodes
    with pytest.raises(KeyError):
        neighborhood(g, addr(99), 1)


@pytest.mark.parametrize("depth", [-1, 1.5, "2", True])
def test_invalid_depth(depth):
    with pytest.raises(ValueError):
        neighborhood(build_graph(chain()), addr(1), depth)


def test_invalid_direction():
    with pytest.raises(ValueError):
        neighborhood(build_graph(chain()), addr(1), 1, "sideways")


def test_filters_combine():
    df = frame([(1, 2, 0, 1), (1, 2, 3600, 50), (1, 2, 7200, 5, "USDC"), (2, 3, 10800, 2)])
    assert len(filter_transactions(df, assets=["usdc"])) == 1
    assert len(filter_transactions(df, min_amount=2)) == 3
    assert len(filter_transactions(df, max_amount=2)) == 2
    assert len(filter_transactions(df, start="2026-02-01T01:00:00Z", end="2026-02-01T02:00:00Z")) == 2
    assert len(filter_transactions(df, start="2026-02-01T01:00:00", assets=["ETH"], max_amount=10)) == 1  # naive = UTC


def test_filter_invalid_ranges():
    df = chain()
    with pytest.raises(ValueError):
        filter_transactions(df, min_amount=5, max_amount=1)
    with pytest.raises(ValueError):
        filter_transactions(df, start="2026-03-01", end="2026-01-01")


def test_filter_can_return_empty():
    assert filter_transactions(chain(), assets=["DOGE"]).empty

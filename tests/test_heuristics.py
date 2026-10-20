import pytest
from helpers import addr, frame

from chaintrace.findings import H_BURST, H_MULTIHOP, H_REPEAT, H_VALUE
from chaintrace.heuristics import (
    HeuristicConfig, detect_bursts, detect_rapid_multihop, detect_repeated_interactions,
    detect_value_anomalies, run_all,
)
from chaintrace.synthetic import address, check_manifest, load_manifest


# ------------------------------------------------------------------ bursts
def burst_rows(n=10, gap=30, recipients=True, sender=1):
    return [(sender, 100 + (i if recipients else 0), i * gap, 1.0) for i in range(n)]


def test_burst_detected_with_evidence():
    df = frame(burst_rows())
    found = detect_bursts(df)
    assert len(found) == 1
    ind = found[0]
    assert ind.heuristic == H_BURST and ind.addresses == (addr(1),) and len(ind.evidence_refs) == 10
    assert ind.metrics["direction"] == "outgoing" and ind.metrics["distinct_counterparties"] == 10
    assert "10 transfers" in ind.explanation and "caveats" not in ind.explanation and ind.caveats


def test_spread_out_transfers_do_not_burst():
    assert detect_bursts(frame(burst_rows(gap=3600))) == []


def test_same_counterparty_is_not_a_burst():
    assert detect_bursts(frame(burst_rows(recipients=False))) == []


def test_burst_threshold_is_configurable_and_boundary_inclusive():
    df = frame(burst_rows(n=5))
    assert detect_bursts(df) == []
    assert len(detect_bursts(df, HeuristicConfig(burst_min_transfers=5, burst_min_counterparties=5))) == 1
    wide = frame(burst_rows(n=10, gap=120))  # spans 18 min
    assert detect_bursts(wide) == []
    assert len(detect_bursts(wide, HeuristicConfig(burst_window_minutes=20))) == 1


def test_incoming_burst_detected():
    rows = [(100 + i, 1, i * 30, 1.0) for i in range(10)]
    found = detect_bursts(frame(rows))
    assert [i.metrics["direction"] for i in found] == ["incoming"]


def test_two_separate_bursts_yield_two_indicators():
    rows = burst_rows(10) + [(1, 200 + i, 36000 + i * 30, 1.0) for i in range(10)]
    assert len(detect_bursts(frame(rows))) == 2


# ----------------------------------------------------------- value changes
def spike_rows(amounts, asset="ETH"):
    return [(1, 2, i * 3600, a, asset) for i, a in enumerate(amounts)]


def test_value_spike_detected_and_baseline_recorded():
    df = frame(spike_rows([1, 1.1, 0.9, 1, 1.05, 50]))
    (ind,) = detect_value_anomalies(df)
    assert ind.heuristic == H_VALUE and len(ind.evidence_refs) == 6
    assert ind.evidence_refs[0] == ind.metrics["primary_ref"]
    assert ind.metrics["ratio"] == pytest.approx(50 / 1.0, rel=0.1)


def test_not_enough_history_no_spike():
    assert detect_value_anomalies(frame(spike_rows([1, 1, 1, 1, 50]))) == []


def test_gradual_growth_is_not_a_spike():
    assert detect_value_anomalies(frame(spike_rows([1, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 4]))) == []


def test_assets_are_not_mixed():
    rows = spike_rows([1, 1, 1, 1, 1]) + [(1, 2, 99999, 500, "USDC")]
    assert detect_value_anomalies(frame(rows)) == []


# ---------------------------------------------------------------- multi-hop
def chain_rows(amounts, gaps):
    t, rows = 0, []
    for k, (a, g) in enumerate(zip(amounts, gaps)):
        t += g
        rows.append((k + 1, k + 2, t, a))
    return rows


def test_rapid_chain_detected():
    df = frame(chain_rows([10, 9.8, 9.6, 9.4, 9.2], [0, 120, 120, 120, 120]))
    (ind,) = detect_rapid_multihop(df)
    assert ind.heuristic == H_MULTIHOP
    assert ind.addresses == tuple(addr(n) for n in range(1, 7)) and ind.metrics["hops"] == 5
    assert ind.metrics["retention"] == pytest.approx(0.92)


def test_slow_gap_breaks_chain():
    assert detect_rapid_multihop(frame(chain_rows([10, 9.8, 9.6, 9.4, 9.2], [0, 120, 7200, 120, 120]))) == []


def test_low_retention_breaks_chain():
    assert detect_rapid_multihop(frame(chain_rows([10, 5, 2.5, 1.2, 0.6], [0, 60, 60, 60, 60]))) == []


def test_growing_amounts_are_not_forwarding():
    assert detect_rapid_multihop(frame(chain_rows([10, 12, 14, 16, 18], [0, 60, 60, 60, 60]))) == []


def test_short_chain_below_minimum():
    assert detect_rapid_multihop(frame(chain_rows([10, 9.8, 9.6], [0, 60, 60]))) == []
    cfg = HeuristicConfig(multihop_min_transfers=3)
    assert len(detect_rapid_multihop(frame(chain_rows([10, 9.8, 9.6], [0, 60, 60])), cfg)) == 1


def test_cycles_terminate_without_revisiting_addresses():
    df = frame([(1, 2, 0, 10), (2, 3, 60, 9.9), (3, 1, 120, 9.8), (1, 2, 180, 9.7), (2, 3, 240, 9.6)])
    assert detect_rapid_multihop(df) == []


def test_branching_yields_each_path():
    rows = [(1, 2, 0, 10), (2, 3, 60, 9.9), (2, 4, 70, 9.5), (3, 5, 120, 9.8), (4, 6, 130, 9.4), (5, 7, 200, 9.7), (6, 8, 210, 9.3)]
    found = detect_rapid_multihop(frame(rows), HeuristicConfig(multihop_min_transfers=4))
    assert len(found) == 2


# --------------------------------------------------- repeated interactions
def repeat_rows(n=6):
    return [((1, 2, i * 86400, 1.0) if i % 2 == 0 else (2, 1, i * 86400, 1.0)) for i in range(n)]


def test_repeated_interaction_needs_watchlist():
    df = frame(repeat_rows())
    assert detect_repeated_interactions(df) == []
    assert detect_repeated_interactions(df, watchlist=[]) == []
    (ind,) = detect_repeated_interactions(df, watchlist=[addr(1)])
    assert ind.heuristic == H_REPEAT and ind.metrics["bidirectional"] and ind.metrics["transfer_count"] == 6
    assert set(ind.addresses) == {addr(1), addr(2)}


def test_repeat_threshold_unknown_watch_and_case_insensitive():
    df = frame(repeat_rows(4))
    assert detect_repeated_interactions(df, watchlist=[addr(1)]) == []
    df = frame(repeat_rows(6))
    assert detect_repeated_interactions(df, watchlist=[addr(99)]) == []
    assert len(detect_repeated_interactions(df, watchlist=[addr(1).upper().replace("0X", "0x")])) == 1


# ---------------------------------------------------------- config & misc
@pytest.mark.parametrize("kw", [dict(burst_min_transfers=0), dict(spike_factor=-1), dict(multihop_min_retention=1.5),
                                dict(burst_min_transfers=3, burst_min_counterparties=5), dict(spike_min_history=2.5)])
def test_invalid_config(kw):
    with pytest.raises(ValueError):
        HeuristicConfig(**kw).validate()


def test_config_roundtrip_and_unknown_key():
    cfg = HeuristicConfig(spike_factor=7.0)
    assert HeuristicConfig.from_dict(cfg.to_dict()) == cfg
    with pytest.raises(ValueError):
        HeuristicConfig.from_dict({"nope": 1})


def test_missing_columns_rejected():
    with pytest.raises(ValueError):
        run_all(frame(burst_rows()).drop(columns=["amount"]))


def test_ids_deterministic_and_order_independent():
    df = frame(burst_rows() + spike_rows([1, 1, 1, 1, 1, 80]))
    a = [i.indicator_id for i in run_all(df)]
    b = [i.indicator_id for i in run_all(df.sample(frac=1, random_state=3).reset_index(drop=True))]
    assert a == b and len(a) == len(set(a)) > 0


def test_empty_table_gives_no_indicators():
    assert run_all(frame(burst_rows()).iloc[0:0]) == []


def test_every_indicator_has_refs_explanation_and_caveats(synthetic_df):
    for ind in run_all(synthetic_df, watchlist=[address("SYN-WATCH-W")]):
        assert ind.evidence_refs and ind.explanation and ind.caveats and ind.addresses
        assert set(ind.evidence_refs) <= set(synthetic_df.evidence_ref)


def test_synthetic_planted_patterns_found_and_nothing_else(synthetic_df):
    found = run_all(synthetic_df, watchlist=[address("SYN-WATCH-W")])
    check = check_manifest(found, load_manifest())
    assert all(c["matched"] for c in check)
    assert len(found) == len(check) == 5  # no stray indicators from background noise
    assert len(run_all(synthetic_df)) == 4  # repeated-interaction needs the watchlist

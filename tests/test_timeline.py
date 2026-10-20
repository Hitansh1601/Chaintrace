from helpers import addr, frame

from chaintrace.heuristics import run_all
from chaintrace.timeline import TIMELINE_COLUMNS, build_timeline


def test_columns_and_chronological_order():
    df = frame([(1, 2, 300, 1), (2, 3, 100, 2), (3, 4, 200, 3)]).sample(frac=1, random_state=1)
    tl = build_timeline(df)
    assert list(tl.columns) == TIMELINE_COLUMNS
    assert tl["timestamp"].is_monotonic_increasing and list(tl["amount"]) == [2, 3, 1]


def test_address_filter_matches_either_side():
    tl = build_timeline(frame([(1, 2, 0, 1), (3, 1, 10, 1), (3, 4, 20, 1)]), addr(1))
    assert len(tl) == 2


def test_indicator_tags_use_evidence_refs():
    df = frame([(1, 100 + i, i * 30, 1.0) for i in range(10)])
    inds = run_all(df)
    tl = build_timeline(df, indicators=inds)
    assert (tl["indicator_ids"] == inds[0].indicator_id).all()
    assert "indicator_ids" not in build_timeline(df).columns

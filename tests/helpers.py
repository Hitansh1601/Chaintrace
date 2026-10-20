import pandas as pd

from chaintrace.importer import validate_frame

BASE = pd.Timestamp("2026-02-01T00:00:00Z")


def addr(n: int) -> str:
    return "0x" + f"{n:040x}"


def thash(n: int) -> str:
    return "0x" + f"{n:064x}"


def ts(seconds: float = 0) -> str:
    return (BASE + pd.Timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def frame(rows, source="TEST"):
    """rows: (from_n, to_n, seconds, amount[, asset]) -> validated transfer table."""
    recs = []
    for k, (frm, to, secs, amt, *rest) in enumerate(rows, start=1):
        recs.append({
            "tx_hash": thash(k), "block_number": str(1000 + k), "timestamp": ts(secs),
            "from_address": addr(frm), "to_address": addr(to), "asset": rest[0] if rest else "ETH",
            "amount": str(amt), "data_source": source,
        })
    res = validate_frame(pd.DataFrame(recs, dtype=str), "test-sha", source)
    assert res.rejected.empty, res.rejected
    return res.valid

import io

import pandas as pd
import pytest
from helpers import addr, thash

from chaintrace.importer import load_transactions, validate_frame
from chaintrace.schema import SchemaError
from chaintrace.synthetic import SAMPLE_CSV

HEADER = "tx_hash,block_number,timestamp,from_address,to_address,asset,amount,data_source\n"


def row(**kw):
    base = dict(tx_hash=thash(1), block=1, ts="2026-02-01T00:00:00Z", frm=addr(1), to=addr(2), asset="eth", amt="1.5", src="T")
    base.update(kw)
    return f"{base['tx_hash']},{base['block']},{base['ts']},{base['frm']},{base['to']},{base['asset']},{base['amt']},{base['src']}\n"


def load(text):
    return load_transactions(text.encode())


def test_synthetic_sample_loads_cleanly():
    res = load_transactions(SAMPLE_CSV)
    assert len(res.valid) == 201 and res.rejected.empty
    assert set(res.valid["data_source"]) == {"SYNTHETIC_DEMO_v1"}


def test_normalisation_and_evidence_ref():
    res = load(HEADER + row(asset="eth", frm=addr(255).upper().replace("0X", "0x")))
    r = res.valid.iloc[0]
    assert r.asset == "ETH" and r.from_address == r.from_address.lower()
    assert r.evidence_ref == f"{thash(1)}#0" and r.amount_raw == "1.5"
    assert str(res.valid["timestamp"].dt.tz) == "UTC"


def test_transfer_index_distinguishes_transfers_in_one_tx():
    text = "tx_hash,transfer_index,block_number,timestamp,from_address,to_address,asset,amount,data_source\n"
    text += f"{thash(1)},0,1,2026-02-01T00:00:00Z,{addr(1)},{addr(2)},ETH,1,T\n"
    text += f"{thash(1)},1,1,2026-02-01T00:00:00Z,{addr(1)},{addr(3)},ETH,2,T\n"
    res = load(text)
    assert res.rejected.empty and set(res.valid.evidence_ref) == {f"{thash(1)}#0", f"{thash(1)}#1"}


@pytest.mark.parametrize(
    "kw,reason",
    [
        (dict(tx_hash="0x123"), "invalid_tx_hash"),
        (dict(frm="not-an-address"), "invalid_from_address"),
        (dict(to=""), "invalid_to_address"),
        (dict(amt="-1"), "negative_amount"),
        (dict(amt="abc"), "invalid_amount"),
        (dict(amt="nan"), "invalid_amount"),
        (dict(amt="inf"), "invalid_amount"),
        (dict(ts="yesterday"), "invalid_timestamp"),
        (dict(block="1.5"), "invalid_block_number"),
        (dict(block="-3"), "invalid_block_number"),
        (dict(asset=""), "missing_asset"),
        (dict(src=""), "missing_data_source"),
    ],
)
def test_invalid_rows_are_rejected_with_reason(kw, reason):
    res = load(HEADER + row() + row(**{"tx_hash": thash(2), **kw}))
    assert len(res.valid) == 1
    assert len(res.rejected) == 1
    assert reason in res.rejected.iloc[0]["reject_reasons"]
    assert res.rejected.iloc[0]["csv_line"] == 3


def test_duplicate_evidence_ref_rejected_keeps_first():
    res = load(HEADER + row() + row(amt="9"))
    assert len(res.valid) == 1 and res.valid.iloc[0].amount == 1.5
    assert "duplicate_evidence_ref" in res.rejected.iloc[0]["reject_reasons"]


def test_multiple_reasons_are_all_reported():
    res = load(HEADER + row() + row(tx_hash="bad", amt="-2"))
    reasons = res.rejected.iloc[0]["reject_reasons"].split(";")
    assert {"invalid_tx_hash", "negative_amount"} <= set(reasons)


@pytest.mark.parametrize("payload", [b"", b"   \n", b"a,b\n1,2\n", (HEADER).encode()])
def test_unusable_input_raises_schema_error(payload):
    with pytest.raises(SchemaError):
        load_transactions(payload)


def test_missing_column_named_in_error():
    with pytest.raises(SchemaError, match="asset"):
        load_transactions(b"tx_hash,block_number,timestamp,from_address,to_address,amount,data_source\n")


def test_binary_garbage_does_not_crash_unexpectedly():
    with pytest.raises(SchemaError):
        load_transactions(b"\xff\xfe\x00\x01\x02")


def test_sha256_stable_and_input_types_equivalent(tmp_path):
    text = HEADER + row()
    p = tmp_path / "t.csv"
    p.write_text(text, newline="\n")  # exact bytes: no CRLF translation on Windows
    a, b, c = load_transactions(p), load_transactions(text.encode()), load_transactions(io.BytesIO(text.encode()))
    assert a.sha256 == b.sha256 == c.sha256 and a.source_name == "t.csv"


def test_unsupported_source_type():
    with pytest.raises(TypeError):
        load_transactions(123)


def test_validate_frame_requires_columns():
    with pytest.raises(SchemaError):
        validate_frame(pd.DataFrame({"x": ["1"]}), "s", "n")

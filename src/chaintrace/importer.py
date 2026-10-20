"""CSV import and validation.

Invalid rows are never silently dropped: they are returned in
``ImportResult.rejected`` together with the CSV line number and every reason.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd

from .schema import (
    CANONICAL_COLUMNS,
    REQUIRED_COLUMNS,
    SORT_KEYS,
    SchemaError,
    ValidationConfig,
)

MAX_INPUT_BYTES = 50 * 1024 * 1024


@dataclass
class ImportResult:
    valid: pd.DataFrame
    rejected: pd.DataFrame
    sha256: str
    source_name: str

    @property
    def total_rows(self) -> int:
        return len(self.valid) + len(self.rejected)


def _read_bytes(source) -> tuple[bytes, str]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        return path.read_bytes(), path.name
    if isinstance(source, (bytes, bytearray)):
        return bytes(source), "<bytes>"
    if hasattr(source, "read"):
        data = source.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        return data, getattr(source, "name", "<stream>")
    raise TypeError(f"unsupported source type: {type(source).__name__}")


def load_transactions(
    source: str | Path | bytes | BinaryIO,
    config: ValidationConfig | None = None,
    source_name: str | None = None,
) -> ImportResult:
    """Read and validate a transaction CSV. Raises ``SchemaError`` if unusable."""
    data, name = _read_bytes(source)
    if len(data) > MAX_INPUT_BYTES:
        raise SchemaError(f"input exceeds {MAX_INPUT_BYTES // (1024 * 1024)} MiB limit")
    if not data.strip():
        raise SchemaError("input is empty")
    sha = hashlib.sha256(data).hexdigest()
    try:
        raw = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise SchemaError(f"could not parse CSV: {exc}") from exc
    return validate_frame(raw, sha, source_name or name, config)


def validate_frame(
    raw: pd.DataFrame,
    sha256: str,
    source_name: str,
    config: ValidationConfig | None = None,
) -> ImportResult:
    """Validate and normalise an all-string DataFrame (shared by every adapter)."""
    cfg = config or ValidationConfig()
    addr_re = re.compile(cfg.address_regex)
    hash_re = re.compile(cfg.tx_hash_regex)

    df = raw.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"missing required column(s): {', '.join(missing)}")
    if df.empty:
        raise SchemaError("no data rows")
    if "transfer_index" not in df.columns:
        df["transfer_index"] = "0"
    text_cols = list(REQUIRED_COLUMNS) + ["transfer_index"]
    for col in text_cols:
        df[col] = df[col].astype(str).str.strip()
    df["csv_line"] = np.arange(2, len(df) + 2)  # header is line 1

    reasons: list[list[str]] = [[] for _ in range(len(df))]

    def flag(mask, reason: str) -> None:
        for i in np.flatnonzero(np.asarray(mask, dtype=bool)):
            reasons[i].append(reason)

    flag(~df["tx_hash"].map(lambda v: bool(hash_re.match(v))), "invalid_tx_hash")
    flag(~df["from_address"].map(lambda v: bool(addr_re.match(v))), "invalid_from_address")
    flag(~df["to_address"].map(lambda v: bool(addr_re.match(v))), "invalid_to_address")

    block = pd.to_numeric(df["block_number"], errors="coerce")
    flag(block.isna() | (block < 0) | ((block % 1) != 0), "invalid_block_number")

    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce", format="ISO8601")
    flag(ts.isna(), "invalid_timestamp")

    amount = pd.to_numeric(df["amount"], errors="coerce")
    finite = np.isfinite(amount.to_numpy(dtype=float))
    flag(~finite, "invalid_amount")
    flag(finite & (amount.to_numpy(dtype=float) < 0), "negative_amount")

    flag(df["asset"] == "", "missing_asset")
    flag(df["data_source"] == "", "missing_data_source")
    tidx = pd.to_numeric(df["transfer_index"], errors="coerce")
    flag(tidx.isna() | (tidx < 0) | ((tidx % 1) != 0), "invalid_transfer_index")

    out = pd.DataFrame(
        {
            "tx_hash": df["tx_hash"].str.lower(),
            "transfer_index": tidx.fillna(0).astype("int64"),
            "block_number": block.fillna(0).astype("int64"),
            "timestamp": ts,
            "from_address": df["from_address"].str.lower(),
            "to_address": df["to_address"].str.lower(),
            "asset": df["asset"].str.upper(),
            "amount": amount,
            "amount_raw": df["amount"],
            "data_source": df["data_source"],
        }
    )
    out["evidence_ref"] = out["tx_hash"] + "#" + out["transfer_index"].astype(str)

    # Duplicate evidence references: keep the first otherwise-valid occurrence only.
    ok_so_far = np.array([len(r) == 0 for r in reasons])
    dup = np.zeros(len(out), dtype=bool)
    dup[ok_so_far] = out.loc[ok_so_far, "evidence_ref"].duplicated(keep="first").to_numpy()
    flag(dup, "duplicate_evidence_ref")

    bad = np.array([len(r) > 0 for r in reasons])
    rejected = df.loc[bad, ["csv_line", *text_cols]].copy()
    rejected["reject_reasons"] = [";".join(r) for r, b in zip(reasons, bad) if b]
    rejected = rejected.reset_index(drop=True)

    valid = (
        out.loc[~bad, list(CANONICAL_COLUMNS)]
        .sort_values(SORT_KEYS, kind="mergesort")
        .reset_index(drop=True)
    )
    return ImportResult(valid=valid, rejected=rejected, sha256=sha256, source_name=source_name)

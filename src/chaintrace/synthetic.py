"""Deterministic SYNTHETIC dataset with planted patterns.

Everything here is invented. Addresses are derived from SHA-256 of role labels such as
``SYN-FANOUT-SRC``; they are not real wallets and the role labels make no claim about any
real person or entity. The planted patterns are listed in a manifest so tests can confirm
that the heuristics find them (and so the one deliberately benign look-alike is explicit).
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .findings import H_BURST, H_MULTIHOP, H_REPEAT, H_VALUE, Indicator

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"
SAMPLE_CSV = SAMPLE_DIR / "synthetic_transactions.csv"
LABELS_CSV = SAMPLE_DIR / "synthetic_address_labels.csv"
MANIFEST_JSON = SAMPLE_DIR / "synthetic_manifest.json"

T0 = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
BASE_BLOCK = 19_000_000
SOURCE = "SYNTHETIC_DEMO_v1"
SEED = 1337
CSV_FIELDS = [
    "tx_hash", "transfer_index", "block_number", "timestamp",
    "from_address", "to_address", "asset", "amount", "data_source",
]


def address(label: str) -> str:
    """Deterministic fake address for a synthetic role label."""
    return "0x" + hashlib.sha256(f"chaintrace-synthetic-address:{label}".encode()).hexdigest()[:40]


class _Builder:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.counter = 0

    def add(self, when: datetime, src: str, dst: str, amount: float, asset: str = "ETH") -> None:
        self.counter += 1
        self.rows.append(
            {
                "tx_hash": "0x" + hashlib.sha256(f"chaintrace-synthetic-tx:{self.counter}".encode()).hexdigest(),
                "transfer_index": 0,
                "block_number": BASE_BLOCK + int((when - T0).total_seconds() // 12),
                "timestamp": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "from_address": address(src),
                "to_address": address(dst),
                "asset": asset,
                "amount": f"{amount:.6f}",
                "data_source": SOURCE,
            }
        )


def generate() -> tuple[list[dict], dict[str, str], list[dict]]:
    """Return (rows, labels {label: address}, manifest of planted patterns)."""
    rng = random.Random(SEED)
    b = _Builder()
    labels: set[str] = set()

    def lab(*names: str) -> None:
        labels.update(names)

    # --- Background: ordinary-looking, low-volume transfers spread over 30 days --------
    users = [f"SYN-USER-{i:02d}" for i in range(1, 16)]
    services = ["SYN-SERVICE-A", "SYN-SERVICE-B"]
    lab(*users, *services)
    for _ in range(140):
        when = T0 + timedelta(seconds=rng.uniform(0, 30 * 86400))
        src = rng.choice(users)
        dst = rng.choice([a for a in users + services if a != src])
        if rng.random() < 0.7:
            b.add(when, src, dst, round(rng.uniform(0.05, 1.5), 6), "ETH")
        else:
            b.add(when, src, dst, round(rng.uniform(20, 400), 2), "USDC")

    # --- A: fan-out burst -------------------------------------------------------------
    t = T0 + timedelta(days=3, hours=14, minutes=20)
    lab("SYN-EXT-FUNDER", "SYN-FANOUT-SRC", "SYN-CONSOLIDATOR")
    b.add(t, "SYN-EXT-FUNDER", "SYN-FANOUT-SRC", 24.0)
    start = t + timedelta(minutes=40)
    for i in range(14):
        rcpt = f"SYN-FANOUT-R{i + 1:02d}"
        lab(rcpt)
        b.add(start + timedelta(seconds=i * 28 + rng.randint(0, 10)), "SYN-FANOUT-SRC", rcpt,
              round(1.70 + rng.uniform(-0.05, 0.05), 6))
    for i in range(5):  # a few recipients later consolidate (hours later: not "rapid")
        b.add(start + timedelta(hours=2, minutes=20 * i), f"SYN-FANOUT-R{i + 1:02d}", "SYN-CONSOLIDATOR", 1.69)

    # --- B: unusual value change -----------------------------------------------------
    lab("SYN-SPIKE-ACCT", "SYN-SPIKE-DEST")
    for i in range(8):
        b.add(T0 + timedelta(days=2 + 2.5 * i, hours=11, minutes=i * 7), "SYN-SPIKE-ACCT",
              "SYN-SERVICE-A", round(rng.uniform(0.4, 0.9), 6))
    b.add(T0 + timedelta(days=24, hours=9, minutes=5), "SYN-SPIKE-ACCT", "SYN-SPIKE-DEST", 38.0)

    # --- C: rapid multi-hop peel chain -------------------------------------------------
    hops = ["SYN-CHAIN-ORIGIN", "SYN-CHAIN-H1", "SYN-CHAIN-H2", "SYN-CHAIN-H3",
            "SYN-CHAIN-H4", "SYN-CHAIN-H5", "SYN-CHAIN-DEST"]
    lab(*hops, *[f"SYN-PEEL-{i}" for i in range(1, 5)])
    t = T0 + timedelta(days=9, hours=3, minutes=12)
    amounts = [20.0, 19.6, 19.2, 18.8, 18.4, 18.0]
    gaps = [0, 190, 240, 150, 180, 300]  # seconds between hops
    for k in range(6):
        t += timedelta(seconds=gaps[k])
        b.add(t, hops[k], hops[k + 1], amounts[k])
        if 1 <= k <= 4:  # small side "peel" payments that are too small to be part of the chain
            b.add(t + timedelta(seconds=45), hops[k], f"SYN-PEEL-{k}", 0.1)

    # --- D: repeated interactions with a selected (watchlist) address ------------------
    lab("SYN-WATCH-W", "SYN-CPTY-X", "SYN-CPTY-Y")
    for i in range(9):
        when = T0 + timedelta(days=1 + i, hours=8 + i % 5, minutes=rng.randint(0, 59))
        if i % 2 == 0:
            b.add(when, "SYN-WATCH-W", "SYN-CPTY-X", round(rng.uniform(0.8, 1.2), 6))
        else:
            b.add(when, "SYN-CPTY-X", "SYN-WATCH-W", round(rng.uniform(0.8, 1.2), 6))
    for i in range(3):  # below threshold on purpose
        b.add(T0 + timedelta(days=12 + i, hours=15), "SYN-WATCH-W", "SYN-CPTY-Y", round(rng.uniform(0.3, 0.6), 6))

    # --- E: benign look-alike batch payout (will trip the burst heuristic) ----------------
    lab("SYN-PAYROLL")
    salaries = [2100, 2400, 1800, 3100, 2750, 1950, 2200, 2600, 3300, 2000]
    for i, amount in enumerate(salaries):
        emp = f"SYN-EMPLOYEE-{i + 1:02d}"
        lab(emp)
        b.add(T0 + timedelta(days=20, hours=8, seconds=i * 35), "SYN-PAYROLL", emp, float(amount), "USDC")

    rows = sorted(b.rows, key=lambda r: (r["timestamp"], r["tx_hash"]))
    label_map = {name: address(name) for name in sorted(labels)}
    A = label_map
    manifest = [
        {
            "scenario": "fan-out burst", "heuristic": H_BURST, "expected_addresses": [A["SYN-FANOUT-SRC"]],
            "benign_lookalike": False,
            "note": "Synthetic: one address sends 14 similar transfers to 14 fresh addresses within ~6 minutes.",
        },
        {
            "scenario": "unusual value change", "heuristic": H_VALUE, "expected_addresses": [A["SYN-SPIKE-ACCT"]],
            "benign_lookalike": False,
            "note": "Synthetic: 38 ETH after eight transfers of 0.4-0.9 ETH.",
        },
        {
            "scenario": "rapid multi-hop chain", "heuristic": H_MULTIHOP,
            "expected_addresses": [A[h] for h in hops], "benign_lookalike": False,
            "note": "Synthetic: six forwards in ~18 minutes, each retaining ~98% of the value.",
        },
        {
            "scenario": "repeated interactions", "heuristic": H_REPEAT,
            "expected_addresses": [A["SYN-WATCH-W"], A["SYN-CPTY-X"]], "benign_lookalike": False,
            "note": "Synthetic: nine two-way transfers over nine days. Only reported when W is on the watchlist.",
        },
        {
            "scenario": "batch payout (benign look-alike)", "heuristic": H_BURST,
            "expected_addresses": [A["SYN-PAYROLL"]], "benign_lookalike": True,
            "note": "Synthetic: ten salary-like USDC transfers in ~5 minutes. Trips the burst rule by design, "
                    "illustrating false positives; the right reading is 'needs context', not 'suspicious'.",
        },
    ]
    return rows, label_map, manifest


def write_sample_files(directory: Path = SAMPLE_DIR) -> None:
    rows, labels, manifest = generate()
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / "synthetic_transactions.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with open(directory / "synthetic_address_labels.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["address", "label", "note"])
        for name, addr in labels.items():
            writer.writerow([addr, name, "Synthetic scenario role label; not a claim about any real wallet"])
    (directory / "synthetic_manifest.json").write_text(
        json.dumps({"dataset": SOURCE, "seed": SEED, "planted_patterns": manifest}, indent=2) + "\n",
        encoding="utf-8",
    )


def load_labels(path: Path = LABELS_CSV) -> dict[str, str]:
    """address -> synthetic role label (empty dict if the file is absent)."""
    if not Path(path).exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {row["address"]: row["label"] for row in csv.DictReader(fh)}


def load_manifest(path: Path = MANIFEST_JSON) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["planted_patterns"]


def check_manifest(indicators: list[Indicator], manifest: list[dict]) -> list[dict]:
    """For each planted pattern, report whether a matching indicator was produced."""
    results = []
    for entry in manifest:
        expected = set(entry["expected_addresses"])
        hits = [i for i in indicators if i.heuristic == entry["heuristic"] and expected <= set(i.addresses)]
        results.append(
            {
                "scenario": entry["scenario"],
                "heuristic": entry["heuristic"],
                "matched": bool(hits),
                "indicator_ids": [h.indicator_id for h in hits],
                "benign_lookalike": entry["benign_lookalike"],
            }
        )
    return results

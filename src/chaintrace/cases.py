"""SQLite case records: cases, imports, transactions, notes, watchlists, analysis runs."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .findings import Indicator
from .heuristics import HeuristicConfig
from .importer import ImportResult
from .schema import CANONICAL_COLUMNS, SORT_KEYS, EvidenceReferenceError, normalize_address

NOTE_KINDS = ("observation", "hypothesis")
HYPOTHESIS_STATUSES = ("open", "supported", "refuted", "inconclusive")
CONFIDENCE_LEVELS = ("low", "medium", "high")
MAX_TEXT = 10_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, investigator TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS imports(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL, sha256 TEXT NOT NULL,
    valid_rows INTEGER NOT NULL, rejected_rows INTEGER NOT NULL,
    inserted_rows INTEGER NOT NULL, imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transactions(
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    evidence_ref TEXT NOT NULL,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    tx_hash TEXT NOT NULL, transfer_index INTEGER NOT NULL, block_number INTEGER NOT NULL,
    timestamp TEXT NOT NULL, from_address TEXT NOT NULL, to_address TEXT NOT NULL,
    asset TEXT NOT NULL, amount REAL NOT NULL, amount_raw TEXT NOT NULL, data_source TEXT NOT NULL,
    PRIMARY KEY(case_id, evidence_ref));
CREATE INDEX IF NOT EXISTS idx_tx_from ON transactions(case_id, from_address);
CREATE INDEX IF NOT EXISTS idx_tx_to ON transactions(case_id, to_address);
CREATE TABLE IF NOT EXISTS notes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('observation','hypothesis')),
    text TEXT NOT NULL, evidence_refs TEXT NOT NULL, author TEXT NOT NULL,
    confidence TEXT, status TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watchlist(
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    address TEXT NOT NULL, PRIMARY KEY(case_id, address));
CREATE TABLE IF NOT EXISTS analysis_runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    run_at TEXT NOT NULL, dataset_sha256 TEXT NOT NULL,
    config_json TEXT NOT NULL, watchlist_json TEXT NOT NULL, indicators_json TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_text(value: str, field: str, required: bool = True) -> str:
    text = (value or "").strip()
    if required and not text:
        raise ValueError(f"{field} must not be empty")
    if len(text) > MAX_TEXT:
        raise ValueError(f"{field} exceeds {MAX_TEXT} characters")
    return text


class CaseStore:
    """Thin SQLite wrapper. Parameterised queries only; safe to share across threads."""

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._memory = sqlite3.connect(":memory:", check_same_thread=False) if self.path == ":memory:" else None
        if self._memory is None:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._tx() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _tx(self):
        conn = self._memory or sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if self._memory is None:
                conn.close()

    # ---------------------------------------------------------------- cases
    def create_case(self, name: str, investigator: str, description: str = "") -> int:
        name = _clean_text(name, "case name")
        investigator = _clean_text(investigator, "investigator")
        description = _clean_text(description, "description", required=False)
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT INTO cases(name, investigator, description, created_at) VALUES(?,?,?,?)",
                (name, investigator, description, _now()),
            )
            return int(cur.lastrowid)

    def get_case(self, case_id: int) -> dict:
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise KeyError(f"case {case_id} not found")
        return dict(row)

    def list_cases(self) -> list[dict]:
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM transactions t WHERE t.case_id=c.id) AS transfer_count "
                "FROM cases c ORDER BY c.id"
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------- imports
    def add_import(self, case_id: int, result: ImportResult) -> dict:
        """Store validated rows. Re-importing the same evidence is idempotent."""
        self.get_case(case_id)
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT INTO imports(case_id, source_name, sha256, valid_rows, rejected_rows, inserted_rows, imported_at)"
                " VALUES(?,?,?,?,?,0,?)",
                (case_id, result.source_name, result.sha256, len(result.valid), len(result.rejected), _now()),
            )
            import_id = int(cur.lastrowid)
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO transactions(case_id, evidence_ref, import_id, tx_hash, transfer_index,"
                " block_number, timestamp, from_address, to_address, asset, amount, amount_raw, data_source)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (case_id, r.evidence_ref, import_id, r.tx_hash, int(r.transfer_index), int(r.block_number),
                     r.timestamp.isoformat(), r.from_address, r.to_address, r.asset, float(r.amount),
                     r.amount_raw, r.data_source)
                    for r in result.valid.itertuples(index=False)
                ],
            )
            inserted = conn.total_changes - before
            conn.execute("UPDATE imports SET inserted_rows=? WHERE id=?", (inserted, import_id))
        return {
            "import_id": import_id,
            "valid_rows": len(result.valid),
            "rejected_rows": len(result.rejected),
            "inserted_rows": inserted,
            "already_present": len(result.valid) - inserted,
        }

    def import_log(self, case_id: int) -> list[dict]:
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT id, source_name, sha256, valid_rows, rejected_rows, inserted_rows, imported_at "
                "FROM imports WHERE case_id=? ORDER BY id",
                (case_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def load_transactions(self, case_id: int) -> pd.DataFrame:
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT evidence_ref, tx_hash, transfer_index, block_number, timestamp, from_address, to_address,"
                " asset, amount, amount_raw, data_source FROM transactions WHERE case_id=?",
                (case_id,),
            ).fetchall()
        df = pd.DataFrame([tuple(r) for r in rows], columns=list(CANONICAL_COLUMNS))
        if df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
        for col in ("transfer_index", "block_number"):
            df[col] = df[col].astype("int64")
        df["amount"] = df["amount"].astype("float64")
        return df.sort_values(SORT_KEYS, kind="mergesort").reset_index(drop=True)

    # ---------------------------------------------------------------- notes
    def _unresolved(self, conn, case_id: int, refs: list[str]) -> list[str]:
        found: set[str] = set()
        for start in range(0, len(refs), 500):
            chunk = refs[start : start + 500]
            marks = ",".join("?" * len(chunk))
            for row in conn.execute(
                f"SELECT evidence_ref FROM transactions WHERE case_id=? AND evidence_ref IN ({marks})",
                [case_id, *chunk],
            ):
                found.add(row[0])
        return sorted(set(refs) - found)

    def add_note(
        self,
        case_id: int,
        kind: str,
        text: str,
        author: str,
        evidence_refs: list[str] | None = None,
        confidence: str | None = None,
        status: str | None = None,
    ) -> int:
        """Record an investigator observation or hypothesis. Evidence refs must resolve."""
        self.get_case(case_id)
        if kind not in NOTE_KINDS:
            raise ValueError(f"kind must be one of {NOTE_KINDS}")
        text = _clean_text(text, "note text")
        author = _clean_text(author, "author")
        refs = sorted({r.strip().lower() for r in (evidence_refs or []) if r and r.strip()})
        if kind == "hypothesis":
            confidence = confidence or "low"
            status = status or "open"
            if confidence not in CONFIDENCE_LEVELS:
                raise ValueError(f"confidence must be one of {CONFIDENCE_LEVELS}")
            if status not in HYPOTHESIS_STATUSES:
                raise ValueError(f"status must be one of {HYPOTHESIS_STATUSES}")
        else:
            confidence = status = None
        with self._tx() as conn:
            missing = self._unresolved(conn, case_id, refs)
            if missing:
                raise EvidenceReferenceError(missing)
            now = _now()
            cur = conn.execute(
                "INSERT INTO notes(case_id, kind, text, evidence_refs, author, confidence, status, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (case_id, kind, text, json.dumps(refs), author, confidence, status, now, now),
            )
            return int(cur.lastrowid)

    def list_notes(self, case_id: int, kind: str | None = None) -> list[dict]:
        query = "SELECT * FROM notes WHERE case_id=?" + (" AND kind=?" if kind else "") + " ORDER BY id"
        params = (case_id, kind) if kind else (case_id,)
        with self._tx() as conn:
            rows = conn.execute(query, params).fetchall()
        notes = []
        for r in rows:
            d = dict(r)
            d["evidence_refs"] = json.loads(d["evidence_refs"])
            notes.append(d)
        return notes

    def update_hypothesis(self, note_id: int, status: str | None = None, confidence: str | None = None) -> None:
        if status is not None and status not in HYPOTHESIS_STATUSES:
            raise ValueError(f"status must be one of {HYPOTHESIS_STATUSES}")
        if confidence is not None and confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"confidence must be one of {CONFIDENCE_LEVELS}")
        with self._tx() as conn:
            row = conn.execute("SELECT kind FROM notes WHERE id=?", (note_id,)).fetchone()
            if row is None:
                raise KeyError(f"note {note_id} not found")
            if row["kind"] != "hypothesis":
                raise ValueError("only hypotheses carry a status and confidence")
            conn.execute(
                "UPDATE notes SET status=COALESCE(?, status), confidence=COALESCE(?, confidence), updated_at=? WHERE id=?",
                (status, confidence, _now(), note_id),
            )

    # ------------------------------------------------------------ watchlist
    def set_watchlist(self, case_id: int, addresses: list[str]) -> list[str]:
        self.get_case(case_id)
        cleaned = sorted({normalize_address(a) for a in addresses if a and str(a).strip()})
        with self._tx() as conn:
            conn.execute("DELETE FROM watchlist WHERE case_id=?", (case_id,))
            conn.executemany("INSERT INTO watchlist(case_id, address) VALUES(?,?)", [(case_id, a) for a in cleaned])
        return cleaned

    def get_watchlist(self, case_id: int) -> list[str]:
        with self._tx() as conn:
            rows = conn.execute("SELECT address FROM watchlist WHERE case_id=? ORDER BY address", (case_id,)).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------- analysis runs
    def save_analysis_run(
        self, case_id: int, dataset_sha256: str, config: HeuristicConfig, watchlist: list[str], indicators: list[Indicator]
    ) -> int:
        self.get_case(case_id)
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT INTO analysis_runs(case_id, run_at, dataset_sha256, config_json, watchlist_json, indicators_json)"
                " VALUES(?,?,?,?,?,?)",
                (case_id, _now(), dataset_sha256, json.dumps(config.to_dict(), sort_keys=True),
                 json.dumps(sorted(watchlist)), json.dumps([i.to_dict() for i in indicators])),
            )
            return int(cur.lastrowid)

    def latest_analysis_run(self, case_id: int) -> dict | None:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_runs WHERE case_id=? ORDER BY id DESC LIMIT 1", (case_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["id"],
            "run_at": row["run_at"],
            "dataset_sha256": row["dataset_sha256"],
            "config": HeuristicConfig.from_dict(json.loads(row["config_json"])),
            "watchlist": json.loads(row["watchlist_json"]),
            "indicators": [Indicator.from_dict(d) for d in json.loads(row["indicators_json"])],
        }

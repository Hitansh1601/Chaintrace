"""Evidence-preserving report builder (JSON, CSV, HTML) and reproducibility verification."""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import platform
from datetime import datetime, timezone

import networkx
import pandas as pd

from . import __version__
from .findings import Indicator, derive_address_fact, derive_dataset_fact
from .heuristics import HeuristicConfig, run_all
from .schema import (
    CANONICAL_COLUMNS,
    DISCLAIMERS,
    SCHEMA_VERSION,
    EvidenceReferenceError,
    StatementKind,
)

MAX_ADDRESS_FACTS = 40
FINDINGS_FIELDS = ["kind", "id", "title", "priority_or_status", "confidence", "addresses", "evidence_refs", "explanation", "caveats"]


def dataset_fingerprint(df: pd.DataFrame) -> str:
    """SHA-256 over the canonical, sorted transfer table (independent of import files)."""
    d = df[list(CANONICAL_COLUMNS)].sort_values("evidence_ref", kind="mergesort").copy()
    d["timestamp"] = d["timestamp"].map(lambda t: t.isoformat())
    d["amount"] = d["amount"].map(lambda x: repr(float(x)))
    return hashlib.sha256(d.to_csv(index=False, lineterminator="\n").encode("utf-8")).hexdigest()


def _tx_record(row) -> dict:
    return {
        "evidence_ref": row.evidence_ref,
        "tx_hash": row.tx_hash,
        "transfer_index": int(row.transfer_index),
        "block_number": int(row.block_number),
        "timestamp": row.timestamp.isoformat(),
        "from_address": row.from_address,
        "to_address": row.to_address,
        "asset": row.asset,
        "amount": row.amount_raw,
        "data_source": row.data_source,
    }


def _content_hash(report: dict) -> str:
    body = {k: v for k, v in report.items() if k not in ("report_id", "generated_at_utc", "environment")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def build_report(
    *,
    case: dict,
    transactions: pd.DataFrame,
    indicators: list[Indicator],
    notes: list[dict],
    config: HeuristicConfig,
    watchlist: list[str],
    import_log: list[dict],
    generated_at: str | None = None,
) -> dict:
    """Assemble the report. Raises EvidenceReferenceError if any reference is dangling."""
    known = set(transactions["evidence_ref"])
    cited: dict[str, set[str]] = {}

    def cite(refs, owner: str) -> None:
        for ref in refs:
            cited.setdefault(ref, set()).add(owner)

    for ind in indicators:
        cite(ind.evidence_refs, ind.indicator_id)
    note_dicts = []
    for n in notes:
        nid = f"NOTE-{n['id']:04d}"
        cite(n["evidence_refs"], nid)
        note_dicts.append(
            {
                "note_id": nid,
                "kind": StatementKind.HYPOTHESIS.value if n["kind"] == "hypothesis" else "investigator_observation",
                "text": n["text"],
                "author": n["author"],
                "confidence": n["confidence"],
                "status": n["status"],
                "evidence_refs": list(n["evidence_refs"]),
                "created_at": n["created_at"],
                "updated_at": n["updated_at"],
            }
        )

    facts = [derive_dataset_fact(transactions)]
    involved = sorted({a for ind in indicators for a in ind.addresses} | set(watchlist))
    for addr in involved[:MAX_ADDRESS_FACTS]:
        fact = derive_address_fact(transactions, addr)
        if fact:
            facts.append(fact)
    for f in facts:
        cite(f.evidence_refs, f.fact_id)

    unresolved = sorted(set(cited) - known)
    if unresolved:
        raise EvidenceReferenceError(unresolved)

    by_ref = transactions.set_index("evidence_ref", drop=False)
    evidence = []
    for ref in sorted(cited):
        rec = _tx_record(next(by_ref.loc[[ref]].itertuples(index=False)))
        rec["referenced_by"] = sorted(cited[ref])
        evidence.append(rec)

    report = {
        "report_schema_version": SCHEMA_VERSION,
        "tool": {"name": "ChainTrace", "version": __version__},
        "case": {k: case[k] for k in ("id", "name", "investigator", "description", "created_at")},
        "disclaimers": list(DISCLAIMERS),
        "reproducibility": {
            "dataset_sha256": dataset_fingerprint(transactions),
            "transfer_count": int(len(transactions)),
            "heuristic_config": config.to_dict(),
            "watchlist": sorted(watchlist),
            "import_log": import_log,
            "how_to_reproduce": (
                "Load the same transfers, run the heuristics with heuristic_config and watchlist, and "
                "compare indicator_id values. IDs are deterministic. Use `chaintrace verify` to automate this."
            ),
        },
        "observed_facts": [f.to_dict() for f in facts],
        "derived_indicators": [i.to_dict() for i in indicators],
        "investigator_observations": [n for n in note_dicts if n["kind"] == "investigator_observation"],
        "investigator_hypotheses": [n for n in note_dicts if n["kind"] == StatementKind.HYPOTHESIS.value],
        "evidence": evidence,
    }
    report["report_id"] = _content_hash(report)[:16]
    report["generated_at_utc"] = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["environment"] = {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "networkx": networkx.__version__,
    }
    return report


def verify_report(report: dict, transactions: pd.DataFrame) -> dict:
    """Re-derive a report's checks from the transfers: fingerprint, indicators, references."""
    repro = report["reproducibility"]
    checks = {
        "dataset_fingerprint_matches": repro["dataset_sha256"] == dataset_fingerprint(transactions),
        "report_id_matches_content": report["report_id"] == _content_hash(report)[:16],
    }
    cfg = HeuristicConfig.from_dict(repro["heuristic_config"])
    rerun = {i.indicator_id for i in run_all(transactions, cfg, repro["watchlist"])}
    recorded = {i["indicator_id"] for i in report["derived_indicators"]}
    checks["indicators_reproduce"] = rerun == recorded
    known = set(transactions["evidence_ref"])
    checks["all_evidence_refs_resolve"] = all(e["evidence_ref"] in known for e in report["evidence"])
    cited = {r for i in report["derived_indicators"] for r in i["evidence_refs"]}
    cited |= {r for sec in ("investigator_observations", "investigator_hypotheses") for n in report[sec] for r in n["evidence_refs"]}
    checks["every_citation_has_evidence_record"] = cited <= {e["evidence_ref"] for e in report["evidence"]}
    return {"ok": all(checks.values()), "checks": checks}


# ------------------------------------------------------------------------- renderers
def render_json(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection in analyst- or data-supplied text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _csv_text(fields: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _csv_safe(row.get(k, "")) for k in fields})
    return buf.getvalue()


def findings_csv(report: dict) -> str:
    rows = []
    for f in report["observed_facts"]:
        rows.append({"kind": f["kind"], "id": f["fact_id"], "title": f["statement"],
                     "addresses": ";".join(f["addresses"]), "evidence_refs": ";".join(f["evidence_refs"])})
    for i in report["derived_indicators"]:
        rows.append({"kind": i["kind"], "id": i["indicator_id"], "title": i["title"],
                     "priority_or_status": i["priority"], "addresses": ";".join(i["addresses"]),
                     "evidence_refs": ";".join(i["evidence_refs"]), "explanation": i["explanation"],
                     "caveats": i["caveats"]})
    for sec in ("investigator_observations", "investigator_hypotheses"):
        for n in report[sec]:
            rows.append({"kind": n["kind"], "id": n["note_id"], "title": n["text"],
                         "priority_or_status": n["status"] or "", "confidence": n["confidence"] or "",
                         "evidence_refs": ";".join(n["evidence_refs"])})
    return _csv_text(FINDINGS_FIELDS, rows)


def evidence_csv(report: dict) -> str:
    fields = ["evidence_ref", "tx_hash", "transfer_index", "block_number", "timestamp", "from_address",
              "to_address", "asset", "amount", "data_source", "referenced_by"]
    rows = [{**e, "referenced_by": ";".join(e["referenced_by"])} for e in report["evidence"]]
    return _csv_text(fields, rows)


def _anchor(ref: str) -> str:
    return "ev-" + hashlib.sha1(ref.encode()).hexdigest()[:12]


def render_html(report: dict) -> str:
    esc = html.escape

    def ref_links(refs, limit=12) -> str:
        shown = "".join(f'<li><a href="#{_anchor(r)}"><code>{esc(r)}</code></a></li>' for r in refs[:limit])
        more = f"<li>… and {len(refs) - limit} more (see evidence appendix)</li>" if len(refs) > limit else ""
        return f'<ul class="refs">{shown}{more}</ul>' if refs else "<p class='muted'>No transaction-level references (dataset-level statement).</p>"

    repro = report["reproducibility"]
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>ChainTrace report {esc(report['report_id'])}</title>",
        "<style>body{font:15px/1.5 system-ui,Segoe UI,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#1b1f23}"
        "h1,h2,h3{line-height:1.2}code{font-size:.85em;word-break:break-all}.banner{background:#fff4ce;border:1px solid #e0c36a;"
        "padding:.8rem 1rem;border-radius:6px}.card{border:1px solid #d0d7de;border-radius:6px;padding:.8rem 1rem;margin:.8rem 0}"
        ".muted{color:#57606a}.tag{display:inline-block;padding:0 .5rem;border-radius:1rem;background:#ddf4ff;font-size:.8em}"
        "table{border-collapse:collapse;width:100%;font-size:.8em}td,th{border:1px solid #d0d7de;padding:.25rem .4rem;text-align:left;vertical-align:top}"
        ".refs{columns:2;font-size:.85em}@media print{.banner{break-inside:avoid}}</style></head><body>",
        f"<h1>ChainTrace investigation report</h1><p class='muted'>Report ID <code>{esc(report['report_id'])}</code> · generated "
        f"{esc(report['generated_at_utc'])} · ChainTrace {esc(report['tool']['version'])}</p>",
        "<div class='banner'><strong>Read before relying on this report</strong><ul>"
        + "".join(f"<li>{esc(d)}</li>" for d in report["disclaimers"])
        + "</ul></div>",
        f"<h2>Case</h2><p><strong>{esc(report['case']['name'])}</strong> (#{esc(str(report['case']['id']))}) · investigator: "
        f"{esc(report['case']['investigator'])} · opened {esc(report['case']['created_at'])}</p><p>{esc(report['case']['description'])}</p>",
        "<h2>Reproducibility</h2><table>"
        f"<tr><th>Dataset SHA-256</th><td><code>{esc(repro['dataset_sha256'])}</code></td></tr>"
        f"<tr><th>Transfers</th><td>{repro['transfer_count']}</td></tr>"
        f"<tr><th>Heuristic parameters</th><td><code>{esc(json.dumps(repro['heuristic_config'], sort_keys=True))}</code></td></tr>"
        f"<tr><th>Watchlist</th><td><code>{esc(', '.join(repro['watchlist']) or 'none')}</code></td></tr></table>",
        "<h2>1. Observed facts</h2><p class='muted'>Computed directly from loaded transfers; no inference.</p>",
    ]
    for f in report["observed_facts"]:
        parts.append(f"<div class='card'><span class='tag'>observed fact</span> <code>{esc(f['fact_id'])}</code><p>{esc(f['statement'])}</p>{ref_links(f['evidence_refs'], 6)}</div>")
    parts.append("<h2>2. Derived indicators</h2><p class='muted'>Heuristic leads. Each lists its rule, why it fired, caveats, and supporting transfers.</p>")
    if not report["derived_indicators"]:
        parts.append("<p>No indicators were produced.</p>")
    for i in report["derived_indicators"]:
        parts.append(
            f"<div class='card'><span class='tag'>derived indicator</span> <code>{esc(i['indicator_id'])}</code> · "
            f"review priority: <strong>{esc(i['priority'])}</strong><h3>{esc(i['title'])}</h3>"
            f"<p><strong>Why it fired:</strong> {esc(i['explanation'])}</p><p><strong>Caveats:</strong> {esc(i['caveats'])}</p>"
            f"<p><strong>Addresses:</strong> <code>{esc(', '.join(i['addresses']))}</code></p>"
            f"<p><strong>Supporting transfers ({len(i['evidence_refs'])}):</strong></p>{ref_links(i['evidence_refs'])}</div>"
        )
    parts.append("<h2>3. Investigator observations</h2><p class='muted'>Recorded by the analyst, tied to evidence.</p>")
    for n in report["investigator_observations"] or []:
        parts.append(f"<div class='card'><span class='tag'>observation</span> <code>{esc(n['note_id'])}</code> · {esc(n['author'])}<p>{esc(n['text'])}</p>{ref_links(n['evidence_refs'])}</div>")
    if not report["investigator_observations"]:
        parts.append("<p>None recorded.</p>")
    parts.append("<h2>4. Investigator hypotheses</h2><p class='muted'>The analyst's working theories. Unverified unless corroborated.</p>")
    for n in report["investigator_hypotheses"]:
        parts.append(
            f"<div class='card'><span class='tag'>hypothesis</span> <code>{esc(n['note_id'])}</code> · {esc(n['author'])} · "
            f"status: {esc(str(n['status']))} · confidence: {esc(str(n['confidence']))}<p>{esc(n['text'])}</p>{ref_links(n['evidence_refs'])}</div>"
        )
    if not report["investigator_hypotheses"]:
        parts.append("<p>None recorded.</p>")
    parts.append(f"<h2>Evidence appendix ({len(report['evidence'])} transfers)</h2><table><tr><th>Ref</th><th>Block</th><th>Time (UTC)</th>"
                 "<th>From</th><th>To</th><th>Amount</th><th>Source</th><th>Cited by</th></tr>")
    for e in report["evidence"]:
        parts.append(
            f"<tr id='{_anchor(e['evidence_ref'])}'><td><code>{esc(e['evidence_ref'])}</code></td><td>{e['block_number']}</td>"
            f"<td>{esc(e['timestamp'])}</td><td><code>{esc(e['from_address'])}</code></td><td><code>{esc(e['to_address'])}</code></td>"
            f"<td>{esc(e['amount'])} {esc(e['asset'])}</td><td>{esc(e['data_source'])}</td><td>{esc(', '.join(e['referenced_by']))}</td></tr>"
        )
    parts.append("</table></body></html>")
    return "".join(parts)

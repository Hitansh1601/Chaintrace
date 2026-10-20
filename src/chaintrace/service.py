"""Orchestration shared by the CLI and the Streamlit app."""
from __future__ import annotations

import json
from pathlib import Path

from .adapters import CsvAdapter
from .cases import CaseStore
from .findings import H_BURST, Indicator
from .heuristics import HeuristicConfig, run_all
from .report import (
    build_report,
    dataset_fingerprint,
    evidence_csv,
    findings_csv,
    render_html,
    render_json,
    verify_report,
)
from .schema import StaleAnalysisError
from .synthetic import SAMPLE_CSV, address, check_manifest, load_manifest


def analyze_case(
    store: CaseStore, case_id: int, config: HeuristicConfig | None = None, watchlist: list[str] | None = None
) -> list[Indicator]:
    """Run all heuristics over the case's transfers and persist the run."""
    cfg = (config or HeuristicConfig()).validate()
    df = store.load_transactions(case_id)
    if df.empty:
        raise ValueError("case has no transactions to analyse")
    selected = store.set_watchlist(case_id, watchlist if watchlist is not None else store.get_watchlist(case_id))
    indicators = run_all(df, cfg, selected)
    store.save_analysis_run(case_id, dataset_fingerprint(df), cfg, selected, indicators)
    return indicators


def run_status(store: CaseStore, case_id: int) -> tuple[dict | None, bool]:
    """(latest run, is_stale). Stale means the transfers changed after the run."""
    run = store.latest_analysis_run(case_id)
    if run is None:
        return None, False
    return run, run["dataset_sha256"] != dataset_fingerprint(store.load_transactions(case_id))


def build_case_report(store: CaseStore, case_id: int, generated_at: str | None = None) -> dict:
    run, stale = run_status(store, case_id)
    if run is None:
        raise ValueError("no analysis run found: run the heuristics before exporting a report")
    if stale:
        raise StaleAnalysisError("transactions changed since the last analysis run; re-run the analysis")
    return build_report(
        case=store.get_case(case_id),
        transactions=store.load_transactions(case_id),
        indicators=run["indicators"],
        notes=store.list_notes(case_id),
        config=run["config"],
        watchlist=run["watchlist"],
        import_log=store.import_log(case_id),
        generated_at=generated_at,
    )


def export_case(store: CaseStore, case_id: int, out_dir: str | Path, generated_at: str | None = None) -> dict[str, Path]:
    report = build_case_report(store, case_id, generated_at)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "json": (out / "report.json", render_json(report)),
        "html": (out / "report.html", render_html(report)),
        "findings_csv": (out / "findings.csv", findings_csv(report)),
        "evidence_csv": (out / "evidence_transactions.csv", evidence_csv(report)),
    }
    for path, content in files.values():
        path.write_text(content, encoding="utf-8", newline="\n")
    return {k: p for k, (p, _) in files.items()}


def verify_exported_report(store: CaseStore, case_id: int, report_path: str | Path) -> dict:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    return verify_report(report, store.load_transactions(case_id))


def run_demo(db_path: str | Path, out_dir: str | Path, generated_at: str | None = None) -> dict:
    """Complete synthetic case, end to end: import -> analyse -> notes -> export -> verify."""
    store = CaseStore(db_path)
    case_id = store.create_case(
        "Demo: synthetic transfer patterns",
        "ChainTrace Demo Analyst",
        "SYNTHETIC DATA ONLY. Demonstrates the workflow on invented transfers; no real wallets or people.",
    )
    imp = store.add_import(case_id, CsvAdapter(SAMPLE_CSV).load())
    watch = address("SYN-WATCH-W")
    indicators = analyze_case(store, case_id, HeuristicConfig(), [watch])

    def first(heuristic: str, label: str) -> Indicator:
        return next(i for i in indicators if i.heuristic == heuristic and address(label) in i.addresses)

    fan, pay = first(H_BURST, "SYN-FANOUT-SRC"), first(H_BURST, "SYN-PAYROLL")
    store.add_note(
        case_id, "observation",
        "Synthetic scenario: the fan-out source received 24 ETH from a single funder about 40 minutes before "
        "sending 14 similar ~1.7 ETH transfers to 14 different addresses.",
        "ChainTrace Demo Analyst", [fan.evidence_refs[0], fan.evidence_refs[-1]],
    )
    store.add_note(
        case_id, "hypothesis",
        "Working hypothesis (unverified): funds are being split across fresh addresses to stay under per-address "
        "monitoring thresholds. Alternative: an ordinary batch payout. Next step: look for how the recipients "
        "later move funds and whether they appear in any independently sourced case material.",
        "ChainTrace Demo Analyst", list(fan.evidence_refs[:3]), confidence="low",
    )
    store.add_note(
        case_id, "hypothesis",
        "The payroll-style burst is most plausibly a legitimate batch payout (round-ish salary amounts, one "
        "sender, evenly spaced). Recorded to show how a benign explanation is documented next to an indicator.",
        "ChainTrace Demo Analyst", list(pay.evidence_refs[:3]), confidence="medium",
    )
    paths = export_case(store, case_id, out_dir, generated_at)
    verification = verify_exported_report(store, case_id, paths["json"])
    return {
        "case_id": case_id,
        "import": imp,
        "indicators": indicators,
        "manifest_check": check_manifest(indicators, load_manifest()),
        "paths": paths,
        "verification": verification,
    }

"""Command-line entry points: demo, export, verify."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import service
from .cases import CaseStore
from .schema import EvidenceReferenceError, StaleAnalysisError


def _cmd_demo(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db = Path(args.db) if args.db else out / "demo_case.db"
    if not args.db and db.exists():
        db.unlink()  # the default demo database is disposable
    result = service.run_demo(db, out)
    print("ChainTrace demo (SYNTHETIC data)")
    print(f"  case #{result['case_id']}: {result['import']['inserted_rows']} transfers imported "
          f"({result['import']['rejected_rows']} rejected)")
    print(f"  {len(result['indicators'])} indicators:")
    for ind in result["indicators"]:
        print(f"    [{ind.priority:6}] {ind.indicator_id}  {ind.title}")
    print("  planted-pattern check:")
    for m in result["manifest_check"]:
        flag = "found" if m["matched"] else "MISSING"
        extra = "  (benign look-alike)" if m["benign_lookalike"] else ""
        print(f"    {flag:7} {m['scenario']}{extra}")
    print(f"  reproducibility check: {'PASS' if result['verification']['ok'] else 'FAIL'}")
    for name, path in result["paths"].items():
        print(f"  wrote {name}: {path}")
    ok = result["verification"]["ok"] and all(m["matched"] for m in result["manifest_check"])
    return 0 if ok else 1


def _cmd_export(args) -> int:
    store = CaseStore(args.db)
    try:
        paths = service.export_case(store, args.case, args.out)
    except (ValueError, KeyError, StaleAnalysisError, EvidenceReferenceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for name, path in paths.items():
        print(f"wrote {name}: {path}")
    return 0


def _cmd_verify(args) -> int:
    store = CaseStore(args.db)
    try:
        result = service.verify_exported_report(store, args.case, args.report)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for name, ok in result["checks"].items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print("OVERALL:", "PASS" if result["ok"] else "FAIL")
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chaintrace", description="Read-only blockchain investigation toolkit")
    sub = parser.add_subparsers(dest="cmd", required=True)
    demo = sub.add_parser("demo", help="run the full synthetic sample case end to end")
    demo.add_argument("--db", help="SQLite path (default: <out>/demo_case.db, recreated each run)")
    demo.add_argument("--out", default="out/demo", help="output directory")
    demo.set_defaults(func=_cmd_demo)
    exp = sub.add_parser("export", help="export the latest analysis of a case")
    exp.add_argument("--db", required=True)
    exp.add_argument("--case", type=int, required=True)
    exp.add_argument("--out", default="out/export")
    exp.set_defaults(func=_cmd_export)
    ver = sub.add_parser("verify", help="re-derive a JSON report's checks from the case data")
    ver.add_argument("report")
    ver.add_argument("--db", required=True)
    ver.add_argument("--case", type=int, required=True)
    ver.set_defaults(func=_cmd_verify)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

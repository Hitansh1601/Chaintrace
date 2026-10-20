"""ChainTrace Streamlit UI. Run: streamlit run src/chaintrace/app.py"""
from __future__ import annotations

import io
import os
import re
import sqlite3
import zipfile

import pandas as pd
import streamlit as st

from chaintrace import __version__, service
from chaintrace.adapters import BlockscoutStyleAdapter, CsvAdapter, ProviderError
from chaintrace.cases import HYPOTHESIS_STATUSES, CONFIDENCE_LEVELS, CaseStore
from chaintrace.findings import HEURISTIC_NAMES, derive_address_fact, derive_dataset_fact, short_addr
from chaintrace.graph import build_graph, filter_transactions, neighborhood
from chaintrace.heuristics import HeuristicConfig
from chaintrace.report import evidence_csv, findings_csv, render_html, render_json
from chaintrace.schema import DISCLAIMERS, EvidenceReferenceError, SchemaError, StaleAnalysisError
from chaintrace.synthetic import SAMPLE_CSV, address, load_labels
from chaintrace.timeline import build_timeline
from chaintrace.viz import graph_figure, node_label, timeline_figure


def show_fig(fig) -> None:
    try:
        st.plotly_chart(fig, width="stretch")
    except TypeError:  # older Streamlit
        st.plotly_chart(fig, use_container_width=True)


@st.cache_resource
def get_store(path: str) -> CaseStore:
    return CaseStore(path)


def sidebar_case(store: CaseStore):
    cases = store.list_cases()
    with st.sidebar.expander("Create case", expanded=not cases):
        with st.form("new_case"):
            name = st.text_input("Case name")
            investigator = st.text_input("Investigator")
            description = st.text_area("Description")
            if st.form_submit_button("Create case"):
                try:
                    st.session_state["case_id"] = store.create_case(name, investigator, description)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    if not cases:
        return None
    ids = [c["id"] for c in cases]
    names = {c["id"]: c["name"] for c in cases}
    current = st.session_state.get("case_id", ids[-1])
    chosen = st.sidebar.selectbox("Active case", ids, index=ids.index(current) if current in ids else len(ids) - 1,
                                  format_func=lambda i: f"#{i} · {names[i]}")
    st.session_state["case_id"] = chosen
    return chosen


def _show_import(store, case_id, result, key: str) -> None:
    st.sidebar.write(f"**{len(result.valid)}** valid rows · **{len(result.rejected)}** rejected")
    if len(result.rejected):
        with st.sidebar.expander("Rejected rows and reasons"):
            st.dataframe(result.rejected, hide_index=True)
    if len(result.valid) and st.sidebar.button(f"Import {len(result.valid)} valid rows", key=f"imp_{key}"):
        info = store.add_import(case_id, result)
        st.sidebar.success(f"Imported {info['inserted_rows']} new transfers ({info['already_present']} already present).")
        st.rerun()


def sidebar_data(store: CaseStore, case_id: int) -> None:
    st.sidebar.subheader("Data")
    if st.sidebar.button("Load synthetic demo dataset"):
        info = store.add_import(case_id, CsvAdapter(SAMPLE_CSV).load())
        st.sidebar.success(f"Imported {info['inserted_rows']} synthetic transfers.")
        st.rerun()
    upload = st.sidebar.file_uploader("Import transaction CSV", type=["csv"])
    if upload is not None:
        try:
            result = CsvAdapter(upload.getvalue(), source_name=upload.name).load()
        except SchemaError as exc:
            st.sidebar.error(f"Cannot import: {exc}")
        else:
            _show_import(store, case_id, result, f"csv_{upload.name}")
    with st.sidebar.expander("Optional: public provider (read-only)"):
        st.caption("Off by default. Makes HTTPS GET requests only; no API key, no signing. "
                   "Experimental: first page, native-coin transfers only.")
        if st.checkbox("Enable network access", key="prov_on"):
            base = st.text_input("Explorer base URL (Blockscout-style)", placeholder="https://…")
            addr = st.text_input("Address to fetch")
            limit = st.number_input("Max transfers", 1, 1000, 50)
            if st.button("Fetch"):
                try:
                    st.session_state["prov_result"] = BlockscoutStyleAdapter(base, addr, int(limit)).load()
                except (ValueError, ProviderError, SchemaError) as exc:
                    st.session_state.pop("prov_result", None)
                    st.error(str(exc))
            if "prov_result" in st.session_state:
                _show_import(store, case_id, st.session_state["prov_result"], "prov")


def tab_overview(df, labels, case_id, store):
    st.subheader("Observed facts")
    st.caption("Computed directly from the loaded rows. No inference.")
    fact = derive_dataset_fact(df)
    st.info(fact.statement)
    st.write("Import log")
    st.dataframe(pd.DataFrame(store.import_log(case_id)), hide_index=True)
    addrs = sorted(set(df.from_address) | set(df.to_address))
    pick = st.selectbox("Address profile", addrs, format_func=lambda a: node_label(a, labels), key="ov_addr")
    f = derive_address_fact(df, pick)
    if f:
        st.write(f.statement)
        st.caption(f"{len(f.evidence_refs)} supporting transfers")


def tab_graph(df, labels, indicators):
    addrs = sorted(set(df.from_address) | set(df.to_address))
    c1, c2, c3 = st.columns([2, 1, 1])
    q = c1.text_input("Search address or label", key="g_q").strip().lower()
    opts = [a for a in addrs if not q or q in a or q in labels.get(a, "").lower()][:500]
    none = "(none: show full filtered graph)"
    seed = c1.selectbox("Seed address", [none, *opts], format_func=lambda a: a if a == none else f"{labels.get(a, '')} {a}".strip())
    depth = c2.slider("Hop depth", 1, 6, 2)
    direction = c3.radio("Direction", ["both", "out", "in"], horizontal=True)
    f1, f2, f3 = st.columns(3)
    assets = f1.multiselect("Assets", sorted(df.asset.unique()), default=sorted(df.asset.unique()))
    tmin, tmax = df.timestamp.min().to_pydatetime(), df.timestamp.max().to_pydatetime()
    window = f2.slider("Time window (UTC)", tmin, tmax, (tmin, tmax)) if tmin < tmax else (tmin, tmax)
    lo = f3.number_input("Min amount", 0.0, value=0.0)
    hi = f3.number_input("Max amount (0 = no limit)", 0.0, value=0.0)
    try:
        fdf = filter_transactions(df, window[0], window[1], assets, lo or None, hi or None)
    except ValueError as exc:
        st.error(str(exc))
        return
    graph = build_graph(fdf)
    if seed != none:
        if seed not in graph:
            st.warning("Seed address has no transfers under the current filters.")
            return
        graph = neighborhood(graph, seed, depth, direction)
    st.caption(f"{graph.number_of_nodes()} addresses · {graph.number_of_edges()} edges · {len(fdf)} filtered transfers. "
               "Edges are observed transfers; proximity is not proof of identity, ownership or intent.")
    if graph.number_of_nodes() > 300:
        st.warning("Graph too large to draw; narrow the filters or pick a seed.")
    else:
        flagged = {a for i in indicators for a in i.addresses}
        show_fig(graph_figure(graph, None if seed == none else seed, flagged, labels))
    rows = [{"from": u, "to": v, "transfers": d["tx_count"], "totals": d["total_by_asset"],
             "first_seen": d["first_seen"], "last_seen": d["last_seen"]} for u, v, d in graph.edges(data=True)]
    with st.expander("Edge table"):
        st.dataframe(pd.DataFrame(rows), hide_index=True)


def tab_timeline(df, labels, indicators):
    addrs = sorted(set(df.from_address) | set(df.to_address))
    allv = "(all addresses)"
    sel = st.selectbox("Address", [allv, *addrs], format_func=lambda a: a if a == allv else node_label(a, labels), key="tl_addr")
    tl = build_timeline(df, None if sel == allv else sel, indicators)
    st.caption(f"{len(tl)} transfers, chronological. 'indicator_ids' lists indicators citing each transfer.")
    st.dataframe(tl.assign(timestamp=tl.timestamp.dt.strftime("%Y-%m-%d %H:%M:%S")), hide_index=True)
    show_fig(timeline_figure(tl, labels))
    st.download_button("Download timeline CSV", tl.to_csv(index=False), "timeline.csv", "text/csv")


def tab_indicators(store, case_id, df, labels, run, stale):
    st.warning("Indicators are heuristic leads for investigation, not findings. Each lists benign explanations to rule out.")
    defaults = run["config"] if run else HeuristicConfig()
    with st.expander("Heuristic parameters", expanded=False):
        cols = st.columns(3)
        vals = {}
        for k, (name, v) in enumerate(defaults.to_dict().items()):
            step = 1 if isinstance(v, int) else 0.1
            vals[name] = cols[k % 3].number_input(name, min_value=step if name != "multihop_min_retention" else 0.1, value=v, step=step, key=f"cfg_{name}")
    addrs = sorted(set(df.from_address) | set(df.to_address))
    watch = st.multiselect("Watchlist (for repeated-interaction heuristic)", addrs,
                           default=[a for a in store.get_watchlist(case_id) if a in addrs],
                           format_func=lambda a: node_label(a, labels))
    if st.button("Run analysis", type="primary"):
        try:
            cfg = HeuristicConfig(**{k: (int(v) if isinstance(defaults.to_dict()[k], int) else float(v)) for k, v in vals.items()})
            service.analyze_case(store, case_id, cfg, watch)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if run is None:
        st.info("No analysis yet. Choose parameters and run the analysis.")
        return
    if stale:
        st.error("Transactions changed since this analysis. Re-run it before exporting.")
    inds = run["indicators"]
    f1, f2 = st.columns(2)
    hs = f1.multiselect("Heuristic", HEURISTIC_NAMES, default=list(HEURISTIC_NAMES))
    pr = f2.multiselect("Priority", ["high", "medium", "low"], default=["high", "medium", "low"])
    shown = [i for i in inds if i.heuristic in hs and i.priority in pr]
    st.write(f"{len(shown)} of {len(inds)} indicators · run at {run['run_at']}")
    for ind in shown:
        with st.expander(f"[{ind.priority}] {ind.indicator_id} · {ind.title}"):
            st.markdown(f"**Why it fired:** {ind.explanation}")
            st.markdown(f"**Caveats:** {ind.caveats}")
            st.json({"parameters": ind.parameters, "metrics": ind.metrics}, expanded=False)
            ev = df[df.evidence_ref.isin(ind.evidence_refs)]
            tl = build_timeline(ev)
            st.dataframe(tl.assign(timestamp=tl.timestamp.dt.strftime("%Y-%m-%d %H:%M:%S")), hide_index=True)


def tab_notes(store, case_id, run):
    st.caption("Observations and hypotheses are yours, kept separate from system facts and indicators. "
               "Evidence references must exist in the case.")
    inds = run["indicators"] if run else []
    with st.form("note_form", clear_on_submit=True):
        kind = st.radio("Type", ["observation", "hypothesis"], horizontal=True)
        text = st.text_area("Text")
        author = st.text_input("Author", value=st.session_state.get("author", ""))
        from_ind = st.multiselect("Attach evidence from indicators", [i.indicator_id for i in inds])
        manual = st.text_area("Additional evidence refs (tx_hash#index, separated by commas or spaces)")
        conf = st.selectbox("Confidence (hypotheses)", CONFIDENCE_LEVELS)
        if st.form_submit_button("Add note"):
            refs = [r for i in inds if i.indicator_id in from_ind for r in i.evidence_refs]
            refs += [t for t in re.split(r"[,\s;]+", manual) if t]
            try:
                store.add_note(case_id, kind, text, author, refs, confidence=conf if kind == "hypothesis" else None)
                st.session_state["author"] = author
                st.success("Note added.")
            except (ValueError, EvidenceReferenceError) as exc:
                st.error(str(exc))
    for n in store.list_notes(case_id):
        with st.container(border=True):
            st.markdown(f"**NOTE-{n['id']:04d}** · {n['kind']} · {n['author']} · {n['created_at']}")
            st.write(n["text"])
            st.caption(f"{len(n['evidence_refs'])} evidence reference(s)")
            if n["kind"] == "hypothesis":
                new = st.selectbox("Status", HYPOTHESIS_STATUSES, index=HYPOTHESIS_STATUSES.index(n["status"]), key=f"st_{n['id']}")
                if new != n["status"]:
                    store.update_hypothesis(n["id"], status=new)
                    st.rerun()


def tab_export(store, case_id):
    st.write("Reports contain the dataset fingerprint, parameters, facts, indicators, hypotheses, and every cited transfer.")
    if st.button("Build report"):
        try:
            report = service.build_case_report(store, case_id)
        except (ValueError, StaleAnalysisError, EvidenceReferenceError) as exc:
            st.error(str(exc))
            return
        st.session_state["report"] = report
    report = st.session_state.get("report")
    if not report or report["case"]["id"] != case_id:
        return
    st.success(f"Report {report['report_id']}: {len(report['derived_indicators'])} indicators, "
               f"{len(report['evidence'])} evidence transfers, dataset {report['reproducibility']['dataset_sha256'][:12]}…")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("findings.csv", findings_csv(report))
        z.writestr("evidence_transactions.csv", evidence_csv(report))
    c = st.columns(4)
    c[0].download_button("JSON", render_json(report), "report.json", "application/json")
    c[1].download_button("HTML", render_html(report), "report.html", "text/html")
    c[2].download_button("CSV (zip)", buf.getvalue(), "findings_csv.zip", "application/zip")
    c[3].caption("PDF: open the HTML and use Print → Save as PDF.")


def main() -> None:
    st.set_page_config(page_title="ChainTrace", page_icon="🔗", layout="wide")
    db_path = os.environ.get("CHAINTRACE_DB") or "chaintrace_cases.db"
    try:
        store = get_store(db_path)
    except (OSError, sqlite3.OperationalError) as exc:
        st.error(
            f"Cannot open the ChainTrace database at '{db_path}'. "
            "Check that the path is writable and is not a folder. "
            f"SQLite reported: {exc}"
        )
        st.stop()
    labels = load_labels()
    st.title("ChainTrace")
    st.caption(f"v{__version__} · read-only blockchain investigation · leads, not verdicts")
    st.info(DISCLAIMERS[3])
    case_id = sidebar_case(store)
    if case_id is None:
        st.write("Create a case in the sidebar to begin.")
        return
    sidebar_data(store, case_id)
    df = store.load_transactions(case_id)
    if df.empty:
        st.write("This case has no transactions. Load the synthetic demo dataset or import a CSV from the sidebar.")
        return
    run, stale = service.run_status(store, case_id)
    indicators = run["indicators"] if run else []
    tabs = st.tabs(["Overview", "Graph", "Timeline", "Indicators", "Notes & hypotheses", "Export"])
    with tabs[0]:
        tab_overview(df, labels, case_id, store)
    with tabs[1]:
        tab_graph(df, labels, indicators)
    with tabs[2]:
        tab_timeline(df, labels, indicators)
    with tabs[3]:
        tab_indicators(store, case_id, df, labels, run, stale)
    with tabs[4]:
        tab_notes(store, case_id, run)
    with tabs[5]:
        tab_export(store, case_id)


main()

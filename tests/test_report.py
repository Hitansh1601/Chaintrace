import copy
import json

import pytest
from helpers import addr, frame

from chaintrace import service
from chaintrace.cases import CaseStore
from chaintrace.heuristics import HeuristicConfig, run_all
from chaintrace.importer import ImportResult
from chaintrace.report import (
    build_report, evidence_csv, findings_csv, render_html, render_json, verify_report,
)
from chaintrace.schema import EvidenceReferenceError, StaleAnalysisError

FIXED = "2026-01-01T00:00:00+00:00"


@pytest.fixture()
def case():
    store = CaseStore()
    cid = store.create_case("Report case", "Analyst", "desc")
    rows = [(1, 100 + i, i * 30, 1.0) for i in range(10)] + [(7, 8, 9999, 2.0)]
    df = frame(rows)
    store.add_import(cid, ImportResult(df, df.iloc[0:0], "sha", "t.csv"))
    inds = service.analyze_case(store, cid, HeuristicConfig(), [addr(1)])
    store.add_note(cid, "observation", "obs text", "me", list(inds[0].evidence_refs[:2]))
    store.add_note(cid, "hypothesis", "hyp text", "me", [inds[0].evidence_refs[0]], confidence="medium")
    return store, cid, df, inds


def make(case, **over):
    store, cid, df, inds = case
    args = dict(case=store.get_case(cid), transactions=df, indicators=inds, notes=store.list_notes(cid),
                config=HeuristicConfig(), watchlist=[addr(1)], import_log=store.import_log(cid), generated_at=FIXED)
    args.update(over)
    return build_report(**args)


def all_cited_refs(report):
    refs = {r for i in report["derived_indicators"] for r in i["evidence_refs"]}
    refs |= {r for f in report["observed_facts"] for r in f["evidence_refs"]}
    for sec in ("investigator_observations", "investigator_hypotheses"):
        refs |= {r for n in report[sec] for r in n["evidence_refs"]}
    return refs


def test_report_separates_the_three_evidence_classes(case):
    r = make(case)
    assert {f["kind"] for f in r["observed_facts"]} == {"observed_fact"}
    assert {i["kind"] for i in r["derived_indicators"]} == {"derived_indicator"}
    assert [n["kind"] for n in r["investigator_hypotheses"]] == ["investigator_hypothesis"]
    assert [n["kind"] for n in r["investigator_observations"]] == ["investigator_observation"]
    assert r["investigator_hypotheses"][0]["confidence"] == "medium"
    assert any("not attributed" in d or "No address" in d for d in r["disclaimers"])


def test_every_cited_reference_is_preserved_in_evidence(case):
    r = make(case)
    evidence = {e["evidence_ref"]: e for e in r["evidence"]}
    cited = all_cited_refs(r)
    assert cited and cited <= set(evidence)
    first = r["derived_indicators"][0]
    for ref in first["evidence_refs"]:
        assert first["indicator_id"] in evidence[ref]["referenced_by"]
    sample = evidence[first["evidence_refs"][0]]
    assert {"tx_hash", "block_number", "timestamp", "from_address", "to_address", "amount", "asset", "data_source"} <= set(sample)


def test_dangling_indicator_reference_blocks_report(case):
    store, cid, df, inds = case
    bad = copy.deepcopy(inds)
    bad[0].evidence_refs = (*bad[0].evidence_refs, "0xmissing#0")
    with pytest.raises(EvidenceReferenceError) as exc:
        make(case, indicators=bad)
    assert exc.value.unresolved == ["0xmissing#0"]


def test_dangling_note_reference_blocks_report(case):
    store, cid, df, inds = case
    notes = store.list_notes(cid)
    notes[0]["evidence_refs"] = ["0xmissing#0"]
    with pytest.raises(EvidenceReferenceError):
        make(case, notes=notes)


def test_report_id_is_deterministic_and_content_sensitive(case):
    a, b = make(case), make(case, generated_at="2030-05-05T00:00:00+00:00")
    assert a["report_id"] == b["report_id"]
    c = make(case, notes=[])
    assert c["report_id"] != a["report_id"]


def test_json_roundtrip_is_lossless(case):
    r = make(case)
    assert json.loads(render_json(r)) == r


def test_csv_exports_carry_references(case):
    r = make(case)
    f, e = findings_csv(r), evidence_csv(r)
    ind = r["derived_indicators"][0]
    assert ind["indicator_id"] in f and ind["evidence_refs"][0] in f
    assert all(ref in e for ref in ind["evidence_refs"])
    assert e.splitlines()[0].startswith("evidence_ref,tx_hash")
    assert len(e.splitlines()) == len(r["evidence"]) + 1


def test_csv_neutralises_formula_injection(case):
    store, cid, df, inds = case
    store.add_note(cid, "observation", "=HYPERLINK(\"http://x\")", "me")
    assert "'=HYPERLINK" in findings_csv(make(case, notes=store.list_notes(cid)))


def test_html_escapes_untrusted_text_and_links_evidence(case):
    store, cid, df, inds = case
    store.add_note(cid, "observation", "<script>alert(1)</script>", "<b>me</b>")
    html = render_html(make(case, notes=store.list_notes(cid)))
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html and "<b>me</b>" not in html
    ref = make(case)["derived_indicators"][0]["evidence_refs"][0]
    assert ref in html and 'href="#ev-' in html and "Read before relying" in html
    assert "Why it fired" in html and "Caveats" in html


def test_verify_report_passes_then_detects_tampering(case):
    store, cid, df, inds = case
    r = make(case)
    assert verify_report(r, df)["ok"]
    changed = df.copy()
    changed.loc[0, "amount"] = 12345.0
    res = verify_report(r, changed)
    assert not res["ok"] and not res["checks"]["dataset_fingerprint_matches"]
    forged = copy.deepcopy(r)
    forged["derived_indicators"] = []
    assert not verify_report(forged, df)["checks"]["report_id_matches_content"]
    dropped = copy.deepcopy(r)
    dropped["evidence"] = dropped["evidence"][1:]
    assert not verify_report(dropped, df)["checks"]["every_citation_has_evidence_record"]


def test_service_export_writes_all_files_and_verifies(case, tmp_path):
    store, cid, df, inds = case
    paths = service.export_case(store, cid, tmp_path, FIXED)
    assert set(paths) == {"json", "html", "findings_csv", "evidence_csv"} and all(p.exists() for p in paths.values())
    assert service.verify_exported_report(store, cid, paths["json"])["ok"]


def test_export_requires_analysis_and_rejects_stale_runs(case):
    store, cid, df, inds = case
    fresh = store.create_case("empty", "x")
    with pytest.raises(ValueError):
        service.build_case_report(store, fresh)
    more = frame([(50, 51, 0, 1.0)])
    store.add_import(cid, ImportResult(more.assign(tx_hash="0x" + "ab" * 32, evidence_ref="0x" + "ab" * 32 + "#0"),
                                       more.iloc[0:0], "s2", "more.csv"))
    with pytest.raises(StaleAnalysisError):
        service.build_case_report(store, cid)

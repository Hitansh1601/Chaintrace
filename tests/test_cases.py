import pytest
from helpers import addr, frame

from chaintrace.cases import CaseStore
from chaintrace.heuristics import HeuristicConfig, run_all
from chaintrace.importer import ImportResult
from chaintrace.report import dataset_fingerprint
from chaintrace.schema import EvidenceReferenceError


def result(df):
    return ImportResult(valid=df, rejected=df.iloc[0:0], sha256="abc", source_name="t.csv")


@pytest.fixture()
def store_case():
    store = CaseStore()
    cid = store.create_case("Case A", "Analyst")
    df = frame([(1, 2, 0, 1.5), (2, 3, 60, 1.4), (3, 4, 120, 1.3)])
    store.add_import(cid, result(df))
    return store, cid, df


def test_create_and_get_case():
    s = CaseStore()
    cid = s.create_case(" Name ", "Me", "desc")
    assert s.get_case(cid)["name"] == "Name" and s.list_cases()[0]["transfer_count"] == 0
    with pytest.raises(KeyError):
        s.get_case(999)


@pytest.mark.parametrize("name,inv", [("", "x"), ("x", "  "), ("   ", "y")])
def test_case_requires_name_and_investigator(name, inv):
    with pytest.raises(ValueError):
        CaseStore().create_case(name, inv)


def test_import_roundtrip_preserves_data_and_is_idempotent(store_case):
    store, cid, df = store_case
    loaded = store.load_transactions(cid)
    assert dataset_fingerprint(loaded) == dataset_fingerprint(df)
    again = store.add_import(cid, result(df))
    assert again["inserted_rows"] == 0 and again["already_present"] == 3
    assert len(store.load_transactions(cid)) == 3 and len(store.import_log(cid)) == 2


def test_import_into_missing_case_fails():
    with pytest.raises(KeyError):
        CaseStore().add_import(5, result(frame([(1, 2, 0, 1)])))


def test_cases_are_isolated():
    s = CaseStore()
    a, b = s.create_case("A", "x"), s.create_case("B", "x")
    s.add_import(a, result(frame([(1, 2, 0, 1)])))
    assert s.load_transactions(b).empty and len(s.load_transactions(a)) == 1


def test_notes_require_resolvable_evidence(store_case):
    store, cid, df = store_case
    ref = df.evidence_ref.iloc[0]
    nid = store.add_note(cid, "observation", "saw it", "me", [ref.upper()])
    assert store.list_notes(cid)[0]["evidence_refs"] == [ref] and nid == 1
    with pytest.raises(EvidenceReferenceError) as exc:
        store.add_note(cid, "hypothesis", "theory", "me", [ref, "0xdead#0"])
    assert exc.value.unresolved == ["0xdead#0"]
    assert len(store.list_notes(cid)) == 1  # nothing partially stored


def test_hypothesis_defaults_and_status_update(store_case):
    store, cid, df = store_case
    nid = store.add_note(cid, "hypothesis", "maybe", "me", [df.evidence_ref.iloc[0]])
    n = store.list_notes(cid, "hypothesis")[0]
    assert n["status"] == "open" and n["confidence"] == "low"
    store.update_hypothesis(nid, status="refuted", confidence="medium")
    n = store.list_notes(cid)[0]
    assert (n["status"], n["confidence"]) == ("refuted", "medium")
    with pytest.raises(ValueError):
        store.update_hypothesis(nid, status="proven")
    obs = store.add_note(cid, "observation", "fact-ish", "me")
    with pytest.raises(ValueError):
        store.update_hypothesis(obs, status="open")
    assert store.list_notes(cid, "observation")[0]["status"] is None


@pytest.mark.parametrize("kw", [dict(kind="verdict"), dict(text=" "), dict(author=""), dict(text="x" * 10_001),
                                dict(kind="hypothesis", confidence="certain"), dict(kind="hypothesis", status="guilty")])
def test_invalid_notes_rejected(store_case, kw):
    store, cid, _ = store_case
    args = dict(kind="observation", text="ok", author="me")
    args.update(kw)
    with pytest.raises(ValueError):
        store.add_note(cid, **args)


def test_sql_metacharacters_are_stored_inertly(store_case):
    store, cid, _ = store_case
    evil = "'); DROP TABLE notes; --"
    store.add_note(cid, "observation", evil, "me")
    assert store.list_notes(cid)[0]["text"] == evil


def test_watchlist_normalised(store_case):
    store, cid, _ = store_case
    assert store.set_watchlist(cid, [addr(2).upper().replace("0X", "0x"), "", addr(2)]) == [addr(2)]
    assert store.get_watchlist(cid) == [addr(2)]


def test_analysis_run_roundtrip(store_case):
    store, cid, df = store_case
    inds = run_all(df, HeuristicConfig(burst_min_transfers=2, burst_min_counterparties=2))
    store.save_analysis_run(cid, dataset_fingerprint(df), HeuristicConfig(burst_min_transfers=2, burst_min_counterparties=2), [], inds)
    run = store.latest_analysis_run(cid)
    assert [i.to_dict() for i in run["indicators"]] == [i.to_dict() for i in inds]
    assert run["config"].burst_min_transfers == 2


def test_file_database_persists_across_instances(tmp_path):
    path = tmp_path / "cases.db"
    s1 = CaseStore(path)
    cid = s1.create_case("Persist", "me")
    s1.add_import(cid, result(frame([(1, 2, 0, 1)])))
    s1.add_note(cid, "observation", "kept", "me")
    s2 = CaseStore(path)
    assert s2.get_case(cid)["name"] == "Persist" and len(s2.load_transactions(cid)) == 1 and s2.list_notes(cid)[0]["text"] == "kept"


def test_file_database_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "folder" / "cases.db"
    store = CaseStore(path)
    case_id = store.create_case("Nested", "me")
    assert path.is_file() and store.get_case(case_id)["name"] == "Nested"

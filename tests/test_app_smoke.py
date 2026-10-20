import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from chaintrace.cases import CaseStore  # noqa: E402

from pathlib import Path  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "src" / "chaintrace" / "app.py")


def click(at, label):
    next(b for b in list(at.button) + list(at.sidebar.button) if b.label == label).click().run()


def test_app_flow_load_analyse_report(tmp_path, monkeypatch):
    db = tmp_path / "ui.db"
    monkeypatch.setenv("CHAINTRACE_DB", str(db))
    store = CaseStore(db)
    cid = store.create_case("UI case", "Analyst")
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert not at.exception
    click(at, "Load synthetic demo dataset")
    assert not at.exception and len(store.load_transactions(cid)) == 201
    click(at, "Run analysis")
    assert not at.exception and store.latest_analysis_run(cid) is not None
    click(at, "Build report")
    assert not at.exception and any("Report" in s.value for s in at.success)


def test_app_starts_with_no_cases(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAINTRACE_DB", str(tmp_path / "empty.db"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception

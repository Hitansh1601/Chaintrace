import json

from chaintrace import service
from chaintrace.cli import main


def test_demo_end_to_end(tmp_path):
    out = service.run_demo(tmp_path / "demo.db", tmp_path / "out", "2026-01-01T00:00:00+00:00")
    assert out["import"]["inserted_rows"] == 201 and out["import"]["rejected_rows"] == 0
    assert len(out["indicators"]) == 5
    assert all(m["matched"] for m in out["manifest_check"])
    assert out["verification"]["ok"]
    report = json.loads(out["paths"]["json"].read_text(encoding="utf-8"))
    assert len(report["investigator_hypotheses"]) == 2 and len(report["investigator_observations"]) == 1
    assert report["reproducibility"]["transfer_count"] == 201
    assert "SYNTHETIC" in report["case"]["description"]


def test_demo_is_reproducible_across_runs(tmp_path):
    a = service.run_demo(tmp_path / "a.db", tmp_path / "a", "2026-01-01T00:00:00+00:00")
    b = service.run_demo(tmp_path / "b.db", tmp_path / "b", "2026-01-01T00:00:00+00:00")
    ja, jb = (json.loads(r["paths"]["json"].read_text(encoding="utf-8")) for r in (a, b))
    assert ja["reproducibility"]["dataset_sha256"] == jb["reproducibility"]["dataset_sha256"]
    assert [i["indicator_id"] for i in ja["derived_indicators"]] == [i["indicator_id"] for i in jb["derived_indicators"]]


def test_cli_demo_export_verify(tmp_path, capsys):
    out = tmp_path / "demo"
    assert main(["demo", "--out", str(out)]) == 0
    assert "reproducibility check: PASS" in capsys.readouterr().out
    db = str(out / "demo_case.db")
    assert main(["export", "--db", db, "--case", "1", "--out", str(tmp_path / "x")]) == 0
    assert main(["verify", str(tmp_path / "x" / "report.json"), "--db", db, "--case", "1"]) == 0
    assert main(["export", "--db", db, "--case", "99", "--out", str(tmp_path / "y")]) == 2

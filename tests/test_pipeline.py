import json
from datetime import date
from pathlib import Path

import pytest

from inbody import cli, report, timeline as tl
from inbody.analysis import Analysis
from inbody.extract import validate_scan

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures"
EX = ROOT / "examples"


def new_scan(date_iso, **over):
    scan = json.loads((EX / "sample_new_scan.json").read_text())
    scan["test_date"] = date_iso
    scan.update(over)
    return scan


def test_parse_skill_report_tables():
    t = tl.load_html(FIX / "skill_report.html")
    assert [s["test_date"] for s in t["scans"]] == ["2025-09-05", "2025-10-17"]
    assert t["patient"] == {"name": "Test Person", "patient_id": "T-42", "age": 66, "sex": "Female",
                            "height": "5'4\"", "device": "InBody 380"}
    s = t["scans"][1]
    assert s["smm"] == 53.0 and s["bmr"] == 1318 and s["ecw_tbw"] == 0.385 and s["fmi"] == 8.4 and s["ffmi"] == 17.2
    assert s["segmental_lean"]["left_leg"] == {"lb": 14.3, "pct": 96.4}
    assert s["segmental_fat"]["trunk"] == {"lb": 23.9, "pct": None}


def test_update_skill_report_with_new_scan(tmp_path):
    scan_file = tmp_path / "scan.json"
    scan_file.write_text(json.dumps(new_scan("2025-12-01", sex="Female", age=66, patient_id="T-42")))
    out = tmp_path / "new.html"
    cli.main(["analyze", str(scan_file), "--history", str(FIX / "skill_report.html"), "-o", str(out)])
    other = tmp_path / "other.json"
    other.write_text(json.dumps(new_scan("2026-02-01", patient_id="SOMEONE-ELSE")))
    with pytest.raises(SystemExit):
        cli.main(["analyze", str(other), "--history", str(out), "-o", str(tmp_path / "x.html")])
    html = out.read_text()
    assert "3 scans" in html and "12/1/25" in html and "9/5/25" in html
    # The new report embeds its data, so it round-trips exactly.
    t = tl.load_html(out)
    assert len(t["scans"]) == 3 and t["patient"]["name"] == "Test Person"
    assert json.loads((tmp_path / "new.json").read_text()) == t


def test_round_trip_and_replace_same_date(tmp_path):
    t = tl.load_json(EX / "sample_timeline.json")
    out = tmp_path / "r.html"
    out.write_text(report.render(t))
    t2 = tl.load_html(out)
    assert t2 == t
    status = tl.add_scan(t2, new_scan(t2["scans"][-1]["test_date"], smm=99.9))
    assert status == "replaced" and len(t2["scans"]) == 2 and t2["scans"][-1]["smm"] == 99.9


def test_findings_and_recommendations():
    t = tl.load_json(EX / "sample_timeline.json")
    tl.add_scan(t, json.loads((EX / "sample_scan_2025-12-02.json").read_text()))
    tl.add_scan(t, new_scan("2026-01-14"))
    a = Analysis(t, generated=date(2026, 1, 20))
    titles = [f[2] for f in a.findings()]
    assert "Body recomposition confirmed" in titles
    assert "Phase angle dropped this interval" in titles  # 6.1 -> 5.0 with ECW/TBW rising
    assert "Daily protein target" in titles and "Next InBody scan" in titles
    assert a.protein_g() == 170  # 2 x 85.1
    assert a.zone2() == (97, 97 + 16)  # age 58 -> 162 max; 60-70%
    recs = a.recommendations()
    assert "97–113 bpm" in recs["Exercise"][0]
    assert "170 g/day" in recs["Nutrition"][0]
    # order: wins, then watch, then action
    kinds = [f[0] for f in a.findings()]
    assert kinds == sorted(kinds, key=["win", "watch", "act"].index)


def test_single_scan_report():
    t = {"version": 1, "patient": {}, "scans": [new_scan("2026-01-14")]}
    html = report.render(t)
    assert "Trend charts require 2 or more scans." in html
    assert "baseline" in html


def test_summary_has_no_names():
    t = tl.load_html(FIX / "skill_report.html")
    paras = Analysis(t).summary()
    assert len(paras) == 3
    text = " ".join(paras)
    assert "Test Person" not in text and "Reid" not in text


def test_validate_scan_catches_inconsistency():
    s = new_scan("2026-01-14")
    s["weight"] = s["ffm"] + s["bfm"] + 5
    assert any("Weight" in w for w in validate_scan(s))
    assert validate_scan(new_scan("2026-01-14")) == []


def test_parse_date_formats():
    assert tl.parse_date("9/5/25") == "2025-09-05"
    assert tl.parse_date("09/05/2025") == "2025-09-05"
    assert tl.parse_date("Sep 5, 2025") == "2025-09-05"
    assert tl.parse_date("Δ Total") is None


def test_extract_scan_request_and_parse(tmp_path):
    from types import SimpleNamespace
    from inbody import extract

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    payload = new_scan("2026-01-14")
    calls = {}

    class Messages:
        def create(self, **kw):
            calls.update(kw)
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text=json.dumps(payload))])

    scan = extract.extract_scan(pdf, client=SimpleNamespace(messages=Messages()))
    assert scan["smm"] == payload["smm"] and scan["source_file"] == "scan.pdf"
    block = calls["messages"][0]["content"][0]
    assert block["type"] == "document" and block["source"]["media_type"] == "application/pdf"
    assert calls["output_config"]["format"]["type"] == "json_schema"
    assert calls["model"] == "claude-opus-5"

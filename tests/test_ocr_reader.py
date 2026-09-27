"""Local (no-API) reader: parse saved OCR output of a de-identified InBody 380 sheet."""
import json
from pathlib import Path

from inbody.extract import validate_scan
from inbody.ocr_reader import boxes_from_json, parse_page

FIX = Path(__file__).parent / "fixtures" / "ocr_inbody380_demo.json"


def parse(**kw):
    return parse_page(boxes_from_json(json.loads(FIX.read_text())), **kw)


def test_reads_every_value():
    s = parse(reread=lambda *a: [])
    assert s["patient_id"] == "DEMO-0001" and s["test_date"] == "2026-01-14"
    assert (s["age"], s["sex"], s["height"]) == (52, "Male", "5 ft 8 in")
    expected = {"icw": 62.0, "ecw": 37.3, "dry_lean_mass": 35.7, "bfm": 23.7, "tbw": 99.2, "ffm": 134.9,
                "weight": 158.6, "smm": 76.3, "bmi": 24.1, "pbf": 14.9, "ecw_tbw": 0.375, "phase_angle": 6.5,
                "inbody_score": 85, "smi": 8.5, "vfl": 4, "bmr": 1692, "arm_circumference": 12.6,
                "ffmi": 20.5, "fmi": 3.6, "smm_wt": 48.1}
    assert {k: s[k] for k in expected} == expected
    assert (s["tbw_range"], s["ffm_range"], s["weight_range"], s["bmr_range"]) == \
        ("81.4~99.4", "110.7~135.4", "123.0~166.2", "1559~1823")
    assert s["segmental_lean"]["right_arm"] == {"lb": 8.2, "pct": 116.1}
    assert s["segmental_lean"]["left_leg"] == {"lb": 19.67, "pct": 100.2}
    assert s["segmental_fat"]["trunk"] == {"lb": 12.3, "pct": 134.8}
    assert s["segmental_fat"]["left_arm"] == {"lb": 0.9, "pct": 70.1}
    assert validate_scan(s) == []


def test_missing_fragment_is_reread():
    """If the page pass skips a number, the reader looks at that area again."""
    items = json.loads(FIX.read_text())
    items = [i for i in items if i[1] != "134.8%"]
    calls = []

    def reread(*box):
        calls.append(box)
        return ["12.31b)", "134.8%"]

    s = parse_page(boxes_from_json(items), reread=reread)
    assert s["segmental_fat"]["trunk"] == {"lb": 12.3, "pct": 134.8} and calls


def test_disagreeing_duplicates_are_flagged():
    items = json.loads(FIX.read_text())
    for i in items:
        if i[1] == "158.6" and i[0][0][1] < 500:  # weight in the top table only
            i[1] = "153.6"
    s = parse_page(boxes_from_json(items))
    assert any("weight" in n for n in s["extraction_notes"])
    assert validate_scan(s)

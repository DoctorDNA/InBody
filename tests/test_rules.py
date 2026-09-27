"""The added clinical rules, each triggered with a small made-up timeline."""
import copy
import json
from datetime import date
from pathlib import Path

from inbody.analysis import Analysis

EX = Path(__file__).resolve().parent.parent / "examples"
BASE = json.loads((EX / "sample_new_scan.json").read_text())


def scan(test_date, **over):
    s = copy.deepcopy(BASE)
    s["test_date"] = test_date
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            for seg, vals in v.items():
                s[k][seg].update(vals)
        else:
            s[k] = v
    return s


def findings(*scans):
    a = Analysis({"version": 1, "patient": {}, "scans": list(scans)}, generated=date(2026, 3, 1))
    return {title: body for _, _, title, body in a.findings()}, a


def test_fat_trending_up_with_trunk_share():
    f, a = findings(scan("2026-01-01", bfm=38.0, pbf=19.0, segmental_fat={"trunk": {"lb": 19.0}}),
                    scan("2026-02-12", bfm=41.0, pbf=20.2, segmental_fat={"trunk": {"lb": 21.0}}))
    assert "Body fat trending up" in f
    assert "up 3.0 lb" in f["Body fat trending up"] and "67% of the gain" in f["Body fat trending up"]
    assert "drifting up" in a.summary()[1]


def test_fat_above_baseline_but_improving():
    f, _ = findings(scan("2026-01-01", bfm=38.0), scan("2026-01-20", bfm=42.0), scan("2026-02-12", bfm=40.0))
    assert "Body fat still above baseline" in f and "came down 2.0 lb" in f["Body fat still above baseline"]


def test_fat_shifting_to_trunk_without_total_gain():
    f, _ = findings(scan("2026-01-01", segmental_fat={"trunk": {"lb": 18.0}, "right_leg": {"lb": 6.0}}),
                    scan("2026-02-12", segmental_fat={"trunk": {"lb": 21.0}, "right_leg": {"lb": 4.0}}))
    assert "Fat shifting toward the trunk" in f


def test_lean_shifting_from_limbs():
    f, _ = findings(scan("2026-01-01"),
                    scan("2026-02-12", segmental_lean={"right_leg": {"lb": 19.5}, "left_leg": {"lb": 19.3},
                                                       "trunk": {"lb": 64.0}}))
    assert "Lean mass shifting away from the limbs" in f


def test_large_weight_swing_and_high_water():
    f, _ = findings(scan("2026-01-01", weight=150.0, tbw=95.0),
                    scan("2026-02-10", weight=158.9, tbw=100.3, tbw_range="81.4~99.4"))
    assert "Large weight change — verify test conditions" in f
    assert "+8.9 lb in 40 days" in f["Large weight change — verify test conditions"]
    assert "Total body water above normal range" in f


def test_smi_declining_while_normal():
    f, _ = findings(scan("2026-01-01", smi=9.0), scan("2026-02-12", smi=8.6))
    assert "SMI declining" in f
    f, _ = findings(scan("2026-01-01", smi=9.0), scan("2026-02-12", smi=8.95))
    assert "SMI declining" not in f


def test_bmr_falling_with_muscle():
    f, _ = findings(scan("2026-01-01", smm=86.0, bmr=1860), scan("2026-02-12", smm=85.0, bmr=1835))
    assert "Metabolic rate falling with muscle" in f


def test_ffmi_thresholds():
    f, _ = findings(scan("2026-01-01", ffmi=21.0))
    assert "Well-muscled frame" in f
    f, _ = findings(scan("2026-01-01", ffmi=16.0))
    assert "FFMI below adequate" in f
    f, _ = findings(scan("2026-01-01", ffmi=16.0, sex="Female"))
    assert "FFMI below adequate" not in f and "Well-muscled frame" not in f


def test_leg_wording_matches_reason():
    _, a = findings(scan("2026-01-01", segmental_lean={"right_arm": {"pct": 116}, "left_arm": {"pct": 115},
                                                        "right_leg": {"pct": 104}, "left_leg": {"pct": 102}}))
    assert a.legs_lagging() == "behind_arms"
    assert "trail the arms" in " ".join(a.recommendations()["Exercise"])
    _, a = findings(scan("2026-01-01", segmental_lean={"left_leg": {"pct": 97}}))
    assert a.legs_lagging() == "below"

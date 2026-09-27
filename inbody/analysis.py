"""Longitudinal analysis: deltas, clinical flags, findings, recommendations and summary prose.

All thresholds follow the Morpheus Precision Health InBody analysis protocol.
"""

import re
from datetime import date, timedelta

from .schema import NUMERIC_FIELDS, SEGMENTS
from .timeline import short_date

THRESHOLDS = {
    "Male": {"pbf_watch": 20, "pbf_act": 25, "smi": 7.0, "pa_low": 5.5, "pa_high": 7.5, "ffmi_ok": 17, "ffmi_good": 20},
    "Female": {"pbf_watch": 28, "pbf_act": 33, "smi": 5.7, "pa_low": 5.0, "pa_high": 6.5, "ffmi_ok": 15, "ffmi_good": 17},
}

# Change smaller than this is treated as flat.
FLAT = {
    "weight": 0.5, "smm": 0.3, "bfm": 0.5, "pbf": 0.3, "bmi": 0.2, "ffm": 0.5, "vfl": 0.5,
    "smi": 0.05, "ffmi": 0.1, "fmi": 0.1, "smm_wt": 0.3, "bmr": 10, "phase_angle": 0.1,
    "ecw_tbw": 0.002, "inbody_score": 0.5, "tbw": 0.5, "icw": 0.5, "ecw": 0.5,
}


def fmt(v, digits=1):
    if v is None:
        return "—"
    return f"{v:,.{digits}f}"


MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def md(d):
    """'Sep 5' — portable (strftime's %-d fails on Windows)."""
    return f"{MONTHS[d.month - 1]} {d.day}"


def mdy(d):
    return f"{md(d)}, {d.year}"


def signed(v, digits=1):
    if v is None:
        return "—"
    return f"{'+' if v > 0 else ''}{v:,.{digits}f}"


DIGITS = {"vfl": 0, "inbody_score": 0, "bmr": 0, "ecw_tbw": 3, "age": 0}


def digits_for(key):
    return DIGITS.get(key, 1)


def delta(scans, key):
    """Δ total (latest vs first scan that has the value)."""
    vals = [s.get(key) for s in scans if s.get(key) is not None]
    if len(vals) < 2:
        return None
    return round(vals[-1] - vals[0], 4)


def classify(key, d):
    """'good' | 'bad' | 'flat' | 'neutral' for a change in `key`."""
    if d is None:
        return "flat"
    if abs(d) < FLAT.get(key, 0.1):
        return "flat"
    direction = NUMERIC_FIELDS.get(key, ("", "", 0))[2]
    if direction == 0:
        return "neutral"
    return "good" if d * direction > 0 else "bad"


def _range_low(text):
    if not text:
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    return float(nums[0]) if nums else None


class Analysis:
    def __init__(self, timeline, generated=None):
        self.timeline = timeline
        self.scans = timeline["scans"]
        if not self.scans:
            raise ValueError("Timeline has no scans")
        self.patient = timeline.get("patient", {})
        self.latest = self.scans[-1]
        self.base = self.scans[0]
        self.prev = self.scans[-2] if len(self.scans) > 1 else None
        self.n = len(self.scans)
        self.sex = self.patient.get("sex") or self.latest.get("sex") or "Male"
        if self.sex not in THRESHOLDS:
            self.sex = "Female" if str(self.sex).lower().startswith("f") else "Male"
        self.t = THRESHOLDS[self.sex]
        self.age = self.latest.get("age") or self.patient.get("age")
        self.generated = generated or date.today()
        self.labels = [short_date(s["test_date"]) for s in self.scans]

    # ------------------------------------------------------------ helpers

    def v(self, key, scan=None):
        return (scan or self.latest).get(key)

    def d(self, key):
        return delta(self.scans, key)

    def interval(self, key):
        if not self.prev:
            return None
        a, b = self.prev.get(key), self.latest.get(key)
        return None if a is None or b is None else round(b - a, 4)

    def series(self, key):
        return [s.get(key) for s in self.scans]

    def interval_days(self):
        if not self.prev:
            return None
        return (date.fromisoformat(self.latest["test_date"]) - date.fromisoformat(self.prev["test_date"])).days

    def months_span(self):
        days = (date.fromisoformat(self.latest["test_date"]) - date.fromisoformat(self.base["test_date"])).days
        return round(days / 30.44, 1)

    def seg(self, field, seg, scan=None):
        return ((scan or self.latest).get(field) or {}).get(seg) or {}

    def protein_g(self):
        smm = self.v("smm")
        return round(2 * smm) if smm else None

    def zone2(self):
        if not self.age:
            return None
        hr_max = 220 - self.age
        return round(hr_max * 0.60), round(hr_max * 0.70)

    def scan_overdue(self):
        last = date.fromisoformat(self.latest["test_date"])
        return last + timedelta(weeks=8) < self.generated

    def next_scan_window(self):
        if self.scan_overdue():  # latest scan is old: schedule from today instead
            return self.generated + timedelta(weeks=1), self.generated + timedelta(weeks=3)
        last = date.fromisoformat(self.latest["test_date"])
        return last + timedelta(weeks=6), last + timedelta(weeks=8)

    def next_scan_text(self):
        start, end = self.next_scan_window()
        if self.scan_overdue():
            return f"a follow-up scan is overdue — schedule it between {md(start)} and {mdy(end)}"
        return f"between {md(start)} and {mdy(end)} (6–8 weeks after the latest scan)"

    def smm_trajectory(self):
        vals = [x for x in self.series("smm") if x is not None]
        if len(vals) < 2:
            return "baseline"
        last = vals[-1] - vals[-2]
        if abs(last) < 0.5:
            return "plateau"
        return "improving" if last > 0 else "declining"

    def legs_lagging(self):
        for seg in ("right_leg", "left_leg"):
            pct = self.seg("segmental_lean", seg).get("pct")
            if pct is not None and pct < 100:
                return True
        arms = [self.seg("segmental_lean", s).get("pct") for s in ("right_arm", "left_arm")]
        legs = [self.seg("segmental_lean", s).get("pct") for s in ("right_leg", "left_leg")]
        if all(x is not None for x in arms + legs):
            return sum(legs) / 2 < sum(arms) / 2 - 5
        return False

    def recomposition(self):
        dw, df, dm = self.d("weight"), self.d("bfm"), self.d("smm")
        # Fat down + muscle up, with weight stable, up, or falling by less than the fat lost.
        return None not in (dw, df, dm) and df < -0.5 and dm > 0.3 and dw > df

    # ------------------------------------------------------------ cards

    def cards(self):
        spec = [
            ("inbody_score", "InBody Score", ""),
            ("bfm", "Body Fat Mass", " lb"),
            ("smm", "Skeletal Muscle Mass", " lb"),
            ("pbf", "Body Fat %", "%"),
            ("vfl", "Visceral Fat Level", ""),
            ("smi", "SMI", " kg/m²"),
            ("phase_angle", "Phase Angle", "°"),
            ("bmr", "BMR", " kcal"),
        ]
        out = []
        for key, label, unit in spec:
            cur, dg = self.v(key), digits_for(key)
            base_val = next((s.get(key) for s in self.scans if s.get(key) is not None), None)
            d = self.d(key)
            cls = {"good": "g", "bad": "r", "flat": "f", "neutral": "w"}[classify(key, d)]
            note = self._card_note(key)
            if key == "phase_angle":
                iv = self.interval(key)
                if iv is not None and iv <= -0.8:
                    cls = "w"
                elif cur is not None and cur < self.t["pa_low"]:
                    cls = "r"
            if d is None:
                sub = "baseline scan" + (f"; {note}" if note else "")
                badge = "baseline"
                cls = "f"
            else:
                sub = f"from {fmt(base_val, dg)}{unit}" + (f"; {note}" if note else "")
                arrow = "▲" if d > 0 else "▼" if d < 0 else "■"
                badge = f"{signed(d, dg)}{unit} {arrow}"
            out.append({"label": label, "value": f"{fmt(cur, dg)}{unit}" if cur is not None else "—",
                        "sub": sub, "badge": badge, "cls": cls})
        return out

    def _card_note(self, key):
        v = self.v(key)
        if v is None:
            return ""
        t = self.t
        if key == "inbody_score":
            return "excellent" if v >= 90 else "good" if v >= 80 else "adequate" if v >= 70 else "below average"
        if key == "pbf":
            return "healthy range" if v <= t["pbf_watch"] else "watch zone" if v <= t["pbf_act"] else "above target"
        if key == "vfl":
            return "target ≤6" if v > 6 else "at target"
        if key == "smi":
            return f"threshold {t['smi']}"
        if key == "phase_angle":
            return f"normal {t['pa_low']}–{t['pa_high']}°"
        return ""

    # ------------------------------------------------------------ findings

    def findings(self):
        wins, watch, act = [], [], []
        t, n = self.t, self.n
        dw, df, dm, dp = self.d("weight"), self.d("bfm"), self.d("smm"), self.d("pbf")
        span = f"{self.labels[0]} → {self.labels[-1]}"

        # ---- wins
        if self.recomposition():
            wins.append(("Body recomposition confirmed",
                         f"Weight {signed(dw)} lb while body fat mass fell {fmt(abs(df))} lb and skeletal muscle rose "
                         f"{fmt(dm)} lb ({span}). The scale understates this progress — fat is being replaced by muscle. "
                         f"Keep the current training and protein plan."))
        elif df is not None and df <= -1.0:
            extra = f" with skeletal muscle {'preserved' if dm is not None and dm > -0.3 else 'down ' + fmt(abs(dm)) + ' lb'}" if dm is not None else ""
            wins.append(("Fat mass reduced",
                         f"Body fat mass is down {fmt(abs(df))} lb from baseline ({fmt(self.v('bfm', self.base))} → "
                         f"{fmt(self.v('bfm'))} lb){extra}."))
        pbf, pbf0 = self.v("pbf"), self.v("pbf", self.base)
        if pbf is not None and pbf <= t["pbf_watch"] and n > 1 and pbf0 is not None and pbf0 > t["pbf_watch"]:
            wins.append(("Body fat % now in the healthy range",
                         f"Body fat moved from {fmt(pbf0)}% to {fmt(pbf)}%, crossing into the healthy range "
                         f"(≤{t['pbf_watch']}% for {self.sex.lower()}s)."))
        elif pbf is not None and pbf <= t["pbf_watch"]:
            wins.append(("Body fat % within the healthy range",
                         f"Body fat is {fmt(pbf)}% — within the healthy range for {self.sex.lower()}s (≤{t['pbf_watch']}%)."))
        ds = self.d("inbody_score")
        if ds is not None and ds >= 1:
            wins.append(("InBody Score improved",
                         f"InBody Score rose {int(ds)} points ({fmt(self.v('inbody_score', self.base), 0)} → "
                         f"{fmt(self.v('inbody_score'), 0)}), driven by {'muscle gain and fat loss' if (dm or 0) > 0 and (df or 0) < 0 else 'the changes in muscle-fat balance'}."))
        dv = self.d("vfl")
        if dv is not None and dv <= -1:
            wins.append(("Visceral fat declining",
                         f"Visceral Fat Level dropped {int(abs(dv))} level{'s' if abs(dv) >= 2 else ''} "
                         f"({fmt(self.v('vfl', self.base), 0)} → {fmt(self.v('vfl'), 0)}). "
                         f"{'Now at the ≤6 target.' if self.v('vfl') <= 6 else 'Target is ≤6 — Zone 2 cardio is the main lever.'}"))
        pa, dpa = self.v("phase_angle"), self.d("phase_angle")
        if pa is not None:
            if dpa is not None and dpa >= 0.1 and pa >= t["pa_low"]:
                wins.append(("Phase angle improving",
                             f"Phase angle rose {signed(dpa)}° to {fmt(pa)}° (normal {t['pa_low']}–{t['pa_high']}°), "
                             f"a sign of healthier, more robust cell membranes."))
            elif pa >= t["pa_low"] + 0.5 and (self.interval("phase_angle") or 0) > -0.8:
                wins.append(("Phase angle strong",
                             f"Phase angle is {fmt(pa)}° — solidly within the normal range ({t['pa_low']}–{t['pa_high']}°), "
                             f"reflecting good cellular health."))
        smm_vals = [x for x in self.series("smm") if x is not None]
        if len(smm_vals) >= 3 and all(b > a for a, b in zip(smm_vals, smm_vals[1:])):
            wins.append(("Consistent muscle gain",
                         f"Skeletal muscle increased at every one of {len(smm_vals)} scans "
                         f"({fmt(smm_vals[0])} → {fmt(smm_vals[-1])} lb)."))
        if n > 1:
            best = None
            for key, label in SEGMENTS:
                a = self.seg("segmental_lean", key, self.base).get("lb")
                b = self.seg("segmental_lean", key).get("lb")
                if a is not None and b is not None and (best is None or b - a > best[1]):
                    best = (label, b - a)
            if best and best[1] >= 0.3:
                wins.append((f"{best[0]} lean mass up",
                             f"{best[0]} lean mass gained {fmt(best[1])} lb since baseline — the largest segmental gain."))
        db = self.d("bmr")
        if db is not None and db >= 10 and (dm or 0) > 0:
            wins.append(("Metabolic rate rising",
                         f"BMR increased {fmt(db, 0)} kcal/day ({fmt(self.v('bmr', self.base), 0)} → "
                         f"{fmt(self.v('bmr'), 0)}), tracking the new muscle — more calories burned at rest."))

        # ---- watch
        for pair, label in ((("right_arm", "left_arm"), "Arm"), (("right_leg", "left_leg"), "Leg")):
            r = self.seg("segmental_lean", pair[0]).get("lb")
            l = self.seg("segmental_lean", pair[1]).get("lb")
            if r and l and abs(r - l) / max(r, l) > 0.05:
                weaker = "left" if l < r else "right"
                watch.append((f"{label} asymmetry",
                              f"Right {label.lower()} {fmt(r)} lb vs left {fmt(l)} lb ({abs(r - l) / max(r, l) * 100:.0f}% difference). "
                              f"Add unilateral work, starting sets with the {weaker} side."))
        ffm, low = self.v("ffm"), _range_low(self.latest.get("ffm_range"))
        if ffm is not None and low is not None and ffm < low * 1.03:
            watch.append(("Fat-free mass near lower limit",
                          f"FFM is {fmt(ffm)} lb against a normal range starting at {fmt(low)} lb. "
                          f"Prioritize resistance training and protein to build reserve."))
        smi = self.v("smi")
        if smi is not None and t["smi"] <= smi < t["smi"] + 0.5:
            watch.append(("SMI close to threshold",
                          f"SMI is {fmt(smi)} kg/m², within 0.5 of the {t['smi']} kg/m² threshold for "
                          f"{self.sex.lower()}s. Building limb muscle raises this directly."))
        ipa = self.interval("phase_angle")
        if ipa is not None and ipa <= -0.8:
            iecw = self.interval("ecw_tbw")
            if iecw is not None and iecw > 0.002:
                why = (f"ECW/TBW rose at the same time ({fmt(self.v('ecw_tbw', self.prev), 3)} → "
                       f"{fmt(self.v('ecw_tbw'), 3)}), so a hydration artifact is likely.")
            else:
                why = ("ECW/TBW was stable, so this is less likely a hydration artifact — "
                       "consider an inflammatory workup (CRP, ESR) if it persists.")
            watch.append(("Phase angle dropped this interval",
                          f"Phase angle fell {fmt(abs(ipa))}° ({fmt(self.v('phase_angle', self.prev))} → {fmt(pa)}°). "
                          f"{why} Re-scan under controlled conditions (fasted, morning, no exercise beforehand)."))
        ratio = self.v("ecw_tbw")
        if ratio is not None and 0.380 < ratio < 0.390:
            watch.append(("ECW/TBW trending up",
                          f"ECW/TBW is {fmt(ratio, 3)} — above the 0.380 ideal and approaching the 0.390 flag. "
                          f"Recheck hydration and look for swelling or inflammation."))
        earlier_dips = []
        for key, label in (("right_leg", "Right leg"), ("left_leg", "Left leg")):
            pcts = [self.seg("segmental_lean", key, s).get("pct") for s in self.scans]
            cur = pcts[-1]
            if cur is not None and cur < 100:
                watch.append((f"{label} lean mass below ideal",
                              f"{label} lean mass is {fmt(cur)}% of ideal (target ≥100%). "
                              f"Add lower-body emphasis: squats, lunges, Romanian deadlifts, leg press."))
            elif any(p is not None and p < 100 for p in pcts[:-1]):
                earlier_dips.append(f"{label.lower()} is now {fmt(cur)}%")
        if earlier_dips:
            watch.append(("Leg lean mass dipped below ideal earlier",
                          "Leg lean mass was below 100% of ideal at an earlier scan and has recovered ("
                          + "; ".join(earlier_dips) + "). Keep lower-body volume in the program."))
        ism, days = self.interval("smm"), self.interval_days()
        if ism is not None and days is not None and abs(ism) > 2 and days <= 42:
            watch.append(("Unusually large muscle change",
                          f"SMM changed {signed(ism)} lb in {days} days. Confirm both scans were taken under the "
                          f"same conditions (time of day, hydration, food, exercise) before drawing strong conclusions."))
        if pbf is not None and t["pbf_watch"] < pbf <= t["pbf_act"]:
            watch.append(("Body fat % in the watch zone",
                          f"Body fat is {fmt(pbf)}% ({t['pbf_watch']}–{t['pbf_act']}% watch zone for "
                          f"{self.sex.lower()}s). Target is ≤{t['pbf_watch']}%."))

        # ---- action items
        if pa is not None and pa < t["pa_low"]:
            act.append(("Phase angle below normal",
                        f"Phase angle is {fmt(pa)}°, below the {t['pa_low']}° lower limit for {self.sex.lower()}s. "
                        f"Build muscle, confirm hydration, and consider CRP/ESR to look for inflammation."))
        else:
            pas = [x for x in self.series("phase_angle") if x is not None]
            if len(pas) >= 3 and pas[-1] < pas[-2] < pas[-3]:
                act.append(("Phase angle trending down",
                            f"Phase angle has declined across the last three scans ({fmt(pas[-3])} → {fmt(pas[-1])}°). "
                            f"Review recovery, sleep, and inflammation markers."))
        if ratio is not None and ratio >= 0.390:
            act.append(("ECW/TBW elevated",
                        f"ECW/TBW is {fmt(ratio, 3)} (flag ≥0.390), suggesting fluid shift, edema, or inflammation. "
                        f"Clinical review recommended."))
        if len(smm_vals) >= 3 and smm_vals[-1] < smm_vals[-2] < smm_vals[-3]:
            act.append(("Muscle declining across scans",
                        f"SMM has fallen at consecutive scans ({fmt(smm_vals[-3])} → {fmt(smm_vals[-1])} lb) — possible "
                        f"catabolism. Increase protein, start/adjust 2×/week resistance training, review calorie deficit."))
        elif ism is not None and ism <= -1.0 and (self.interval("weight") or 0) < 0:
            act.append(("Muscle lost with weight",
                        f"Weight fell and SMM dropped {fmt(abs(ism))} lb this interval — some of the loss is muscle. "
                        f"Prioritize protein and resistance training to protect it."))
        vfl = self.v("vfl")
        if vfl is not None and vfl >= 10:
            act.append(("Visceral fat elevated",
                        f"Visceral Fat Level is {fmt(vfl, 0)} ({'high risk, ≥13' if vfl >= 13 else 'elevated, ≥10'}); target ≤6. "
                        f"Zone 2 cardio and a longer fasting window are the primary drivers of reduction."))
        if pbf is not None and pbf > t["pbf_act"]:
            act.append(("Body fat % above target",
                        f"Body fat is {fmt(pbf)}% (above {t['pbf_act']}% for {self.sex.lower()}s). "
                        f"Combine Zone 2 cardio, resistance training, and protein-forward nutrition."))
        if smi is not None and smi < t["smi"]:
            act.append(("SMI below threshold",
                        f"SMI is {fmt(smi)} kg/m², below the {t['smi']} kg/m² threshold — low appendicular muscle. "
                        f"Resistance training 2–3×/week is the priority."))
        protein = self.protein_g()
        if protein:
            act.append(("Daily protein target",
                        f"Skeletal muscle is {fmt(self.v('smm'))} lb → protein target is {protein} g/day "
                        f"(2 g per lb of SMM), spread over 3–4 meals with ≥30 g each."))
        act.append(("Next InBody scan",
                    f"Next scan: {self.next_scan_text()}. Then continue every 6–8 weeks under the same conditions: "
                    f"morning, fasted, before exercise, after voiding."))

        return ([("win", "★", *w) for w in wins] + [("watch", "⚠", *w) for w in watch]
                + [("act", "→", *a) for a in act])

    # ------------------------------------------------------------ recommendations

    def recommendations(self):
        z = self.zone2()
        traj = self.smm_trajectory()
        ex = []
        if z:
            ex.append(f"Zone 2 cardio: 30 minutes, at least 3 times per week. For a {self.age}-year-old, "
                      f"target a heart rate of {z[0]}–{z[1]} bpm — a pace where you can still hold a conversation. "
                      f"This is the primary driver of visceral fat reduction and metabolic health.")
        else:
            ex.append("Zone 2 cardio: 30 minutes, at least 3 times per week at 60–70% of max heart rate "
                      "(220 − age). Age was not on the scan, so a specific bpm range can't be given.")
        if traj == "declining":
            ex.append("Resistance training: skeletal muscle is declining, so start (or restart) a structured program — "
                      "2 full-body sessions per week built on compound movements (squat, deadlift, press, row), "
                      "3–5 sets of 8–12 reps. Emphasize progressive overload and pair sessions with protein.")
        elif traj == "improving":
            ex.append("Resistance training: the current protocol is working — skeletal muscle is increasing. "
                      "Stay consistent, keep adding load or reps over time (progressive overload), and reassess at the next InBody.")
        elif traj == "plateau":
            ex.append("Resistance training: skeletal muscle has plateaued, so increase the stimulus — add a third session, "
                      "move to 4–5 sets, drop the rep range to 6–8 with heavier loads, or add drop sets and tempo work.")
        else:
            ex.append("Resistance training: build the foundation with 2 full-body sessions per week using compound "
                      "movements (squat, deadlift, press, row), 3–5 sets of 8–12 reps, adding load progressively.")
        if self.legs_lagging():
            ex.append("Lower body: segmental data shows the legs lagging. Make every session leg-first — squats, "
                      "Romanian deadlifts, lunges or split squats, and leg press — to bring both legs to at least 100% of ideal.")
        ex.append("VO₂ max intervals (e.g., 4 × 4 minutes hard with 3 minutes easy) can be added once the Zone 2 base is established.")

        protein = self.protein_g()
        nut = []
        if protein:
            nut.append(f"Protein target: 2 g per lb of skeletal muscle mass. SMM is {fmt(self.v('smm'))} lb → "
                       f"protein target is {protein} g/day.")
        nut.append("Distribute protein across 3–4 meals with at least 30 g per meal to maximize muscle protein "
                   "synthesis. Priority sources: whole eggs, whey, Greek yogurt, chicken, beef, and fish.")
        nut.append("Follow a Mediterranean framework — olive oil, nuts, fish, avocados, vegetables — and minimize "
                   "refined carbohydrates and fructose.")

        pbf, vfl = self.v("pbf"), self.v("vfl")
        metabolic = (pbf is not None and pbf > self.t["pbf_watch"]) or (vfl is not None and vfl >= 10)
        if metabolic:
            fast = ("Target a 14–18 hour daily fast. Given the current "
                    + ("body fat percentage" if pbf is not None and pbf > self.t["pbf_watch"] else "visceral fat level")
                    + ", work up to 18 hours (e.g., a 12pm–6pm eating window) once 16 hours feels comfortable. "
                      "Hit the protein target inside the eating window so muscle is protected while fat comes down.")
        else:
            fast = ("Target a 16-hour daily fast (e.g., a 10am–6pm eating window) within the 14–18 hour range. "
                    "Body composition is on track, so the goal is maintenance of metabolic flexibility — make sure "
                    "the full protein target still fits in the eating window.")

        assess = []
        if traj in ("declining", "plateau"):
            assess.append("whether skeletal muscle has resumed increasing")
        else:
            assess.append("whether skeletal muscle gains continue")
        if (self.d("bfm") or 0) < 0:
            assess.append("continued fat mass reduction")
        else:
            assess.append("body fat mass and percent")
        if vfl is not None and vfl > 6:
            assess.append(f"visceral fat progress toward ≤6 (currently {fmt(vfl, 0)})")
        if self.legs_lagging():
            assess.append("leg lean mass relative to 100% of ideal")
        ipa = self.interval("phase_angle")
        follow = [f"Next InBody: {self.next_scan_text()}; then every 6–8 weeks. At that visit, assess "
                  + ", ".join(assess[:-1]) + (" and " if len(assess) > 1 else "") + assess[-1] + "."]
        std = ("Standardize test conditions: morning, fasted, no exercise or caffeine beforehand, after voiding, "
               "same clothing.")
        if ipa is not None and ipa <= -0.8:
            std += (" This is especially important because phase angle dropped this interval — a controlled re-scan "
                    "will show whether that was hydration or a real change.")
        follow.append(std)

        return {"Exercise": ex, "Nutrition": nut, "Intermittent Fasting": [fast], "Follow-Up": follow}

    # ------------------------------------------------------------ summary

    def summary(self):
        dw, df, dm = self.d("weight"), self.d("bfm"), self.d("smm")
        paras = []
        if self.n == 1:
            p1 = (f"This baseline scan shows a body weight of {fmt(self.v('weight'))} lb with "
                  f"{fmt(self.v('smm'))} lb of skeletal muscle (the muscle you can train) and "
                  f"{fmt(self.v('bfm'))} lb of body fat, a body fat percentage of {fmt(self.v('pbf'))}%.")
            if self.v("inbody_score") is not None:
                p1 += f" The InBody Score — an overall body composition grade — is {fmt(self.v('inbody_score'), 0)}."
            paras.append(p1)
        elif self.recomposition():
            paras.append(f"The headline is true body recomposition: across {self.n} scans, body fat mass fell "
                         f"{fmt(abs(df))} lb while skeletal muscle rose {fmt(dm)} lb, with weight changing only "
                         f"{signed(dw)} lb. The scale hides this — fat is being replaced with metabolically active muscle.")
        elif df is not None and df < -0.5:
            paras.append(f"The headline is fat loss: body fat mass is down {fmt(abs(df))} lb from baseline "
                         f"({fmt(self.v('bfm', self.base))} → {fmt(self.v('bfm'))} lb), and body fat percentage moved "
                         f"from {fmt(self.v('pbf', self.base))}% to {fmt(self.v('pbf'))}%."
                         + (f" Skeletal muscle changed {signed(dm)} lb over the same period." if dm is not None else ""))
        elif dm is not None and dm > 0.3:
            paras.append(f"The headline is muscle gain: skeletal muscle is up {fmt(dm)} lb from baseline "
                         f"({fmt(self.v('smm', self.base))} → {fmt(self.v('smm'))} lb)"
                         + (f", and BMR (calories burned at rest) rose {fmt(self.d('bmr'), 0)} kcal/day." if (self.d('bmr') or 0) > 0 else "."))
        else:
            paras.append(f"Across {self.n} scans from {self.labels[0]} to {self.labels[-1]}, weight changed "
                         f"{signed(dw)} lb, body fat mass {signed(df)} lb, and skeletal muscle {signed(dm)} lb. "
                         f"Body composition has been largely stable, which gives a clear baseline to build from.")

        # paragraph 2: the longitudinal picture
        p2 = []
        if self.n > 1:
            p2.append(f"Over {self.months_span()} months and {self.n} scans, body fat percentage went from "
                      f"{fmt(self.v('pbf', self.base))}% to {fmt(self.v('pbf'))}% and the Visceral Fat Level "
                      f"(fat around the internal organs) from {fmt(self.v('vfl', self.base), 0)} to {fmt(self.v('vfl'), 0)}.")
        else:
            p2.append(f"Body fat is {fmt(self.v('pbf'))}% and the Visceral Fat Level (fat around the internal organs) "
                      f"is {fmt(self.v('vfl'), 0)}, where 1–9 is low risk and the target is 6 or below.")
        pa = self.v("phase_angle")
        if pa is not None:
            ipa = self.interval("phase_angle")
            if ipa is not None and ipa <= -0.8:
                p2.append(f"Phase angle — a measure of cell health and integrity — dropped {fmt(abs(ipa))}° this "
                          f"interval to {fmt(pa)}°. Single-interval swings this large are often driven by hydration "
                          f"or test conditions, so a controlled re-scan is the right next step before reading much into it.")
            else:
                status = ("below" if pa < self.t["pa_low"] else "above" if pa > self.t["pa_high"] else "within")
                p2.append(f"Phase angle — a measure of cell health and integrity — is {fmt(pa)}°, {status} the normal "
                          f"range of {self.t['pa_low']}–{self.t['pa_high']}°.")
        if self.legs_lagging():
            p2.append("Segmental analysis shows the legs lagging relative to ideal, which is the clearest place to focus training.")
        paras.append(" ".join(p2))

        protein = self.protein_g()
        start, end = self.next_scan_window()
        when = f"{md(start)} and {md(end)}"
        traj = self.smm_trajectory()
        focus = {"improving": "keep the resistance training that is clearly working",
                 "plateau": "push the resistance training stimulus a step further to restart muscle gain",
                 "declining": "rebuild muscle with consistent, progressive resistance training",
                 "baseline": "build a consistent resistance training habit"}[traj]
        z = self.zone2()
        p3 = "Going forward, the priorities are simple: "
        p3 += f"eat {protein} g of protein per day, " if protein else ""
        p3 += f"{focus}, and accumulate Zone 2 cardio"
        p3 += f" at {z[0]}–{z[1]} bpm" if z else ""
        p3 += (f". The next InBody scan (between {when}) will show how these changes are "
               f"taking hold. Every scan adds to the picture — consistency is what turns these numbers into lasting health.")
        paras.append(p3)
        return paras

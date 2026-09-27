"""Patient timeline: load/save JSON, recover history from previous HTML reports, merge new scans."""

import json
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from .schema import SEGMENTS

DATA_SCRIPT_ID = "inbody-data"


def empty_timeline():
    return {"version": 1, "patient": {}, "scans": []}


# ---------------------------------------------------------------- dates

def parse_date(text):
    """Accept ISO, m/d/yy, m/d/yyyy, 'Sep 5, 2025'. Returns ISO string or None."""
    if not text:
        return None
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y", "%m-%d-%Y", "%m.%d.%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def short_date(iso):
    d = date.fromisoformat(iso)
    return f"{d.month}/{d.day}/{d.strftime('%y')}"


# ---------------------------------------------------------------- JSON I/O

def load_json(path):
    data = json.loads(Path(path).read_text())
    if "scans" not in data:  # a single scan JSON
        return {"version": 1, "patient": {}, "scans": [data]}
    return data


def save_json(timeline, path):
    Path(path).write_text(json.dumps(timeline, indent=2) + "\n")


# ---------------------------------------------------------------- HTML history

class _ReportParser(HTMLParser):
    """Collects the pieces of an InBody HTML report needed to rebuild its timeline."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, classes, id)
        self.embedded = None
        self.nav_meta = ""
        self.hdr_sub = ""
        self.last_sec = ""
        self.tables = []  # (section heading, rows[list[str]])
        self._buf = None
        self._capture = None
        self._table = None
        self._row = None

    def _classes(self):
        return [c for _, cls, _ in self.stack for c in cls]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        self.stack.append((tag, classes, a.get("id")))
        if tag == "script" and a.get("id") == DATA_SCRIPT_ID:
            self._capture, self._buf = "embedded", []
        elif tag == "div" and "sec" in classes:
            self._capture, self._buf = "sec", []
        elif tag == "div" and "meta" in classes and "nav" in self._classes():
            self._capture, self._buf = "meta", []
        elif tag == "div" and "sub" in classes and "rpt-hdr" in self._classes():
            self._capture, self._buf = "hdr", []
        elif tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._capture, self._buf = "cell", []
        elif tag == "br" and self._buf is not None:
            self._buf.append(" ")

    def handle_endtag(self, tag):
        # pop to the matching tag (tolerates unclosed tags)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        text = " ".join("".join(self._buf or []).split())
        if tag == "script" and self._capture == "embedded":
            self.embedded = "".join(self._buf)
            self._capture = None
        elif tag == "div" and self._capture in ("sec", "meta", "hdr"):
            if self._capture == "sec":
                self.last_sec = text
            elif self._capture == "meta":
                self.nav_meta = text
            else:
                self.hdr_sub = text
            self._capture = None
        elif tag in ("td", "th") and self._capture == "cell":
            self._row.append(text)
            self._capture = None
        elif tag == "tr" and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append((self.last_sec, self._table))
            self._table = None

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)


_NUM = re.compile(r"-?\d+(?:\.\d+)?")

CORE_ROW_KEYS = {
    "weight": "weight",
    "skeletal muscle": "smm",
    "skeletal muscle mass": "smm",
    "smm": "smm",
    "body fat mass": "bfm",
    "body fat %": "pbf",
    "body fat percent": "pbf",
    "pbf": "pbf",
    "bmi": "bmi",
    "fat free mass": "ffm",
    "ffm": "ffm",
    "visceral fat level": "vfl",
    "visceral fat": "vfl",
    "smi": "smi",
    "ffmi": "ffmi",
    "fmi": "fmi",
    "smm/weight": "smm_wt",
    "smm/wt": "smm_wt",
    "bmr": "bmr",
    "phase angle": "phase_angle",
    "ecw/tbw": "ecw_tbw",
    "inbody score": "inbody_score",
    "total body water": "tbw",
    "intracellular water": "icw",
    "extracellular water": "ecw",
    "arm circumference": "arm_circumference",
}

SEGMENT_KEYS = {label.lower(): key for key, label in SEGMENTS}


def _numbers(text):
    return [float(n) for n in _NUM.findall(text.replace(",", ""))]


def _row_key(label):
    label = re.sub(r"\(.*?\)", "", label).strip().lower().rstrip(":")
    return label


def _parse_patient(nav_meta, hdr_sub):
    patient = {}
    parts = [p.strip() for p in nav_meta.split("·")]
    if parts and parts[0] and not parts[0].upper().startswith("ID"):
        patient["name"] = parts[0]
    m = re.search(r"\bID\s*[:#]?\s*([\w-]+)", nav_meta)
    if m:
        patient["patient_id"] = m.group(1)
    m = re.search(r"(\d{1,3})\s*(?:yo|y/o|-year-old|years? old)?\s*(Male|Female)\b", hdr_sub, re.I)
    if m:
        patient["age"] = int(m.group(1))
        patient["sex"] = m.group(2).capitalize()
    sub_parts = [p.strip() for p in hdr_sub.split("·")]
    if len(sub_parts) > 1 and re.search(r"\d", sub_parts[1]) and re.search(r"ft|in|'|\"|cm", sub_parts[1]):
        patient["height"] = sub_parts[1]
    m = re.search(r"InBody\s*\d+\w*", hdr_sub)
    if m:
        patient["device"] = m.group(0)
    return patient


def _timeline_from_tables(parser):
    scans = {}  # column index -> scan dict
    for sec, rows in parser.tables:
        if not rows:
            continue
        header = rows[0]
        cols = {}
        for i, cell in enumerate(header[1:], start=1):
            iso = parse_date(cell)
            if iso:
                cols[i] = iso
        if not cols:
            continue
        body = rows[1:]
        is_segmental = any(r and r[0].strip().lower() in SEGMENT_KEYS for r in body)
        seg_field = None
        if is_segmental:
            seg_field = "segmental_fat" if "fat" in sec.lower() else "segmental_lean"
        for row in body:
            if not row:
                continue
            for i, iso in cols.items():
                if i >= len(row):
                    continue
                scan = scans.setdefault(iso, {"test_date": iso})
                nums = _numbers(row[i])
                if is_segmental:
                    seg = SEGMENT_KEYS.get(row[0].strip().lower())
                    if seg and nums:
                        scan.setdefault(seg_field, {})[seg] = {
                            "lb": nums[0], "pct": nums[1] if len(nums) > 1 else None,
                        }
                else:
                    key = CORE_ROW_KEYS.get(_row_key(row[0]))
                    if key and nums:
                        scan[key] = nums[0]
    return [scans[k] for k in sorted(scans)]


def load_html(path):
    """Recover a timeline from a previous report.

    Reports produced by this program embed the full timeline as JSON. Older reports
    (e.g. made with the InBody skill in chat) are reconstructed from their metric tables.
    """
    parser = _ReportParser()
    parser.feed(Path(path).read_text(encoding="utf-8"))
    if parser.embedded:
        return json.loads(parser.embedded)
    scans = _timeline_from_tables(parser)
    if not scans:
        raise ValueError(f"No InBody scan data found in {path}")
    patient = _parse_patient(parser.nav_meta, parser.hdr_sub)
    for s in scans:
        s["source_file"] = Path(path).name
        s.setdefault("sex", patient.get("sex"))
    return {"version": 1, "patient": patient, "scans": scans}


def load_history(path):
    path = Path(path)
    if path.suffix.lower() in (".html", ".htm"):
        return load_html(path)
    return load_json(path)


# ---------------------------------------------------------------- merge

PATIENT_KEYS = ["name", "patient_id", "sex", "height", "age", "device"]


class PatientMismatch(ValueError):
    pass


def add_scan(timeline, scan, allow_mismatch=False):
    """Add or replace (same test date) a scan, keeping scans sorted. Returns 'added' or 'replaced'."""
    if not scan.get("test_date"):
        raise ValueError("Scan has no test_date; cannot place it on the timeline")
    known, new = (timeline.get("patient") or {}).get("patient_id"), scan.get("patient_id")
    if known and new and str(known).strip() != str(new).strip() and not allow_mismatch:
        raise PatientMismatch(f"Scan {scan['test_date']} is for patient ID {new}, but the timeline is for {known}")
    scans = timeline.setdefault("scans", [])
    status = "added"
    for i, existing in enumerate(scans):
        if existing.get("test_date") == scan["test_date"]:
            # Keep any fields the older record had that the new one lacks.
            merged = {**existing, **{k: v for k, v in scan.items() if v is not None}}
            scans[i] = merged
            status = "replaced"
            break
    else:
        scans.append(scan)
    scans.sort(key=lambda s: s["test_date"])
    _refresh_patient(timeline)
    return status


def merge_timelines(base, other, allow_mismatch=False):
    for scan in other.get("scans", []):
        add_scan(base, scan, allow_mismatch)
    for k, v in (other.get("patient") or {}).items():
        if v and not base["patient"].get(k):
            base["patient"][k] = v
    return base


def _refresh_patient(timeline):
    """Patient header fields follow the latest scan that reports them."""
    patient = timeline.setdefault("patient", {})
    for scan in timeline["scans"]:
        for key in PATIENT_KEYS:
            if scan.get(key) in (None, ""):
                continue
            # Identity fields stick to the first value seen; descriptive ones follow the latest scan.
            if key in ("name", "patient_id") and patient.get(key):
                continue
            patient[key] = scan[key]

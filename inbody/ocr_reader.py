"""Read an InBody 380 result sheet on this computer — no internet, no API.

A local text-recognition engine (RapidOCR) finds every piece of text on the page with its position.
Values are then picked out by where they sit on the standard InBody 380 layout, using the section
titles as anchors so small shifts between scans don't matter. The sheet prints several values twice
(weight, fat mass, fat-free mass), and those duplicates are cross-checked.
"""

import io
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .schema import SEGMENTS

PAGE_WIDTH = 1700  # all coordinates are normalized to a 1700-px-wide page (a 200 dpi letter scan)

_ENGINE = None


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    conf: float

    @property
    def yc(self):
        return (self.y0 + self.y1) / 2

    @property
    def key(self):
        return re.sub(r"[^a-z]", "", self.text.lower())


# ------------------------------------------------------------------ image + OCR

def load_image(path):
    """PIL image of the sheet. Scanned PDFs are read from their embedded page image."""
    from PIL import Image

    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return Image.open(path).convert("RGB")
    from pypdf import PdfReader

    page = PdfReader(str(path)).pages[0]
    images = list(page.images)
    if not images:
        raise ValueError(f"{path.name} has no scanned image in it. "
                         "Scan the sheet to PDF, or save it as a picture (PNG/JPG).")
    biggest = max(images, key=lambda im: len(im.data))
    return Image.open(io.BytesIO(biggest.data)).convert("RGB")


def run_ocr(image):
    """List of Box for every text fragment on the page."""
    global _ENGINE
    import numpy as np
    from rapidocr import RapidOCR

    if _ENGINE is None:
        _ENGINE = RapidOCR()
    scale = PAGE_WIDTH / image.width
    result = _ENGINE(np.array(image))
    boxes = []
    for pts, text, conf in zip(result.boxes, result.txts, result.scores):
        xs = [p[0] * scale for p in pts]
        ys = [p[1] * scale for p in pts]
        boxes.append(Box(min(xs), min(ys), max(xs), max(ys), text, float(conf)))
    return boxes


def boxes_from_json(items, image_width=PAGE_WIDTH):
    """Boxes from saved OCR output: [[points, text, conf], ...] (used by tests)."""
    scale = PAGE_WIDTH / image_width
    out = []
    for pts, text, conf in items:
        xs = [p[0] * scale for p in pts]
        ys = [p[1] * scale for p in pts]
        out.append(Box(min(xs), min(ys), max(xs), max(ys), text, float(conf)))
    return out


# ------------------------------------------------------------------ text helpers

def clean(text):
    text = text.translate(str.maketrans("（）［］，：～", "()[],:~"))
    text = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", text)  # "3. 9" -> "3.9"
    return text.strip()


_DEC = re.compile(r"^\(?-?\d+\.\d+\)?$")
_LB = re.compile(r"(\d+\.\d)\s*[1lI|]?\s*[bB]")  # "13.41b" = 13.4 lb (the "l" often reads as "1")


def decimal_value(box):
    t = clean(box.text)
    return float(t.strip("()")) if _DEC.match(t) else None


def first_number(text):
    m = re.search(r"-?\d+(?:\.\d+)?", clean(text))
    return float(m.group()) if m else None


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


class Page:
    def __init__(self, boxes, reread=None):
        self.boxes = sorted(boxes, key=lambda b: (b.y0, b.x0))
        self.notes = []
        # reread(x0, y0, x1, y1) -> [text]: OCR a small area again (the full-page pass
        # occasionally skips a number that touches a bar graph)
        self.reread = reread or (lambda *a: [])

    def find(self, label, x0=0, x1=PAGE_WIDTH, y0=0, y1=10_000, threshold=0.75):
        """Best box whose letters match `label` inside the region."""
        want = re.sub(r"[^a-z]", "", label.lower())
        best, score = None, threshold
        for b in self.boxes:
            if x0 <= b.x0 <= x1 and y0 <= b.y0 <= y1:
                s = similar(b.key, want)
                if s > score or (s == score and best is None):
                    best, score = b, s
        return best

    def region(self, x0, x1, y0, y1):
        return [b for b in self.boxes if x0 <= b.x0 < x1 and y0 <= b.yc < y1]

    def low_conf(self, box, what):
        if box is not None and box.conf < 0.85:
            self.notes.append(f"{what}: read as '{box.text}' with low confidence — please check")


def _without_scale_rows(boxes):
    """Drop the tick labels printed above each bar graph (rows of 4+ numbers at one height)."""
    numeric = [b for b in boxes if re.fullmatch(r"[\d.\s]+", clean(b.text))]
    ticks = set()
    for b in numeric:
        row = [o for o in numeric if abs(o.yc - b.yc) <= 7]
        if len(row) >= 4:
            ticks.update(id(o) for o in row)
    # a box holding several numbers (e.g. "22.025.030.0") is a merged scale label
    return [b for b in boxes if id(b) not in ticks and len(re.findall(r"\d+\.\d", clean(b.text))) <= 1]


def _rows(boxes, tol=14):
    rows = []
    for b in sorted(boxes, key=lambda b: b.yc):
        if rows and abs(rows[-1][0].yc - b.yc) <= tol:
            rows[-1].append(b)
        else:
            rows.append([b])
    return [sorted(r, key=lambda b: b.x0) for r in rows]


def _bar_values(page, y0, y1, count, what):
    """Decimal values printed at the end of the bar graphs between y0 and y1, top to bottom."""
    cands = _without_scale_rows(page.region(300, 1100, y0, y1))
    vals = [(b, decimal_value(b)) for b in cands]
    vals = [(b, v) for b, v in vals if v is not None]
    if len(vals) != count:
        page.notes.append(f"{what}: expected {count} values, found {len(vals)} — please check")
        return [None] * count
    for b, _ in vals:
        page.low_conf(b, what)
    return [v for _, v in vals]


# ------------------------------------------------------------------ parsing

def parse_page(boxes, reread=None):
    """Turn OCR boxes of an InBody 380 sheet into a scan dict (same fields as the Claude reader)."""
    p = Page(boxes, reread)
    scan = {"extraction_notes": p.notes, "device": "InBody 380"}
    L = 1100  # left/right column split

    # --- section anchors
    mf = p.find("Muscle-Fat Analysis", x1=400)
    ob = p.find("Obesity Analysis", x1=400)
    sl = p.find("Segmental Lean Analysis", x1=400)
    ew = p.find("ECW/TBW-Phase Angle", x1=400)
    hist = p.find("Body Composition History", x1=400)
    if not all((mf, ob, sl, ew)):
        raise ValueError("This doesn't look like an InBody 380 result sheet (section titles not found)")
    hist_y = hist.y0 if hist else ew.y0 + 200

    # --- header: ID, height, age, gender, test date/time
    hdr = {k: p.find(k, x1=L, y1=mf.y0) for k in ("ID", "Height", "Age", "Gender", "Test Date / Time")}
    if hdr["ID"]:
        row = [b for b in p.region(0, L, hdr["ID"].y1 + 5, hdr["ID"].y1 + 80)]
        cols = sorted((b for b in hdr.values() if b), key=lambda b: b.x0)
        for b in row:
            col = min(cols, key=lambda c: abs(c.x0 - b.x0))
            name = next(k for k, v in hdr.items() if v is col)
            t = clean(b.text)
            if name == "ID":
                scan["patient_id"] = t
            elif name == "Height":
                m = re.match(r"(\d+)\s*ft\s*(\d+(?:\.\d+)?)\s*in", t.replace(" ", ""))
                scan["height"] = f"{m.group(1)} ft {float(m.group(2)):g} in" if m else t
            elif name == "Age":
                scan["age"] = int(first_number(t)) if first_number(t) is not None else None
            elif name == "Gender":
                scan["sex"] = "Female" if t.lower().startswith("f") else "Male"
            else:
                m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})\.?\s*(\d{2}:\d{2})?", t)
                if m:
                    scan["test_date"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                    scan["test_time"] = m.group(4)
    if not scan.get("test_date"):
        p.notes.append("Test date not found")

    # --- body composition analysis (top block)
    top = p.find("Intracellular Water", x1=400, y1=mf.y0)
    y_top = (top.y0 - 20) if top else mf.y0 - 280
    left_vals = [(b, decimal_value(b)) for b in p.region(300, 520, y_top, mf.y0)]
    left_vals = [(b, v) for b, v in left_vals if v is not None]
    if len(left_vals) == 4:
        for key, (b, v) in zip(("icw", "ecw", "dry_lean_mass", "bfm"), left_vals):
            scan[key] = v
            p.low_conf(b, key)
    else:
        p.notes.append(f"Body composition values: expected 4, found {len(left_vals)} — please check")
    for key, rng, label, default_x in (("tbw", "tbw_range", "Total Body Water", 506),
                                       ("ffm", "ffm_range", "Fat Free Mass", 706),
                                       ("weight", "weight_range", "Weight", 932)):
        h = p.find(label, x0=400, x1=L, y1=mf.y0)
        hx = h.x0 if h else default_x
        col = p.region(hx - 60, hx + 170, y_top, mf.y0)
        vals = [b for b in col if decimal_value(b) is not None and "(" not in b.text]
        ranges = [b for b in col if "~" in clean(b.text)]
        if vals:
            scan[key] = decimal_value(vals[0])
            p.low_conf(vals[0], key)
        if ranges:
            scan[rng] = clean(ranges[0].text).strip("()")

    # --- bar graphs
    w, smm, bfm = _bar_values(p, mf.y1, ob.y0, 3, "Muscle-Fat Analysis")
    scan["smm"] = smm
    for key, dup in (("weight", w), ("bfm", bfm)):
        if dup is not None and scan.get(key) is not None and abs(dup - scan[key]) > 0.15:
            p.notes.append(f"{key} reads {scan[key]} in one place and {dup} in another — please check")
        scan.setdefault(key, dup)
    scan["bmi"], scan["pbf"] = _bar_values(p, ob.y1, sl.y0, 2, "Obesity Analysis")
    seg = _bar_values(p, sl.y1 + 30, ew.y0, 10, "Segmental Lean Analysis")
    scan["segmental_lean"] = {k: {"lb": seg[2 * i], "pct": seg[2 * i + 1]} for i, (k, _) in enumerate(SEGMENTS)}

    # --- ECW/TBW and phase angle
    ecw_vals = [b for b in _without_scale_rows(p.region(300, 950, ew.y1 + 30, hist_y))
                if re.fullmatch(r"0\.\d{3}", clean(b.text))]
    scan["ecw_tbw"] = float(clean(ecw_vals[0].text)) if ecw_vals else None
    pa = [b for b in p.region(900, L, ew.y1 + 30, hist_y) if re.match(r"\d+\.\d", clean(b.text))]
    scan["phase_angle"] = first_number(pa[0].text) if pa else None

    # --- right column
    def between(a, b, x0=L):
        ya = a.y1 if a else 0
        yb = b.y0 if b else 10_000
        return p.region(x0, PAGE_WIDTH, ya, yb)

    score_h = p.find("InBody Score", x0=L)
    smi_h = p.find("SMI", x0=L, y0=score_h.y1 if score_h else 0)
    ctrl_h = p.find("Body Fat - Fat Free Mass Control", x0=L)
    fat_h = p.find("Segmental Fat Analysis", x0=L)
    vfl_h = p.find("Visceral Fat Level", x0=L)
    bmr_h = p.find("Basal Metabolic Rate", x0=L)
    res_h = p.find("Research Parameters", x0=L)
    imp_h = p.find("Impedance", x0=L)

    ints = [b for b in between(score_h, smi_h) if re.fullmatch(r"\d{2,3}", clean(b.text))]
    scan["inbody_score"] = int(clean(ints[0].text)) if ints else None
    smi = [b for b in between(smi_h, ctrl_h) if "kg" in b.text.lower()]
    scan["smi"] = first_number(smi[0].text) if smi else None

    fat = {}
    fat_boxes = [b for b in between(fat_h, vfl_h) if b.x0 > (fat_h.x0 if fat_h else L) + 100]
    fat_rows = [r for r in _rows(fat_boxes)
                if re.search(r"\d\.\d\s*%|\d\.\d\s*[1lI|]?\s*[bB]", clean(" ".join(b.text for b in r)))]
    if len(fat_rows) == 5:
        for (key, _), row in zip(SEGMENTS, fat_rows):
            text = clean(" ".join(b.text for b in row))
            lb = _LB.search(text)
            pct = re.search(r"(\d+\.\d)\s*%", text)
            if not (lb and pct):
                y0, y1 = min(b.y0 for b in row) - 8, max(b.y1 for b in row) + 8
                text = clean(" ".join(p.reread(row[0].x0 - 5, y0, PAGE_WIDTH, y1)))
                lb = lb or _LB.search(text)
                pct = pct or re.search(r"(\d+\.\d)\s*%", text)
            fat[key] = {"lb": float(lb.group(1)) if lb else None, "pct": float(pct.group(1)) if pct else None}
    else:
        p.notes.append(f"Segmental Fat Analysis: expected 5 rows, found {len(fat_rows)} — please check")
    scan["segmental_fat"] = fat

    vfl = [re.search(r"Level\s*(\d+)", b.text, re.I) for b in between(vfl_h, bmr_h)]
    vfl = [m for m in vfl if m]
    scan["vfl"] = int(vfl[0].group(1)) if vfl else None

    bmr_boxes = between(bmr_h, res_h)
    kcal = [b for b in bmr_boxes if "kcal" in b.text.lower()]
    if kcal:
        m = re.search(r"(\d{3,4})\s*kcal", clean(kcal[0].text))
        if not m:
            left = [b for b in bmr_boxes if abs(b.yc - kcal[0].yc) < 25 and b.x1 <= kcal[0].x0 + 5
                    and re.fullmatch(r"\d{3,4}", clean(b.text))]
            scan["bmr"] = float(clean(left[-1].text)) if left else None
        else:
            scan["bmr"] = float(m.group(1))
        rng = re.findall(r"\d{4}", " ".join(b.text for b in bmr_boxes if b.yc < kcal[0].yc - 10))
        if len(rng) >= 2:
            scan["bmr_range"] = f"{rng[0]}~{rng[1]}"

    params = {"fatfreemass": "ffm_research", "armcircumference": "arm_circumference", "ffmi": "ffmi",
              "fmi": "fmi", "smmwt": "smm_wt"}
    for row in _rows(between(res_h, imp_h)):
        label = row[0]
        key = max(params, key=lambda k: similar(label.key, k))
        if similar(label.key, key) < 0.6:
            continue
        text = clean(" ".join(b.text for b in row[1:]))
        if params[key] == "ffm_research":
            m = _LB.search(text) or re.search(r"(\d+\.\d)", text)
            val = float(m.group(1)) if m else None
            if val is not None and scan.get("ffm") is not None and abs(val - scan["ffm"]) > 0.15:
                p.notes.append(f"Fat-free mass reads {scan['ffm']} and {val} — please check")
            scan.setdefault("ffm", val)
        else:
            scan[params[key]] = first_number(text)

    for key in ("weight", "smm", "bfm", "pbf", "ffm", "inbody_score", "vfl", "phase_angle", "ecw_tbw", "bmr"):
        if scan.get(key) is None:
            p.notes.append(f"{key} not found on the sheet — please check")
    return scan


def _rereader(image):
    import numpy as np

    scale = image.width / PAGE_WIDTH

    def reread(x0, y0, x1, y1):
        crop = image.crop((int(x0 * scale), int(y0 * scale), int(x1 * scale), int(y1 * scale)))
        crop = crop.resize((crop.width * 2, crop.height * 2))
        result = _ENGINE(np.array(crop))
        return list(result.txts or [])

    return reread


def read_scan(path):
    """Scan dict for one InBody sheet (PDF or picture), read entirely on this computer."""
    image = load_image(path)
    scan = parse_page(run_ocr(image), reread=_rereader(image))
    scan["source_file"] = Path(path).name
    return scan

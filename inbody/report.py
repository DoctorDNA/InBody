"""Render the self-contained HTML report (inline SVG charts, no external dependencies).

The full timeline is embedded as JSON so the report itself can be fed back in as history.
"""

import json
from html import escape

from .analysis import Analysis, classify, digits_for, fmt, mdy, signed
from .schema import SEGMENTS
from .timeline import DATA_SCRIPT_ID

CSS = """
:root {
  --bg:#0f1117; --card:#161b27; --border:#1F2937;
  --accent:#00BFFF; --text:#FFFFFF; --muted:#94A3B8;
  --green-bg:#064E3B; --green-text:#6EE7B7;
  --red-bg:#450A0A; --red-text:#FCA5A5;
  --yellow-bg:#451a03; --yellow-text:#FDE68A;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;line-height:1.6}
.nav{position:sticky;top:0;z-index:100;background:#0a0d14;border-bottom:1px solid var(--border);padding:10px 24px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px}
.nav .logo{color:var(--accent);font-weight:700;font-size:15px;letter-spacing:.5px}
.nav .meta{color:var(--muted);font-size:12px}
.wrap{max-width:1150px;margin:0 auto;padding:28px 20px 60px}
.rpt-hdr{margin-bottom:28px;border-bottom:1px solid var(--border);padding-bottom:20px}
.rpt-hdr h1{font-size:24px;font-weight:700}
.rpt-hdr .sub{color:var(--muted);font-size:13px;margin-top:4px}
.sec{font-size:12px;font-weight:600;color:var(--accent);text-transform:uppercase;letter-spacing:1px;margin:32px 0 14px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
@media(max-width:700px){.cards{grid-template-columns:repeat(2,1fr)}}
.sc{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 14px;display:flex;flex-direction:column;gap:5px}
.sc .lbl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.8px}
.sc .val{font-size:26px;font-weight:700;line-height:1.1}
.sc .sub{font-size:12px;color:var(--muted)}
.bdg{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;margin-top:3px;width:fit-content}
.g{background:var(--green-bg);color:var(--green-text)}
.r{background:var(--red-bg);color:var(--red-text)}
.f{background:#1F2937;color:var(--muted)}
.w{background:var(--yellow-bg);color:var(--yellow-text)}
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:800px){.chart-grid{grid-template-columns:1fr}}
.cc{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px}
.cc .ct{font-size:13px;font-weight:600;margin-bottom:10px}
.cc svg{width:100%;height:210px;display:block}
.twrap{overflow-x:auto}
table.mt{width:100%;border-collapse:collapse;font-size:12.5px;background:var(--card);border-radius:10px;overflow:hidden}
table.mt th,table.mt td{padding:9px 11px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}
table.mt th{background:#0a0d14;color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
td.mn{color:var(--accent);font-weight:600}
td.dg{color:var(--green-text);font-weight:600}
td.dr{color:var(--red-text);font-weight:600}
td.dm{color:var(--muted)}
.finds{display:grid;gap:12px}
.find{background:var(--card);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:8px;padding:14px 16px}
.find.win{border-left-color:#10B981}
.find.watch{border-left-color:#F59E0B}
.find.act{border-left-color:#EF4444}
.ft{font-weight:600;font-size:14px;margin-bottom:4px}
.fb{font-size:13px;color:#CBD5E1}
.recs{display:grid;gap:24px}
.rec-group h3{font-size:13px;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border)}
.rec-group p{font-size:13px;color:#CBD5E1;line-height:1.75;margin-bottom:8px}
.rec-group p:last-child{margin-bottom:0}
.summ{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:22px 24px;line-height:1.8;font-size:14px}
.summ p{margin-bottom:14px}
.summ p:last-child{margin-bottom:0}
.footer{margin-top:40px;padding-top:20px;border-top:1px solid var(--border);color:var(--muted);font-size:12px;text-align:center}
@media print{
  .nav{display:none}
  body{background:white!important;color:black!important}
  .sc,.find,.cc,.summ{break-inside:avoid}
  table{font-size:10px}
}
"""

CORE_ROWS = [
    ("weight", "Weight (lb)"), ("smm", "Skeletal Muscle (lb)"), ("bfm", "Body Fat Mass (lb)"),
    ("pbf", "Body Fat %"), ("bmi", "BMI (kg/m²)"), ("ffm", "Fat Free Mass (lb)"),
    ("vfl", "Visceral Fat Level"), ("smi", "SMI (kg/m²)"), ("ffmi", "FFMI (kg/m²)"),
    ("fmi", "FMI (kg/m²)"), ("smm_wt", "SMM/Weight (%)"), ("bmr", "BMR (kcal)"),
    ("phase_angle", "Phase Angle (°)"), ("ecw_tbw", "ECW/TBW"), ("inbody_score", "InBody Score"),
]

REVIEWER = "Jeff Reid, DO"


# ------------------------------------------------------------------ charts

def _chart(title, labels, values, color, digits=1, zones=(), floor=None, ceil=None, terminal=None):
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return f'<div class="cc"><div class="ct">{escape(title)}</div><p class="sub" style="color:var(--muted)">Not enough data.</p></div>'
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.25, abs(hi) * 0.02, 0.5)
    y_min, y_max = lo - pad, hi + pad
    if floor is not None:
        y_min = min(y_min, floor)
    if ceil is not None:
        y_max = max(y_max, ceil)
    if digits == 0:
        y_min, y_max = max(0, int(y_min)), int(y_max + 0.999)
        if y_max - y_min < 4:
            y_max = y_min + 4

    def y(v):
        return 190 - (v - y_min) / (y_max - y_min) * 160

    n = len(values)
    xs = [60 + (416 * i / (n - 1) if n > 1 else 208) for i in range(n)]
    out = [f'<svg viewBox="0 0 520 210" preserveAspectRatio="none" role="img" aria-label="{escape(title)} trend">']
    for lo_z, hi_z, fill, text in zones:
        a = max(y_min, lo_z if lo_z is not None else y_min)
        b = min(y_max, hi_z if hi_z is not None else y_max)
        if b > a:
            out.append(f'<rect x="60" y="{y(b):.1f}" width="416" height="{y(a) - y(b):.1f}" fill="{fill}" opacity="0.07"/>')
            out.append(f'<text x="472" y="{y(b) + 10:.1f}" text-anchor="end" font-size="8" fill="{fill}">{escape(text)}</text>')
    for i, gy in enumerate((30, 70, 110, 150, 190)):
        val = y_max - (y_max - y_min) * i / 4
        out.append(f'<line x1="50" y1="{gy}" x2="490" y2="{gy}" stroke="#1F2937" stroke-width="1"/>')
        out.append(f'<text x="44" y="{gy + 3}" text-anchor="end" font-size="9" fill="#94A3B8">{fmt(val, 0 if digits == 0 else 1)}</text>')
    poly = " ".join(f"{xs[i]:.1f},{y(v):.1f}" for i, v in pts)
    out.append(f'<polyline points="{poly}" stroke="{color}" stroke-width="2.5" fill="none" stroke-linejoin="round"/>')
    show_all = n <= 10
    for k, (i, v) in enumerate(pts):
        last = k == len(pts) - 1
        dot = (terminal or color) if last else color
        out.append(f'<circle cx="{xs[i]:.1f}" cy="{y(v):.1f}" r="{5 if last else 3.5}" fill="{dot}"/>')
        if show_all or last or k == 0:
            weight = ' font-weight="600"' if last else ""
            out.append(f'<text x="{xs[i]:.1f}" y="{y(v) - 9:.1f}" text-anchor="middle" font-size="{10 if last else 9}" '
                       f'fill="#FFFFFF"{weight}>{fmt(v, digits)}</text>')
    step = max(1, (n + 11) // 12)
    for i, lab in enumerate(labels):
        if i % step == 0 or i == n - 1:
            out.append(f'<text x="{xs[i]:.1f}" y="205" text-anchor="middle" font-size="8" fill="#94A3B8">{escape(lab)}</text>')
    out.append("</svg>")
    return f'<div class="cc"><div class="ct">{escape(title)}</div>{"".join(out)}</div>'


def _charts(a):
    if a.n < 2:
        return ('<div class="cc"><div class="ct">Trends</div>'
                '<p style="color:var(--muted)">Trend charts require 2 or more scans.</p></div>')
    t = a.t
    pbf = a.v("pbf")
    vfl = a.v("vfl")
    green, red = "#10B981", "#EF4444"
    charts = [
        _chart("Weight (lb)", a.labels, a.series("weight"), "#00BFFF"),
        _chart("Skeletal Muscle Mass (lb)", a.labels, a.series("smm"), "#10B981"),
        _chart("Body Fat Percent (%)", a.labels, a.series("pbf"), "#F59E0B",
               zones=[(None, t["pbf_watch"], green, f"healthy ≤{t['pbf_watch']}%")],
               terminal=(green if pbf is not None and pbf <= t["pbf_watch"] else red if pbf is not None and pbf > t["pbf_act"] else None)),
        _chart("Visceral Fat Level", a.labels, a.series("vfl"), "#F59E0B", digits=0,
               zones=[(None, 6, green, "target ≤6"), (10, None, red, "elevated ≥10")], floor=1, ceil=11,
               terminal=(green if vfl is not None and vfl <= 6 else red if vfl is not None and vfl >= 10 else None)),
    ]
    return f'<div class="chart-grid">{"".join(charts)}</div>'


# ------------------------------------------------------------------ tables

def _delta_td(key, d, digits):
    cls = {"good": "dg", "bad": "dr", "flat": "dm", "neutral": "dm"}[classify(key, d)]
    return f'<td class="{cls}">{signed(d, digits)}</td>'


def _core_table(a):
    head = "".join(f"<th>{escape(l)}</th>" for l in a.labels)
    rows = []
    for key, label in CORE_ROWS:
        vals = a.series(key)
        if all(v is None for v in vals):
            continue
        dg = digits_for(key)
        cells = "".join(f"<td>{fmt(v, dg)}</td>" for v in vals[:-1])
        cells += f'<td class="mn">{fmt(vals[-1], dg)}</td>'
        rows.append(f"<tr><td>{escape(label)}</td>{cells}{_delta_td(key, a.d(key), dg)}</tr>")
    return (f'<div class="twrap"><table class="mt"><thead><tr><th>Metric</th>{head}<th>Δ Total</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _seg_table(a, field, with_pct, direction):
    head = "".join(f"<th>{escape(l)}</th>" for l in a.labels)
    rows = []
    for key, label in SEGMENTS:
        cells = []
        lbs = []
        for i, scan in enumerate(a.scans):
            seg = (scan.get(field) or {}).get(key) or {}
            lb, pct = seg.get("lb"), seg.get("pct")
            lbs.append(lb)
            text = fmt(lb, 2 if lb is not None and round(lb, 1) != round(lb, 2) else 1)
            if with_pct and pct is not None:
                text += f" ({fmt(pct)}%)"
            elif not with_pct and pct is not None:
                text += f" <span style=\"color:var(--muted)\">({fmt(pct)}%)</span>"
            low = with_pct and "leg" in key and pct is not None and pct < 100
            cls = ' class="mn"' if i == len(a.scans) - 1 else ""
            style = ' style="color:var(--red-text)"' if low else ""
            cells.append(f"<td{cls}{style}>{text}</td>")
        known = [x for x in lbs if x is not None]
        d = round(known[-1] - known[0], 2) if len(known) >= 2 else None
        if d is None or abs(d) < 0.2:
            dcls = "dm"
        else:
            dcls = "dg" if d * direction > 0 else "dr"
        rows.append(f'<tr><td>{label}</td>{"".join(cells)}<td class="{dcls}">{signed(d)}</td></tr>')
    if not any(scan.get(field) for scan in a.scans):
        return '<p style="color:var(--muted)">No segmental data recorded.</p>'
    return (f'<div class="twrap"><table class="mt"><thead><tr><th>Region</th>{head}<th>Δ Total (lb)</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


# ------------------------------------------------------------------ page

def render(timeline, summary_override=None, generated=None):
    a = Analysis(timeline, generated=generated)
    p = a.patient
    name = p.get("name") or ""
    pid = p.get("patient_id") or "—"
    who_id = " · ".join(x for x in (name, f"ID {pid}" if pid != "—" else "") if x) or "Patient"
    gen = a.generated
    span = f"{a.labels[0]} – {a.labels[-1]}" if a.n > 1 else a.labels[0]
    device = p.get("device") or a.latest.get("device") or "InBody"
    who = " ".join(x for x in [f"{a.age}" if a.age else "", a.sex] if x)
    months = f" over {a.months_span()} months" if a.n > 1 else ""

    cards = "".join(
        f'<div class="sc"><div class="lbl">{escape(c["label"])}</div><div class="val">{escape(c["value"])}</div>'
        f'<div class="sub">{escape(c["sub"])}</div><span class="bdg {c["cls"]}">{escape(c["badge"])}</span></div>'
        for c in a.cards())
    finds = "".join(
        f'<div class="find {cls}"><div class="ft">{icon} {escape(title)}</div><div class="fb">{escape(body)}</div></div>'
        for cls, icon, title, body in a.findings())
    recs = "".join(
        f'<div class="rec-group"><h3>{escape(h)}</h3>{"".join(f"<p>{escape(x)}</p>" for x in paras)}</div>'
        for h, paras in a.recommendations().items())
    summary = summary_override or a.summary()
    summ = "".join(f"<p>{escape(x)}</p>" for x in summary)

    data = json.dumps(timeline, indent=None, separators=(",", ":")).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>InBody Report · {escape(who_id)} · {escape(a.labels[-1])}</title>
<style>{CSS}</style>
</head>
<body>
<div class="nav">
  <div class="logo">MORPHEUS PRECISION HEALTH · InBody Longitudinal</div>
  <div class="meta">{escape(who_id)} · {a.n} scan{"s" if a.n != 1 else ""} · {escape(span)}</div>
</div>
<div class="wrap">
  <div class="rpt-hdr">
    <h1>InBody Body Composition Report</h1>
    <div class="sub">{escape(who)} · {escape(p.get("height") or "height —")} · {escape(device)} · {a.n} scan{"s" if a.n != 1 else ""}{months} · Generated {mdy(gen)} · Reviewed by {REVIEWER}</div>
  </div>

  <div class="sec">Headline Metrics</div>
  <div class="cards">{cards}</div>

  <div class="sec">Trends</div>
  {_charts(a)}

  <div class="sec">Core Metrics</div>
  {_core_table(a)}

  <div class="sec">Segmental Lean Analysis (lb, % of ideal)</div>
  {_seg_table(a, "segmental_lean", True, 1)}

  <div class="sec">Segmental Fat Analysis (lb)</div>
  {_seg_table(a, "segmental_fat", False, -1)}

  <div class="sec">Key Findings &amp; Opportunities</div>
  <div class="finds">{finds}</div>

  <div class="sec">Recommendations</div>
  <div class="recs">{recs}</div>

  <div class="sec">Summary</div>
  <div class="summ">{summ}</div>

  <div class="footer">
    Generated by Morpheus Precision Health · {mdy(gen)} · {escape(who_id)} · {a.n} scan{"s" if a.n != 1 else ""} · Reviewed by {REVIEWER}
  </div>
</div>
<script type="application/json" id="{DATA_SCRIPT_ID}">{data}</script>
</body>
</html>
"""

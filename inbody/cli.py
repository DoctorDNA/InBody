"""Command line interface.

Examples:
  # New scan, no history yet
  python -m inbody analyze scan.pdf --name "Jane Doe"

  # Add the latest scan to a previous report (HTML from this tool or from the InBody skill)
  python -m inbody analyze latest.pdf --history old_report.html

  # Rebuild a report from a saved timeline
  python -m inbody render patients/jane/timeline.json
"""

import argparse
import sys
from pathlib import Path

from . import extract, report, timeline as tl


def _load_input(path, model):
    """A scan file becomes a timeline with one scan; JSON/HTML are loaded as timelines."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm", ".json"):
        return tl.load_history(path)
    print(f"Reading {path.name} with Claude…", file=sys.stderr)
    scan = extract.extract_scan(path, model=model)
    return {"version": 1, "patient": {}, "scans": [scan]}


def _write_outputs(timeline, out_html, out_json, ai, model):
    summary = None
    if ai:
        from .narrative import ai_summary
        print("Writing summary with Claude…", file=sys.stderr)
        summary = ai_summary(timeline, model=model)
        if summary is None:
            print("  AI summary unavailable; using the built-in summary.", file=sys.stderr)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(report.render(timeline, summary_override=summary), encoding="utf-8")
    if out_json:
        tl.save_json(timeline, out_json)
    print(f"Report:   {out_html}")
    if out_json:
        print(f"Timeline: {out_json}")
    return out_html


def _default_out(timeline, out_dir="reports"):
    p = timeline.get("patient", {})
    slug = (p.get("name") or p.get("patient_id") or "patient").strip().lower().replace(" ", "_")
    last = timeline["scans"][-1]["test_date"]
    return Path(out_dir) / f"inbody_{slug}_{last}.html"


def cmd_analyze(args):
    timeline = tl.empty_timeline()
    for h in args.history or []:
        tl.merge_timelines(timeline, tl.load_history(h), args.force)
        print(f"History:  {h} → {len(timeline['scans'])} scan(s)", file=sys.stderr)

    warnings = []
    for f in args.scans:
        new = _load_input(f, args.model)
        for scan in new["scans"]:
            for w in extract.validate_scan(scan):
                warnings.append(f"{Path(f).name}: {w}")
                print(f"  ⚠ {Path(f).name}: {w}", file=sys.stderr)
            try:
                status = tl.add_scan(timeline, scan, args.force)
            except tl.PatientMismatch as e:
                confirm = getattr(args, "confirm_mismatch", None)
                if not (confirm and confirm(str(e))):
                    sys.exit(f"{e}. Use --force if this is really the same patient.")
                status = tl.add_scan(timeline, scan, allow_mismatch=True)
            print(f"Scan {scan.get('test_date')}: {status}", file=sys.stderr)
        for k, v in (new.get("patient") or {}).items():
            if v and not timeline["patient"].get(k):
                timeline["patient"][k] = v

    _apply_overrides(timeline, args)
    if not timeline["scans"]:
        sys.exit("No scans to analyze.")
    out_html = Path(args.output) if args.output else _default_out(timeline, args.out_dir)
    out_json = Path(args.timeline) if args.timeline else out_html.with_suffix(".json")
    return _write_outputs(timeline, out_html, out_json, args.ai_summary, args.model), warnings


def cmd_render(args):
    timeline = tl.load_history(args.source)
    _apply_overrides(timeline, args)
    out_html = Path(args.output) if args.output else _default_out(timeline, args.out_dir)
    return _write_outputs(timeline, out_html, None, args.ai_summary, args.model), []


def cmd_extract(args):
    """Extract one scan to JSON without building a report (for review/correction)."""
    scan = extract.extract_scan(args.scan, model=args.model)
    for w in extract.validate_scan(scan):
        print(f"  ⚠ {w}", file=sys.stderr)
    out = Path(args.output) if args.output else Path(args.scan).with_suffix(".json")
    tl.save_json(scan, out)
    print(f"Scan data: {out}")


def _apply_overrides(timeline, args):
    p = timeline.setdefault("patient", {})
    for key in ("name", "patient_id", "sex", "height"):
        val = getattr(args, key, None)
        if val:
            p[key] = val
    if getattr(args, "age", None):
        p["age"] = args.age
        timeline["scans"][-1]["age"] = args.age


def _common(sp):
    sp.add_argument("-o", "--output", help="Output HTML path (default: <out-dir>/inbody_<patient>_<date>.html)")
    sp.add_argument("--out-dir", default="reports", help="Folder for reports when -o is not given (default: reports)")
    sp.add_argument("--name", help="Patient name (InBody sheets often only show an ID)")
    sp.add_argument("--patient-id", dest="patient_id")
    sp.add_argument("--sex", choices=["Male", "Female"])
    sp.add_argument("--age", type=int)
    sp.add_argument("--height")
    sp.add_argument("--ai-summary", action="store_true", help="Have Claude write the Summary section")
    sp.add_argument("--model", default=extract.MODEL, help=f"Claude model (default {extract.MODEL})")


def main(argv=None, confirm_mismatch=None):
    ap = argparse.ArgumentParser(prog="inbody", description="InBody longitudinal analysis & HTML reports")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="Add scan(s) to the timeline and generate a report")
    a.add_argument("scans", nargs="*", help="InBody PDF/PNG/JPG sheets, or scan JSON files")
    a.add_argument("--history", action="append",
                   help="Previous report (.html) or timeline (.json). Repeatable.")
    a.add_argument("--force", action="store_true", help="Allow scans whose patient ID differs from the history")
    a.add_argument("--timeline", help="Where to save the updated timeline JSON (default: next to the report)")
    _common(a)
    a.set_defaults(func=cmd_analyze)

    r = sub.add_parser("render", help="Regenerate a report from a timeline JSON or previous report")
    r.add_argument("source")
    _common(r)
    r.set_defaults(func=cmd_render)

    e = sub.add_parser("extract", help="Extract one sheet to JSON only")
    e.add_argument("scan")
    e.add_argument("-o", "--output")
    e.add_argument("--model", default=extract.MODEL)
    e.set_defaults(func=cmd_extract)

    args = ap.parse_args(argv)
    args.confirm_mismatch = confirm_mismatch
    return args.func(args)


if __name__ == "__main__":
    main()

"""Read an InBody result sheet (PDF or image) with Claude and return structured scan data.

Values are read directly from the sheet by the model (no OCR), then cross-validated
with the physical relationships InBody values must satisfy.
"""

import base64
import json
import mimetypes
from pathlib import Path

from .schema import extraction_schema

MODEL = "claude-opus-5"

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}

SYSTEM_PROMPT = """You extract data from InBody body composition result sheets (typically InBody 380/570/770).
Read every value directly from the sheet. Use pounds, inches, and the units printed on the sheet.
Rules:
- If the sheet contains multiple scans or a history panel, extract ONLY the current/main test (the one in the header).
- Segmental Lean Analysis: record lb and the % of ideal printed with it for each of the five segments.
- Segmental Fat Analysis: record lb and the % printed with it.
- Research Parameters: FFM, arm circumference, FFMI, FMI, SMM/WT (%).
- Normal ranges: copy as printed (e.g. "128.6~174.0").
- test_date must be ISO format YYYY-MM-DD.
- If a value is not on the sheet, use null. If a value is hard to read, give your best reading and add a note to extraction_notes. Never invent values."""


def _content_block(path: Path):
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    media = IMAGE_TYPES.get(suffix) or mimetypes.guess_type(path.name)[0]
    if not media or not media.startswith("image/"):
        raise ValueError(f"Unsupported file type: {path.name} (use PDF, PNG, JPG, WEBP)")
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def extract_scan(path, model=MODEL, client=None):
    """Send one InBody PDF/image to Claude and return the extracted scan dict."""
    path = Path(path)
    if client is None:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("Reading with Claude needs the Anthropic package: "
                               "pip install -r requirements-claude.txt")
        client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": extraction_schema()}},
        messages=[{
            "role": "user",
            "content": [
                _content_block(path),
                {"type": "text", "text": "Extract all data from this InBody result sheet."},
            ],
        }],
        # Re-run on Anthropic's recommended fallback model if the request is declined.
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined to read {path.name}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"Extraction of {path.name} was cut off (max_tokens)")
    text = next(b.text for b in response.content if b.type == "text")
    scan = json.loads(text)
    scan["source_file"] = path.name
    return scan


def validate_scan(scan):
    """Cross-check extracted values. Returns a list of human-readable warnings."""
    warnings = []

    def close(a, b, tol):
        return a is None or b is None or abs(a - b) <= tol

    w, ffm, bfm = scan.get("weight"), scan.get("ffm"), scan.get("bfm")
    if None not in (w, ffm, bfm) and not close(w, ffm + bfm, 0.6):
        warnings.append(f"Weight {w} ≠ FFM {ffm} + BFM {bfm} ({ffm + bfm:.1f})")
    tbw, icw, ecw = scan.get("tbw"), scan.get("icw"), scan.get("ecw")
    if None not in (tbw, icw, ecw) and not close(tbw, icw + ecw, 0.6):
        warnings.append(f"TBW {tbw} ≠ ICW {icw} + ECW {ecw} ({icw + ecw:.1f})")
    ratio = scan.get("ecw_tbw")
    if ratio is not None and not 0.34 <= ratio <= 0.42:
        warnings.append(f"ECW/TBW {ratio} is outside the plausible 0.34–0.42 range — check the reading")
    smm, smm_wt = scan.get("smm"), scan.get("smm_wt")
    if None not in (smm, smm_wt, w) and not close(smm, smm_wt * w / 100, 1.0):
        warnings.append(f"SMM {smm} ≠ SMM/WT {smm_wt}% × weight {w} ({smm_wt * w / 100:.1f})")
    if not scan.get("test_date"):
        warnings.append("No test date found — set it manually in the timeline JSON")
    for note in scan.get("extraction_notes") or []:
        warnings.append(f"Extraction note: {note}")
    return warnings

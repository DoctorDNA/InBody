"""Optional: have Claude write the 3-paragraph Summary from the computed analysis."""

import json

from .analysis import Analysis
from .extract import MODEL

SYSTEM = """You write the Summary section of an InBody body composition report for a precision-medicine clinic.
Write exactly three paragraphs:
1. Headline achievement — lead with the single strongest win, fully quantified.
2. What the complete longitudinal picture shows — consistency, trajectory, notable interval events; contextualize anomalies (phase angle swings, leg lean dips, etc.).
3. Going-forward priorities — the protein target in grams, training focus, next scan plan, closing encouragement.
Rules: never use any names (no patient or physician names); address the reader as "you" or use clinical third person.
Warm clinical tone for both patient and physician. Define any jargon inline in plain language.
Do not recommend creatine or any supplements. Use only numbers present in the data provided."""


def ai_summary(timeline, model=MODEL, client=None):
    import anthropic

    a = Analysis(timeline)
    payload = {
        "sex": a.sex,
        "age": a.age,
        "scan_dates": a.labels,
        "metrics": {k: a.series(k) for k in ("weight", "smm", "bfm", "pbf", "vfl", "smi", "phase_angle",
                                              "ecw_tbw", "inbody_score", "bmr", "ffm")},
        "segmental_lean_latest": a.latest.get("segmental_lean"),
        "findings": [{"type": c, "title": t, "detail": b} for c, _, t, b in a.findings()],
        "protein_target_g": a.protein_g(),
        "zone2_bpm": a.zone2(),
        "next_scan_window": [d.isoformat() for d in a.next_scan_window()],
    }
    client = client or anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": {
            "type": "object",
            "properties": {"paragraphs": {"type": "array", "items": {"type": "string"}}},
            "required": ["paragraphs"],
            "additionalProperties": False,
        }}},
        messages=[{"role": "user", "content": "Analysis data:\n" + json.dumps(payload, indent=1)}],
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    text = next(b.text for b in response.content if b.type == "text")
    paras = json.loads(text)["paragraphs"]
    return paras[:3] if len(paras) >= 3 else None

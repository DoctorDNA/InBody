"""Data model for a single InBody scan and the JSON schema used for extraction."""

SEGMENTS = [
    ("right_arm", "Right Arm"),
    ("left_arm", "Left Arm"),
    ("trunk", "Trunk"),
    ("right_leg", "Right Leg"),
    ("left_leg", "Left Leg"),
]

# Numeric scan fields: key -> (label, unit, direction)
# direction: +1 = higher is better, -1 = lower is better, 0 = neutral / judgment
NUMERIC_FIELDS = {
    "weight": ("Weight", "lb", 0),
    "icw": ("Intracellular Water", "lb", 0),
    "ecw": ("Extracellular Water", "lb", 0),
    "tbw": ("Total Body Water", "lb", 0),
    "dry_lean_mass": ("Dry Lean Mass", "lb", 1),
    "ffm": ("Fat Free Mass", "lb", 1),
    "bfm": ("Body Fat Mass", "lb", -1),
    "smm": ("Skeletal Muscle Mass", "lb", 1),
    "bmi": ("BMI", "kg/m²", -1),
    "pbf": ("Body Fat %", "%", -1),
    "ecw_tbw": ("ECW/TBW", "", -1),
    "phase_angle": ("Phase Angle", "°", 1),
    "inbody_score": ("InBody Score", "", 1),
    "smi": ("SMI", "kg/m²", 1),
    "vfl": ("Visceral Fat Level", "", -1),
    "bmr": ("BMR", "kcal", 1),
    "arm_circumference": ("Arm Circumference", "in", 0),
    "ffmi": ("FFMI", "kg/m²", 1),
    "fmi": ("FMI", "kg/m²", -1),
    "smm_wt": ("SMM/Weight", "%", 1),
}

RANGE_FIELDS = ["weight_range", "tbw_range", "ffm_range", "bmr_range"]

HEADER_FIELDS = ["patient_id", "name", "height", "age", "sex", "test_date", "test_time", "device"]


def _num():
    return {"type": ["number", "null"]}


def _str():
    return {"type": ["string", "null"]}


def _segment_obj(pct_desc):
    return {
        "type": "object",
        "properties": {
            key: {
                "type": "object",
                "properties": {"lb": _num(), "pct": {"type": ["number", "null"], "description": pct_desc}},
                "required": ["lb", "pct"],
                "additionalProperties": False,
            }
            for key, _ in SEGMENTS
        },
        "required": [k for k, _ in SEGMENTS],
        "additionalProperties": False,
    }


def extraction_schema():
    """JSON schema passed to Claude's structured outputs for one scan."""
    props = {
        "patient_id": _str(),
        "name": {"type": ["string", "null"], "description": "Patient name if printed on the sheet"},
        "height": {"type": ["string", "null"], "description": "Height exactly as printed, e.g. 5ft 10.0in"},
        "age": {"type": ["integer", "null"]},
        "sex": {"type": ["string", "null"], "description": "Exactly 'Male' or 'Female'"},
        "test_date": {"type": ["string", "null"], "description": "Test date as ISO YYYY-MM-DD"},
        "test_time": _str(),
        "device": {"type": ["string", "null"], "description": "Device model, e.g. InBody 380"},
    }
    for key, (label, unit, _) in NUMERIC_FIELDS.items():
        props[key] = {"type": ["number", "null"], "description": f"{label} ({unit})" if unit else label}
    for key in RANGE_FIELDS:
        props[key] = {"type": ["string", "null"], "description": "Normal range as printed, e.g. 128.6~174.0"}
    props["segmental_lean"] = _segment_obj("% of ideal, as printed under the lb value")
    props["segmental_fat"] = _segment_obj("% as printed under the lb value")
    props["extraction_notes"] = {
        "type": "array",
        "items": {"type": "string"},
        "description": "Any values that were unclear, illegible, or missing",
    }
    return {
        "type": "object",
        "properties": props,
        "required": list(props.keys()),
        "additionalProperties": False,
    }

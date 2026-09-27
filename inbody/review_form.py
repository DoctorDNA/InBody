"""A small window to check and correct values read from a sheet, shown only when a check fails."""

from .schema import NUMERIC_FIELDS, SEGMENTS

FIELDS = ["weight", "smm", "bfm", "pbf", "bmi", "ffm", "icw", "ecw", "tbw", "dry_lean_mass", "vfl",
          "inbody_score", "smi", "ffmi", "fmi", "smm_wt", "bmr", "phase_angle", "ecw_tbw", "arm_circumference"]


def _to_number(text):
    text = text.strip().replace(",", "")
    if not text:
        return None
    return float(text)


def review(root, scan, problems, filename):
    """Show the values next to the problems found. Returns the corrected scan, or None if cancelled."""
    import tkinter as tk
    from tkinter import messagebox

    win = tk.Toplevel(root)
    win.title(f"Check values — {filename}")
    win.attributes("-topmost", True)
    win.grab_set()

    msg = ("Some values didn't pass the consistency checks. Compare them with the printed sheet, "
           "fix any that are wrong, then click Continue.\n\n• " + "\n• ".join(problems))
    tk.Label(win, text=msg, justify="left", fg="#B00020", wraplength=760).grid(
        row=0, column=0, columnspan=6, sticky="w", padx=12, pady=(12, 8))

    entries = {}
    tk.Label(win, text="Test date (YYYY-MM-DD)").grid(row=1, column=0, sticky="e", padx=(12, 4), pady=2)
    e = tk.Entry(win, width=12)
    e.insert(0, scan.get("test_date") or "")
    e.grid(row=1, column=1, sticky="w", pady=2)
    entries["test_date"] = e

    for i, key in enumerate(FIELDS):
        label, unit, _ = NUMERIC_FIELDS[key]
        r, c = 2 + i // 3, (i % 3) * 2
        tk.Label(win, text=f"{label}{' (' + unit + ')' if unit else ''}").grid(
            row=r, column=c, sticky="e", padx=(12, 4), pady=2)
        e = tk.Entry(win, width=9)
        if scan.get(key) is not None:
            e.insert(0, f"{scan[key]:g}")
        e.grid(row=r, column=c + 1, sticky="w", pady=2)
        entries[key] = e

    row = 3 + len(FIELDS) // 3
    for c, text in ((1, "Segmental lean: lb / % of ideal"), (3, "Segmental fat: lb / %")):
        tk.Label(win, text=text, font=("Segoe UI", 9, "bold")).grid(
            row=row, column=c, columnspan=2, sticky="w", pady=(10, 2))
    for j, (seg, label) in enumerate(SEGMENTS):
        r = row + 1 + j
        tk.Label(win, text=label).grid(row=r, column=0, sticky="e", padx=(12, 4))
        for c, field in ((1, "segmental_lean"), (3, "segmental_fat")):
            frame = tk.Frame(win)
            frame.grid(row=r, column=c, columnspan=2, sticky="w")
            for part in ("lb", "pct"):
                e = tk.Entry(frame, width=7)
                val = ((scan.get(field) or {}).get(seg) or {}).get(part)
                if val is not None:
                    e.insert(0, f"{val:g}")
                e.pack(side="left", padx=2)
                entries[(field, seg, part)] = e

    result = {}

    def done(ok):
        if ok:
            try:
                updated = dict(scan)
                updated["test_date"] = entries["test_date"].get().strip() or None
                for key in FIELDS:
                    updated[key] = _to_number(entries[key].get())
                for field in ("segmental_lean", "segmental_fat"):
                    updated[field] = {seg: {part: _to_number(entries[(field, seg, part)].get())
                                            for part in ("lb", "pct")} for seg, _ in SEGMENTS}
                updated["extraction_notes"] = []  # reviewed by a person
            except ValueError:
                messagebox.showerror("Check values", "Please enter numbers only (e.g. 76.7).", parent=win)
                return
            result["scan"] = updated
        win.destroy()

    buttons = tk.Frame(win)
    buttons.grid(row=row + 7, column=0, columnspan=6, pady=12)
    tk.Button(buttons, text="Continue", width=12, command=lambda: done(True)).pack(side="left", padx=6)
    tk.Button(buttons, text="Cancel", width=12, command=lambda: done(False)).pack(side="left", padx=6)
    win.protocol("WM_DELETE_WINDOW", lambda: done(False))
    root.wait_window(win)
    return result.get("scan")

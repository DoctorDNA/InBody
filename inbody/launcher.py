"""Point-and-click front end used by "InBody Report.bat".

Files dropped on the .bat arrive as arguments; anything missing is asked for with file dialogs.
The finished report opens in the default browser.
"""

import os
import sys
import traceback
import webbrowser
from pathlib import Path

HISTORY_TYPES = {".html", ".htm"}
SCAN_TYPES = [("InBody scan", "*.pdf *.png *.jpg *.jpeg *.webp"), ("All files", "*.*")]
REPORT_TYPES = [("InBody report or timeline", "*.html *.htm *.json"), ("All files", "*.*")]


def _key_file():
    base = os.environ.get("APPDATA") or Path.home()
    return Path(base) / "InBody" / "api_key.txt"


def _ensure_api_key(ask):
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    kf = _key_file()
    if kf.exists():
        key = kf.read_text(encoding="utf-8").strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
            return True
    key = ask("Anthropic API key",
              "Paste your Anthropic API key (starts with sk-ant-).\n"
              "It is saved on this computer so you only enter it once.", show="*")
    if not key:
        return False
    kf.parent.mkdir(parents=True, exist_ok=True)
    kf.write_text(key.strip(), encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key.strip()
    return True


def main(argv=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    def ask(title, prompt, show=None):
        return simpledialog.askstring(title, prompt, parent=root, show=show)

    reports_dir = Path.cwd() / "reports"
    reports_dir.mkdir(exist_ok=True)

    dropped = [Path(a) for a in (argv if argv is not None else sys.argv[1:])]
    history = [p for p in dropped if p.suffix.lower() in HISTORY_TYPES]
    scans = [p for p in dropped if p.suffix.lower() not in HISTORY_TYPES]

    if not scans:
        picked = filedialog.askopenfilenames(parent=root, title="Choose the new InBody scan (PDF or picture)",
                                             filetypes=SCAN_TYPES)
        scans = [Path(p) for p in picked]
        if not scans:
            return 0

    name = None
    if not history:
        answer = messagebox.askyesnocancel(
            "Previous report?",
            "Does this patient already have an InBody report?\n\n"
            "Yes — choose their most recent report and the new scan will be added to it.\n"
            "No — this is the patient's first scan.",
            parent=root)
        if answer is None:
            return 0
        if answer:
            picked = filedialog.askopenfilename(parent=root, title="Choose the patient's most recent InBody report",
                                                initialdir=str(reports_dir), filetypes=REPORT_TYPES)
            if not picked:
                return 0
            history = [Path(picked)]
        else:
            name = ask("Patient name", "Patient name for the report (optional):")

    needs_claude = any(p.suffix.lower() not in (".json",) for p in scans)
    if needs_claude and not _ensure_api_key(ask):
        messagebox.showinfo("InBody", "An API key is needed to read the scan.", parent=root)
        return 1

    argv = ["analyze", *map(str, scans)]
    for h in history:
        argv += ["--history", str(h)]
    if name:
        argv += ["--name", name]

    from . import cli
    print("Working… this usually takes under a minute per scan.\n")
    try:
        out, warnings = cli.main(argv)
    except SystemExit as e:  # cli reports problems (e.g. patient ID mismatch) via sys.exit
        messagebox.showerror("InBody", str(e.code), parent=root)
        return 1
    except Exception as e:
        traceback.print_exc()
        msg = str(e)
        if type(e).__name__ == "AuthenticationError":
            _key_file().unlink(missing_ok=True)
            msg = "The API key was rejected. Run again and paste a valid key."
        messagebox.showerror("InBody", f"Something went wrong:\n\n{msg}", parent=root)
        return 1

    webbrowser.open(Path(out).resolve().as_uri())
    text = f"Report saved to:\n{Path(out).resolve()}\n\nIt is opening in your browser."
    if warnings:
        text += ("\n\nPlease double-check these values against the sheet:\n• "
                 + "\n• ".join(warnings[:8]))
    messagebox.showinfo("InBody report ready", text, parent=root)
    return 0


if __name__ == "__main__":
    sys.exit(main())

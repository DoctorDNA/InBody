"""Point-and-click front end used by "InBody Report.bat".

Files dropped on the .bat arrive as arguments; anything missing is asked for with file dialogs.
The finished report opens in the default browser.
"""

import sys
import traceback
import webbrowser
from pathlib import Path

HISTORY_TYPES = {".html", ".htm"}
SCAN_TYPES = [("InBody scan", "*.pdf *.png *.jpg *.jpeg *.webp"), ("All files", "*.*")]
REPORT_TYPES = [("Previous InBody report", "*.html *.htm"), ("All files", "*.*")]


def _writable(folder):
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def reports_folder():
    """'reports' next to the program if Windows allows writing there, else one in the user's home folder."""
    for folder in (Path.cwd() / "reports", Path.home() / "InBody Reports"):
        if _writable(folder):
            return folder
    raise OSError("No writable folder for reports")


def _split(paths):
    """Previous reports (.html) vs new scans (PDF/pictures/JSON)."""
    history = [p for p in paths if p.suffix.lower() in HISTORY_TYPES]
    scans = [p for p in paths if p.suffix.lower() not in HISTORY_TYPES]
    return history, scans


def main(argv=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    reports_dir = reports_folder()

    dropped = [Path(a) for a in (argv if argv is not None else sys.argv[1:])]
    history, scans = _split(dropped)

    # Step 1: the previous report. Cancel = no previous report (first scan).
    if not history:
        picked = filedialog.askopenfilenames(
            parent=root, title="Step 1 of 2: choose the PREVIOUS InBody report (.html) — Cancel if there is none",
            filetypes=REPORT_TYPES)
        more_history, more_scans = _split([Path(p) for p in picked])
        history += more_history
        scans += more_scans

    # Step 2: the new InBody PDF.
    if not scans:
        picked = filedialog.askopenfilenames(
            parent=root, title="Step 2 of 2: choose the NEW InBody report (PDF)", filetypes=SCAN_TYPES)
        more_history, more_scans = _split([Path(p) for p in picked])
        history += more_history
        scans += more_scans
        if not scans:
            return 0

    argv = ["analyze", *map(str, scans), "--out-dir", str(reports_dir)]
    for h in history:
        argv += ["--history", str(h)]

    from . import cli
    print("Working… reading each scan takes about 10–20 seconds.\n")

    def confirm_mismatch(problem):
        return messagebox.askyesno("Different patient ID?", f"{problem}.\n\nAdd it to this report anyway?",
                                   parent=root)

    def review(scan, problems, filename):
        from .review_form import review as show_form
        return show_form(root, scan, problems, filename)

    try:
        out, warnings = cli.main(argv, confirm_mismatch=confirm_mismatch, review=review)
    except SystemExit as e:  # cli reports problems via sys.exit
        messagebox.showerror("InBody", str(e.code), parent=root)
        return 1
    except Exception as e:
        traceback.print_exc()
        messagebox.showerror("InBody", f"Something went wrong:\n\n{e}", parent=root)
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

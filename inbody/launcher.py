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
REPORT_TYPES = [("Previous InBody report", "*.html *.htm"), ("All files", "*.*")]


def _key_file():
    base = os.environ.get("APPDATA") or Path.home()
    return Path(base) / "InBody" / "api_key.txt"


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


def _split(paths):
    """Previous reports (.html) vs new scans (PDF/pictures/JSON)."""
    history = [p for p in paths if p.suffix.lower() in HISTORY_TYPES]
    scans = [p for p in paths if p.suffix.lower() not in HISTORY_TYPES]
    return history, scans


def main(argv=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    def ask(title, prompt, show=None):
        return simpledialog.askstring(title, prompt, parent=root, show=show)

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

    needs_claude = any(p.suffix.lower() not in (".json",) for p in scans)
    if needs_claude and not _ensure_api_key(ask):
        messagebox.showinfo("InBody", "An API key is needed to read the scan.", parent=root)
        return 1

    argv = ["analyze", *map(str, scans), "--out-dir", str(reports_dir)]
    for h in history:
        argv += ["--history", str(h)]

    from . import cli
    print("Working… this usually takes under a minute per scan.\n")
    def confirm_mismatch(problem):
        return messagebox.askyesno("Different patient ID?", f"{problem}.\n\nAdd it to this report anyway?",
                                   parent=root)

    try:
        out, warnings = cli.main(argv, confirm_mismatch=confirm_mismatch)
    except SystemExit as e:  # cli reports problems via sys.exit
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

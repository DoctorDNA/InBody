"""Drive the point-and-click launcher with scripted dialog answers (no display needed)."""
import json
import sys
import types
from pathlib import Path

import pytest

EX = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def fake_tk(monkeypatch, tmp_path):
    answers = {"files": [], "file": "", "yesno": None, "string": None}
    shown = []

    class Tk:
        def withdraw(self): pass
        def attributes(self, *a): pass

    tk = types.ModuleType("tkinter")
    tk.Tk = Tk
    fd = types.ModuleType("tkinter.filedialog")
    fd.askopenfilenames = lambda **k: answers["files"]
    fd.askopenfilename = lambda **k: answers["file"]
    mb = types.ModuleType("tkinter.messagebox")
    mb.askyesnocancel = lambda *a, **k: answers["yesno"]
    mb.showinfo = lambda title, text, **k: shown.append(("info", text))
    mb.showerror = lambda title, text, **k: shown.append(("error", text))
    sd = types.ModuleType("tkinter.simpledialog")
    sd.askstring = lambda *a, **k: answers["string"]
    tk.filedialog, tk.messagebox, tk.simpledialog = fd, mb, sd
    for name, mod in {"tkinter": tk, "tkinter.filedialog": fd, "tkinter.messagebox": mb,
                      "tkinter.simpledialog": sd}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    monkeypatch.chdir(tmp_path)
    return answers, shown, opened


def test_new_patient_then_follow_up(fake_tk, tmp_path):
    from inbody import launcher
    answers, shown, opened = fake_tk
    first = tmp_path / "first.json"
    first.write_text((EX / "sample_scan_2025-12-02.json").read_text())

    answers.update(files=[str(first)], yesno=False, string="Sample Patient")
    assert launcher.main([]) == 0
    reports = sorted((tmp_path / "reports").glob("*.html"))
    assert [r.name for r in reports] == ["inbody_sample_patient_2025-12-02.html"]
    assert opened and shown[-1][0] == "info"

    # Return visit: drag the new scan onto the .bat, pick the last report in the dialog.
    answers.update(yesno=True, file=str(reports[0]))
    assert launcher.main([str(EX / "sample_new_scan.json")]) == 0
    latest = tmp_path / "reports" / "inbody_sample_patient_2026-01-14.html"
    assert latest.exists() and "2 scans" in latest.read_text(encoding="utf-8")


def test_cancel_does_nothing(fake_tk, tmp_path):
    from inbody import launcher
    answers, shown, opened = fake_tk
    assert launcher.main([]) == 0
    assert not opened and not shown


def test_patient_mismatch_is_reported(fake_tk, tmp_path):
    from inbody import launcher
    answers, shown, opened = fake_tk
    other = tmp_path / "other.json"
    other.write_text(json.dumps({**json.loads((EX / "sample_new_scan.json").read_text()), "patient_id": "X-9"}))
    assert launcher.main([str(other), str(EX / "sample_report.html")]) == 1
    assert shown[-1][0] == "error" and "X-9" in shown[-1][1]

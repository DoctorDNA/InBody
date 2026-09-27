"""Drive the point-and-click launcher with scripted dialog answers (no display needed)."""
import json
import sys
import types
from pathlib import Path

import pytest

EX = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def fake_tk(monkeypatch, tmp_path):
    state = {"pickers": [], "yesno": True, "titles": []}
    shown = []

    class Tk:
        def withdraw(self): pass
        def attributes(self, *a): pass

    def askopenfilenames(**k):
        state["titles"].append(k["title"])
        return state["pickers"].pop(0) if state["pickers"] else ""

    tk = types.ModuleType("tkinter")
    tk.Tk = Tk
    fd = types.ModuleType("tkinter.filedialog")
    fd.askopenfilenames = askopenfilenames
    mb = types.ModuleType("tkinter.messagebox")
    mb.askyesno = lambda *a, **k: state["yesno"]
    mb.showinfo = lambda title, text, **k: shown.append(("info", text))
    mb.showerror = lambda title, text, **k: shown.append(("error", text))
    sd = types.ModuleType("tkinter.simpledialog")
    sd.askstring = lambda *a, **k: pytest.fail("should not ask for text")
    tk.filedialog, tk.messagebox, tk.simpledialog = fd, mb, sd
    for name, mod in {"tkinter": tk, "tkinter.filedialog": fd, "tkinter.messagebox": mb,
                      "tkinter.simpledialog": sd}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    monkeypatch.chdir(tmp_path)
    return state, shown, opened


def test_previous_html_plus_new_scan(fake_tk, tmp_path):
    """Step 1 picks the old HTML report, step 2 the new scan → one updated report."""
    from inbody import launcher
    state, shown, opened = fake_tk
    state["pickers"] = [(str(EX / "sample_report.html"),), (str(EX / "sample_new_scan.json"),)]
    # sample_report already contains 1/14/26; use a later date so it is a genuinely new visit
    new = tmp_path / "new.json"
    new.write_text(json.dumps({**json.loads((EX / "sample_new_scan.json").read_text()), "test_date": "2026-03-01"}))
    state["pickers"][1] = (str(new),)
    assert launcher.main([]) == 0
    assert "PREVIOUS" in state["titles"][0] and "NEW" in state["titles"][1]
    out = tmp_path / "reports" / "inbody_sample_patient_2026-03-01.html"
    html = out.read_text(encoding="utf-8")
    assert "5 scans" in html and "Sample Patient" in html
    assert opened and shown[-1][0] == "info"


def test_both_files_selected_in_one_picker(fake_tk, tmp_path):
    from inbody import launcher
    state, shown, opened = fake_tk
    state["pickers"] = [(str(EX / "sample_timeline.json"), str(EX / "sample_report.html"))]
    assert launcher.main([]) == 0
    assert len(state["titles"]) == 1  # step 2 skipped


def test_no_previous_report_first_scan(fake_tk, tmp_path):
    from inbody import launcher
    state, shown, opened = fake_tk
    state["pickers"] = ["", (str(EX / "sample_new_scan.json"),)]  # cancel step 1
    assert launcher.main([]) == 0
    assert list((tmp_path / "reports").glob("inbody_demo-001_2026-01-14.html"))


def test_drag_and_drop_both_skips_pickers(fake_tk, tmp_path):
    from inbody import launcher
    state, shown, opened = fake_tk
    assert launcher.main([str(EX / "sample_report.html"), str(EX / "sample_new_scan.json")]) == 0
    assert state["titles"] == []


def test_cancel_everything_does_nothing(fake_tk):
    from inbody import launcher
    state, shown, opened = fake_tk
    assert launcher.main([]) == 0
    assert not opened and not shown


def test_patient_mismatch_asks_once(fake_tk, tmp_path):
    from inbody import launcher
    state, shown, opened = fake_tk
    other = tmp_path / "other.json"
    other.write_text(json.dumps({**json.loads((EX / "sample_new_scan.json").read_text()),
                                 "patient_id": "X-9", "test_date": "2026-03-01"}))
    state["yesno"] = False
    assert launcher.main([str(EX / "sample_report.html"), str(other)]) == 1
    state["yesno"] = True
    assert launcher.main([str(EX / "sample_report.html"), str(other)]) == 0


def test_reports_fall_back_when_program_folder_is_read_only(fake_tk, tmp_path, monkeypatch):
    from inbody import launcher
    state, shown, opened = fake_tk
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    real = launcher._writable
    monkeypatch.setattr(launcher, "_writable", lambda f: f.parent != tmp_path and real(f))
    state["pickers"] = [""]
    assert launcher.main([str(EX / "sample_new_scan.json")]) == 0
    assert list((home / "InBody Reports").glob("*.html"))
    assert str(home / "InBody Reports") in shown[-1][1]


def test_new_report_from_several_scans_then_follow_up(fake_tk, tmp_path):
    """Cancel step 1, pick two scans → new report; next visit: that report + one new scan."""
    from inbody import launcher
    state, shown, opened = fake_tk
    base = json.loads((EX / "sample_new_scan.json").read_text())
    files = []
    for d in ("2026-03-01", "2026-01-14", "2026-04-20"):
        f = tmp_path / f"{d}.json"
        f.write_text(json.dumps({**base, "test_date": d}))
        files.append(str(f))
    state["pickers"] = ["", (files[0], files[1])]  # picked out of date order
    assert launcher.main([]) == 0
    first = tmp_path / "reports" / "inbody_demo-001_2026-03-01.html"
    assert "2 scans" in first.read_text(encoding="utf-8")

    state["pickers"] = [(str(first),), (files[2],)]
    assert launcher.main([]) == 0
    from inbody.timeline import load_html
    latest = tmp_path / "reports" / "inbody_demo-001_2026-04-20.html"
    assert "3 scans" in latest.read_text(encoding="utf-8")
    assert [s["test_date"] for s in load_html(latest)["scans"]] == ["2026-01-14", "2026-03-01", "2026-04-20"]

# InBody Longitudinal Analysis

Turns InBody result sheets (PDF or photo/scan) into the Morpheus Precision Health longitudinal
HTML report — the same layout, thresholds and rules as the InBody analysis skill — and keeps a
running timeline for each patient.

- **Reads the sheet with Claude.** Values are read straight from the PDF/image, not OCR'd, then
  cross-checked (Weight = FFM + BFM, TBW = ICW + ECW, ECW/TBW range, SMM/WT%).
- **Analyzes the timeline.** Interval and total deltas, sex-specific flags, findings (wins → watch → action),
  protein target, Zone 2 heart rate, fasting window, next-scan timing, and a three-paragraph summary.
- **Writes a self-contained HTML report.** Inline SVG charts and no external files. Open it in a browser
  and use Ctrl/Cmd+P → Save as PDF.
- **Every report carries its own data.** The full timeline is embedded in the HTML, so last visit's
  report *is* the history for the next one. Reports made earlier by the InBody skill in chat work too:
  their tables are parsed back into scans.

## Windows: double-click

1. Install Python from [python.org](https://www.python.org/downloads/windows/) and tick **"Add python.exe to PATH"** (one time).
2. Unzip this folder anywhere and double-click **`InBody Report.bat`**.
   - The first run takes about a minute to set up.
   - It asks for your Anthropic API key once and saves it in `%APPDATA%\InBody\api_key.txt`.
3. Choose the new InBody PDF, or a photo of the sheet.
4. When it asks "Does this patient already have an InBody report?":
   - **Yes:** choose their last report. The new scan is added and the new report covers every visit.
   - **No:** type the patient's name.
5. The report opens in your browser and is saved in the `reports` folder next to the `.bat`.
   If Windows won't allow writing there, it goes to `InBody Reports` in your user folder instead,
   and the pop-up shows exactly where.

The Python setup lives in `%LOCALAPPDATA%\InBody\venv`, not in the program folder, so the program can
sit on any drive, including protected or synced folders. To reset it, delete that folder.

You can also drag PDFs onto `InBody Report.bat`, optionally together with the patient's last report.
If Claude has to guess at a value, a pop-up lists it so you can check it against the sheet.

## Command line setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # needed to read PDFs/images
```

## Usage

**First scan for a patient:**
```bash
python -m inbody analyze scan_2025-09-05.pdf --name "Jane Doe"
# → reports/inbody_jane_doe_2025-09-05.html  (+ .json timeline next to it)
```

**Add the newest scan to an existing report** (a previous report from this tool *or* from the InBody skill):
```bash
python -m inbody analyze latest_scan.pdf --history reports/inbody_jane_doe_2025-12-02.html
```
The previous scans are recovered from the HTML, the new sheet is read and added, and a new report
covering every scan is written. You can pass several `--history` files and several scan files at once.
A scan with the same test date as an existing one replaces it. A scan whose patient ID doesn't match
the history is rejected unless you pass `--force`.

**Other commands:**
```bash
python -m inbody extract scan.pdf            # sheet → scan.json only, to review or correct values
python -m inbody analyze scan.json --history old.html   # use a corrected JSON instead of the PDF
python -m inbody render reports/…json        # rebuild a report from a timeline JSON or report HTML
```

**Options:** `--name`, `--patient-id`, `--sex Male|Female`, `--age`, `--height` (fill in or override
what's on the sheet), `-o report.html`, `--timeline timeline.json`, `--ai-summary` (Claude writes the
Summary section instead of the built-in template), `--model` (default `claude-opus-5`).

Extraction warnings (for example a value that fails the Weight = FFM + BFM check) are printed. When you
see one, run `extract`, fix the JSON, and analyze from the JSON.

## Privacy

`reports/`, `patients/` and `*.pdf` are git-ignored so patient data isn't committed. When you use a
PDF, it is sent to the Anthropic API to be read.

## Layout

| File | Purpose |
|---|---|
| `inbody/extract.py` | Claude reads a PDF/image into structured JSON, plus consistency checks |
| `inbody/timeline.py` | Timeline JSON, recovering history from HTML reports, merging scans |
| `inbody/analysis.py` | Deltas, clinical thresholds, findings, recommendations, summary |
| `inbody/report.py` | HTML/CSS/SVG rendering (skill design system) |
| `inbody/narrative.py` | Optional Claude-written summary |
| `inbody/launcher.py`, `InBody Report.bat` | Double-click Windows front end (file pickers, opens the report) |
| `examples/` | Sample data for a fictional patient |
| `tests/` | `python -m pytest` |

# InBody Longitudinal Analysis

Turns InBody result sheets (PDF or photo/scan) into the Morpheus Precision Health longitudinal
HTML report — the same layout, thresholds and rules as the InBody analysis skill — and keeps a
running timeline for each patient.

- **Reads the sheet on your computer, with no internet or API key.** A local text-recognition engine
  reads the InBody 380 sheet, whether a scanned PDF or a photo. Each value is found by its position on
  the standard layout, then cross-checked: Weight = FFM + BFM, TBW = ICW + ECW, the ECW/TBW range,
  SMM/WT%, and the values the sheet prints twice. If a check fails, a form opens so you can fix the
  value before the report is made. Reading with Claude is still available as an option (`--reader claude`).
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
   - The first run takes a few minutes to set up and needs internet. After that it works offline.
3. **Step 1:** choose the patient's previous InBody report (`.html`). This can be a report from this
   program or one the InBody skill made in chat. Press **Cancel** if it's the patient's first scan.
4. **Step 2:** choose the new InBody PDF, or a photo of the sheet.
5. The report opens in your browser and is saved in the `reports` folder next to the `.bat`.
   If Windows won't allow writing there, it goes to `InBody Reports` in your user folder instead,
   and the pop-up shows exactly where.

The Python setup lives in `%LOCALAPPDATA%\InBody\venv`, not in the program folder, so the program can
sit on any drive, including protected or synced folders. To reset it, delete that folder.

You can also select both files at once in Step 1 (hold Ctrl), or drag the HTML and the PDF onto
`InBody Report.bat` together to skip the pickers. There are no other questions. The only exception is
when the PDF's patient ID differs from the old report's, in which case it asks before combining them.
Reading a scan takes about 10 seconds. If a value fails a check, a form opens showing what the reader
found, so you can correct it against the printed sheet.

## Command line setup

```bash
pip install -r requirements.txt            # local reader, no API needed
pip install -r requirements-claude.txt     # optional: --reader claude and --ai-summary
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
what's on the sheet), `-o report.html`, `--out-dir folder`, `--timeline timeline.json`,
`--reader local|claude` (default `local`), `--ai-summary` (Claude writes the Summary section instead
of the built-in template), and `--model` (default `claude-opus-5`, used only with Claude).

The local reader is built for the **InBody 380** result sheet. Extraction warnings, for example a value
that fails the Weight = FFM + BFM check, are printed. When you see one, run `extract`, fix the JSON,
and analyze from the JSON.

## Privacy

`reports/`, `patients/` and `*.pdf` are git-ignored so patient data isn't committed. With the default
local reader, scans never leave your computer. Only `--reader claude` and `--ai-summary` send data to
the Anthropic API. The test fixture `tests/fixtures/ocr_inbody380_demo.json` is recognition output
from one sheet, de-identified: the ID and dates are replaced and the signature is removed.

## Layout

| File | Purpose |
|---|---|
| `inbody/ocr_reader.py` | Local reader: text recognition plus InBody 380 layout parsing (default) |
| `inbody/extract.py` | Optional Claude reader, plus the consistency checks used by both readers |
| `inbody/review_form.py` | Correction form shown when a value fails a check |
| `inbody/timeline.py` | Timeline JSON, recovering history from HTML reports, merging scans |
| `inbody/analysis.py` | Deltas, clinical thresholds, findings, recommendations, summary |
| `inbody/report.py` | HTML/CSS/SVG rendering (skill design system) |
| `inbody/narrative.py` | Optional Claude-written summary |
| `inbody/launcher.py`, `InBody Report.bat` | Double-click Windows front end (file pickers, opens the report) |
| `examples/` | Sample data for a fictional patient |
| `tests/` | `python -m pytest` |

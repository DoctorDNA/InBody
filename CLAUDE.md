# InBody Report — notes for Claude

## Who uses this and how
- The user is a physician (Dr. Jeff Reid, Morpheus Precision Health), **not a programmer**, on **Windows**.
- Everything must start from a **double-click**: the desktop shortcut or `InBody Report.bat`. Never ask the
  user to open a command prompt, type commands, edit config files, or install things by hand. If a change
  needs new packages, add them to `requirements.txt`; the .bat reinstalls automatically when that file changes.
- Prefer file-picker windows and simple pop-ups to typed input. Ask only what's unavoidable.
- Explain things in plain language and short numbered steps. No jargon.
- **Delivery:** after committing and pushing, build a zip with
  `git archive --format=zip --prefix=InBody/ -o <scratchpad>/InBody.zip HEAD` and send it. The user copies the
  files over their existing folder. Say whether a first-run setup will happen (only when `requirements.txt` changed).
- The user's program folder is on a protected D: drive. Nothing but reports may be written next to the code:
  the Python environment lives in `%LOCALAPPDATA%\InBody\venv`, and reports fall back to `~/InBody Reports`.

## Building and checking changes
- Run `python -m pytest` before every commit; don't push with failing tests.
- `.bat` files must keep CRLF line endings (enforced by `.gitattributes`); check the zip with `file`.
- Batch-file pitfalls: never echo a folder path inside a `( ... )` block (paths with parentheses break
  it); quote paths; don't rely on `python` being on PATH (the .bat tries `py -3`, then checks `python` runs).
- Windows pitfalls already hit: `strftime("%-d")` doesn't work (use `analysis.md()` / `mdy()`); always pass
  `encoding="utf-8"` to file reads and writes; patient IDs contain `*`, so sanitize anything used as a filename.
- When the user sends real InBody PDFs or reports, test the full flow on them end to end, in a fresh venv
  like the .bat creates. Real files have found bugs that the tests didn't.

## Patient data
- Never commit PDFs, reports, or timelines (`reports/`, `patients/` and `*.pdf` are git-ignored). Real files
  stay in the scratchpad. Test fixtures must be de-identified (ID, dates and signature replaced or removed).

## How it works (short)
- `inbody/ocr_reader.py` reads InBody 380 sheets locally with RapidOCR (no API); values are found by layout
  position, and the checks in `extract.validate_scan` plus duplicate values catch misreads. The review form
  (`review_form.py`) appears only when a check fails.
- `timeline.py` loads history from previous HTML reports (this tool embeds JSON; old InBody-skill reports are
  parsed from their tables) and merges scans by test date.
- `analysis.py` applies the InBody skill's clinical rules; `report.py` renders the skill's HTML design.
- `launcher.py` is the point-and-click flow: Step 1 previous report (Cancel to start a new one from PDFs),
  Step 2 one or more new PDFs.
- Claude-based reading (`--reader claude`) and `--ai-summary` are optional and need `requirements-claude.txt`.

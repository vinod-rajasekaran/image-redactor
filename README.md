# image-redactor

A local evaluation harness for [Microsoft Presidio](https://microsoft.github.io/presidio/)'s
image redaction pipeline: local OCR (Tesseract) + local Presidio
analyzer (spaCy NLP) + Presidio's image redactor, run end-to-end
against a folder of images. No cloud calls, no external APIs — OCR and
PII detection both run on-device.

Includes a generator for synthetic Indian-context test documents
(Aadhaar, PAN, hospital reports, prescriptions, etc.) so there's
something to evaluate against out of the box.

## Setup

Requires macOS with [Homebrew](https://brew.sh).

```bash
./setup.sh
```

This installs Tesseract (via brew), creates a Python 3.12 venv
(spaCy/Presidio don't yet ship wheels for very new Python versions),
installs `requirements.txt`, and downloads the spaCy `en_core_web_lg`
model (~400MB).

## Usage

```bash
source venv/bin/activate

# Optional: create 10 synthetic Indian-context PII documents in input_images/
python generate_test_images.py

# Redact input_images/ -> output_images/
python evaluate_redactor.py
```

Or point at your own folders:

```bash
python evaluate_redactor.py --input path/to/images --output path/to/redacted
```

**To evaluate your own images:** drop them into `input_images/`
(created by `setup.sh`) and run `evaluate_redactor.py` — no need to
run the generator first. Supported formats: `.png .jpg .jpeg .tiff
.bmp`.

`input_images/` and `output_images/` are git-ignored, since they may
contain real PII from images you drop in — nothing there gets
committed.

## Output

For each input image, a redacted copy is written to the output folder
under the same filename, with detected PII regions blacked out. The
run also produces:

- `output_images/redaction_report.json` — per-image results (status,
  detected entity types + counts, average confidence, processing
  time, and any error)
- `output_images/run.log` — full run log (console output is also
  colorized via `rich`, with a live progress bar and a summary table/panel
  at the end)

A per-image failure (corrupt file, unreadable format) is logged and
skipped — it does not stop the batch. Exit code is `2` if any image
failed, `0` otherwise, `1` on a fatal startup error (missing input
folder, missing Tesseract, missing spaCy model).

## Known limitation: Indian ID formats

Presidio's *default* recognizers (`US_DRIVER_LICENSE`, `US_BANK_NUMBER`,
etc.) are US/UK-pattern-based. In testing against the synthetic Indian
documents, names/dates/addresses/phone numbers/emails were reliably
detected and redacted, but **Aadhaar numbers and PAN numbers were not
recognized as distinct entity types** (they aren't blacked out unless
they happen to get swept up by a generic pattern). Adding custom
Presidio `PatternRecognizer`s for `AADHAAR` and `PAN` formats would
close this gap — out of scope for this evaluation harness, but worth
knowing before treating output as fully redacted for Indian documents.

## Files

- `evaluate_redactor.py` — the evaluation CLI
- `generate_test_images.py` — synthetic test document generator
- `setup.sh` — one-time environment setup
- `requirements.txt` — Python dependencies
- `docs/superpowers/specs/` — design spec for this harness

# Presidio Image Redactor Evaluation Harness — Design

Date: 2026-09-14
Status: Approved

## Purpose

Evaluate Microsoft Presidio's image redaction pipeline (local OCR +
local Presidio analyzer, no cloud calls) against a folder of input
images, producing redacted output images and a run report. Also
produce a set of synthetic Indian-context test documents (Aadhaar,
PAN, hospital reports, prescriptions, etc.) with varied PII, since no
sample images exist yet.

Scope is a functional/qualitative run, not accuracy scoring against
ground truth — there is no ground-truth labeling step in this version.

## Components

1. **`generate_test_images.py`** — Pillow-based generator that creates
   10 synthetic Indian-context document images into `input_images/`:
   Aadhaar card, PAN card, job application form, hospital admission
   report, doctor's prescription, bank passbook page, driving license,
   voter ID (EPIC), insurance claim form, rental agreement excerpt.
   All names/numbers are fabricated placeholders, not real people's
   data.

2. **`evaluate_redactor.py`** — CLI script:
   - Args: `--input` (default `input_images/`), `--output` (default
     `output_images/`)
   - For each supported image (`.png .jpg .jpeg .tiff .bmp`) in the
     input folder:
     1. Run Presidio's `ImageAnalyzerEngine` (pytesseract OCR feeding
        Presidio's `AnalyzerEngine` with spaCy `en_core_web_lg` NLP)
        to detect PII entities and their bounding boxes.
     2. Run `ImageRedactorEngine.redact()` to black-box those regions.
     3. Save the redacted image to the output folder under the same
        filename.
     4. Record per-image results (entity types, counts, confidence
        scores) into an in-memory report.
   - A `rich` progress bar tracks batch progress; per-image status
     lines are printed as each stage completes.
   - On a per-image failure (corrupt file, unreadable format, etc.),
     log the exception with filename + stage, mark that image as
     failed in the report, and continue the batch — one bad image
     does not stop the run.
   - At the end, print a summary panel (images processed, entities
     redacted by type, failures) and write
     `output_images/redaction_report.json` with full per-image detail.
   - Logging goes to both the console (rich handler, colorized,
     pretty tracebacks) and a persistent `output_images/run.log` file.

3. **`setup.sh`** — one-time environment setup: creates a venv,
   installs `requirements.txt`, installs the `en_core_web_lg` spaCy
   model, and installs the Tesseract OCR binary via Homebrew (the one
   system-level, non-pip dependency).

4. **`requirements.txt`** — `presidio-analyzer`, `presidio-image-redactor`,
   `pytesseract`, `Pillow`, `spacy`, `rich`.

## Data Flow

```
input_images/*.{png,jpg,...}
        |
        v
[pytesseract OCR] -> text + bounding boxes
        |
        v
[Presidio AnalyzerEngine + spaCy NLP] -> PII entities (type, score, location)
        |
        v
[Presidio ImageRedactorEngine] -> black-box regions on a copy of the image
        |
        v
output_images/<same filename>            output_images/redaction_report.json
                                          output_images/run.log
```

## Error Handling

- Per-image try/except in the batch loop; failures are logged (console
  + file) with filename, stage, and exception, then skipped.
- Report distinguishes `processed`, `no_pii_found`, and `failed` per
  image.
- Missing/empty input folder, missing Tesseract binary, or missing
  spaCy model are checked up front with a clear actionable error
  message before the batch starts.

## Testing / Validation

- Run `generate_test_images.py` to populate `input_images/` with the
  10 synthetic documents.
- Run `evaluate_redactor.py` against them and manually inspect a few
  output images plus `redaction_report.json` to confirm PII regions
  are visibly redacted and entity types look reasonable.
- No pytest suite in this version (I/O + ML pipeline script; manual
  visual validation is the practical check here). Can be added later
  if this becomes a maintained tool rather than a one-off eval.

## Out of Scope (this version)

- Ground-truth accuracy scoring (precision/recall/F1).
- Non-Tesseract OCR engines.
- Cloud-based analyzers.
- A pytest suite.

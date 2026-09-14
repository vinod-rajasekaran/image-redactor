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

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | `input_images` | Folder of images to redact |
| `--output` | `output_images` | Folder for redacted images + report |
| `--threshold` | `0.5` | Minimum Presidio confidence score to redact |
| `--entities` | all supported | Restrict to specific entity types |
| `--strict-aadhaar` | off | Disable the OCR-tolerant Aadhaar fallback (see below) |

`--threshold` and `--entities` mirror the `threshold` / `entity_types`
config in [kaapi-guardrails' `pii_remover` validator](https://github.com/ProjectTech4DevAI/kaapi-guardrails/blob/main/docs/validators/pii-remover.md),
so this harness can be pointed at the same settings that validator runs
in production.

```bash
# Only redact names and Aadhaar numbers, aggressively
python evaluate_redactor.py --entities PERSON IN_AADHAAR --threshold 0.3
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

## Indian entity support

Presidio ships India-specific recognizers but **registers none of them
by default** — a stock `AnalyzerEngine()` loads only US/UK recognizers.
This harness registers all six explicitly in `build_engines()`:
`IN_AADHAAR`, `IN_PAN`, `IN_VOTER`, `IN_PASSPORT`,
`IN_VEHICLE_REGISTRATION`, `IN_GSTIN`.

Note that Aadhaar/PAN/Voter IDs are **regex + checksum** entities, not
NER ones — no spaCy model detects them, so the NER model choice is
irrelevant for these. The NER model only matters for `PERSON` and
`LOCATION`; `en_core_web_lg` detected 19/20 Indian names in testing,
and is what kaapi-guardrails runs in production, so it's kept as-is.

## Findings from evaluation

These came out of running the harness and are worth knowing before
trusting redaction output:

**1. Aadhaar is checksum-validated, and failures are dropped entirely.**
`InAadhaarRecognizer` runs a Verhoeff checksum in `validate_result()`.
An invalid checksum doesn't score low — the match is **discarded**, so
no `--threshold` value recovers it. Consequences: made-up test Aadhaar
numbers are never redacted, and **a single OCR digit error on a real
Aadhaar silently leaves it unredacted**.

This harness therefore registers an OCR-tolerant fallback recognizer by
default: a checksum-free `IN_AADHAAR` pattern for the 4-4-4 grouped form
at score 0.5. Measured effect on the test set — the hospital report's
deliberately checksum-invalid Aadhaar is redacted in default mode and
**missed entirely** under `--strict-aadhaar`.

The fallback carries no look-around guards on purpose. OCR flattens a
page into a single string with no field boundaries, so an adjacent phone
number is indistinguishable from a continuation of the same number, and
guards drop real Aadhaars. The trade-off is that credit-card and account
numbers also match the pattern; those spans are redacted anyway as
`CREDIT_CARD`/`DATE_TIME`, so it costs label precision in the report,
not redaction quality.

**2. Two-column layouts break context-dependent recognizers.** Tesseract
reads a label/value form in column order, emitting *every* label before
*every* value. The reconstructed text puts "Aadhaar No.:" far away from
its number, so Presidio's context enhancer finds no nearby context word
and applies no score boost. Any recognizer relying on context words
degrades on form-style documents — which describes most Indian ID
documents.

**3. `IN_PASSPORT` cannot fire at the default threshold.** Its base
pattern scores 0.1 and reaches only ~0.45 even with context words
present — below the 0.5 default. Indian passport numbers are never
redacted unless you pass `--threshold 0.4` or lower.

**4. `IN_VEHICLE_REGISTRATION` needs the unspaced form, and OCR breaks
it.** It matches `KA05MJ4521` but not `KA 05 MJ 4521` (the spaced form
printed on real plates and RCs). In testing Tesseract also misread
`KA05MJ4521` as `KA**O**5MJ4521` (digit `0` → letter `O`), which defeats
the regex. No OCR-tolerant fallback is provided for this one.

### Relevant to kaapi-guardrails

Findings 1, 3 and 4 contradict the current
[`pii-remover.md`](https://github.com/ProjectTech4DevAI/kaapi-guardrails/blob/main/docs/validators/pii-remover.md)
docs, which describe `IN_AADHAAR` as a plain "Regex (12-digit format)"
scoring 1.0. That doc's own Example 2 (`2345 6789 0123`) fails the
Verhoeff checksum and is **not** detected. Its
`IN_VEHICLE_REGISTRATION` example (`MH 12 AB 1234`, spaced) is also not
detected. And with the documented default `threshold: 0.5`,
`IN_PASSPORT` can never trigger.

## Files

- `evaluate_redactor.py` — the evaluation CLI
- `generate_test_images.py` — synthetic test document generator
- `setup.sh` — one-time environment setup
- `requirements.txt` — Python dependencies
- `docs/superpowers/specs/` — design spec for this harness

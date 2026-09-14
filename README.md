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
| `--runs-dir` | `runs` | Parent folder; each run gets its own subfolder |
| `--run-name` | timestamp + settings | Name for this run's folder |
| `--ocr` | `tesseract` | OCR backend: `tesseract` or `paddle` |
| `--visual-pii` | off | Also redact faces and QR/barcodes (OpenCV + pyzbar) |
| `--threshold` | `0.4` | Minimum Presidio confidence score to redact |
| `--entities` | all supported | Restrict to specific entity types |
| `--upscale` | `auto` | Pre-OCR upscale factor; `auto` scales narrow images toward 600px wide, `1` disables |
| `--strict-aadhaar` | off | Disable the OCR-tolerant Aadhaar fallback (see below) |

`--threshold` and `--entities` mirror the `threshold` / `entity_types`
config in [kaapi-guardrails' `pii_remover` validator](https://github.com/ProjectTech4DevAI/kaapi-guardrails/blob/main/docs/validators/pii-remover.md),
so this harness can be pointed at the same settings that validator runs
in production. The one deliberate divergence is the **default** threshold
(0.4 here vs 0.5 there) — see finding 3 below for why 0.5 silently misses
PAN, voter and passport numbers.

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

Each run writes a self-describing folder so results stay reproducible and
comparable:

```
runs/<run-name>/
  config.json    # exactly what this run was asked to do
  summary.json   # totals, per-entity counts, per-image results
  run.log        # full log
  images/        # redacted images
```

`config.json` records the OCR backend, threshold, entity list, upscale
setting, visual-PII flag, image count, and platform/Python versions —
enough to reproduce or audit the run later. `summary.json` embeds that
same config alongside the results, so a single file is self-contained.

Every input image gets a counterpart in `images/` under the same
filename, with detected PII regions blacked out. Images where no PII was
found are copied through unchanged, so the folder is always a complete
mirror of the input and a downstream consumer never silently loses a file.

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
at score 0.5. It is not a theoretical concern — on a real sample Aadhaar
card image, the printed number `4587 6321 9876` is checksum-invalid, so
stock Presidio redacted **nothing**; the fallback caught it. Across a
20-image set, default mode found 15 `IN_AADHAAR` spans vs 9 under
`--strict-aadhaar`.

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

**3. A 0.5 threshold is precisely the wrong value for Indian IDs.**
Presidio's context enhancer adds +0.35, and several India recognizers
use a weak base pattern of 0.1 — so a context-boosted weak match lands
at exactly **0.45**, just under a 0.5 threshold. Affected: `IN_PASSPORT`
(always), and `IN_PAN`/`IN_VOTER` whenever the value doesn't satisfy
the recognizer's strong pattern.

This is not theoretical. On a real photographed PAN card whose number
OCR'd perfectly as `ABCDE1234F`, **the PAN number was left fully
visible** at the default threshold — `ABCDE1234F` has `D` as its 4th
character, which is not a valid PAN holder-type code, so it only
matched the weak pattern and scored 0.45.

| image | `--threshold 0.5` | `--threshold 0.4` |
|-------|-------------------|-------------------|
| real PAN card | nothing | `IN_PAN` ✓ |
| voter ID | nothing | `IN_VOTER` ✓ |

**This harness therefore defaults to `--threshold 0.4`,** deliberately
diverging from kaapi-guardrails' documented 0.5. Pass `--threshold 0.5`
explicitly to reproduce that validator's current behaviour.

**4. `IN_VEHICLE_REGISTRATION` needs the unspaced form, and OCR breaks
it.** It matches `KA05MJ4521` but not `KA 05 MJ 4521` (the spaced form
printed on real plates and RCs). In testing Tesseract also misread
`KA05MJ4521` as `KA**O**5MJ4521` (digit `0` → letter `O`), which defeats
the regex. No OCR-tolerant fallback is provided for this one.

**5. Only OCR'd text is redacted — faces and QR codes are not.**
`ImageRedactorEngine` blacks out text regions found via OCR. On a real
Aadhaar card it correctly redacts name, DOB and the number, but leaves
the **photo** and the **QR code** fully intact. An Aadhaar QR encodes
the holder's name, DOB and address, so a card redacted this way is not
meaningfully redacted.

`--visual-pii` closes this gap (see `visual_redaction.py`): OpenCV Haar
cascades for faces, `cv2.QRCodeDetector` for QR regions, pyzbar for
barcodes. Two notes from building it:

- **Detection matters more than decoding.** pyzbar decoded none of the
  QR codes in the sample set — decorative or low-resolution codes are
  exactly the ones it refuses — but `cv2.QRCodeDetector` still *located*
  them, which is all redaction needs. Relying on decode alone would have
  redacted nothing.
- **Haar face boxes are too tight.** They hug the eyes and nose and clip
  chin, hair and ears, leaving a recognisable sliver. Faces are padded
  30% (`PAD_RATIO`); don't reduce that without looking at the output.

**6. Cropped or truncated values defeat pattern recognizers.** A PAN
visible only as `DE1234F` (rather than the full `ABCDE1234F`) does not
match `IN_PAN`, because the pattern needs the complete
5-letter/4-digit/1-letter form. Partially visible IDs at frame edges
pass through unredacted.

**7. Photographed documents need upscaling before OCR.** Tesseract reads
small photos of documents (~300px wide, shot at an angle) very poorly.
A real job-application form yielded **zero** detections at native size;
at 2x it yielded 7, including the phone number. `--upscale` defaults to
`auto` for this reason, scaling narrow images toward 600px wide for the
OCR pass only — the saved image keeps its original dimensions.

Upscaling also *improves precision*: on the PAN card, native-size OCR
produced 9 `PERSON` hits for a card carrying 2 names, because garbled
text was misread as names. At 2x it produced the correct 4 word-boxes.

**8. OCR errors defeat regex entities generally.** The same failure mode
as the Aadhaar checksum shows up everywhere: an email OCR'd as
`oriyasharma@grmal ON` never matches `EMAIL_ADDRESS`, and a vehicle
registration read as `KAO5MJ4521` (letter `O` for digit `0`) never
matches. Any recognizer that depends on exact character patterns
degrades in proportion to OCR quality — which is why image redaction
cannot be assumed as reliable as text redaction.

### Benchmark: OCR backend × visual PII

All four combinations over the same 20 images (10 synthetic, 10 photos of
Indian documents):

| run | entities | EMAIL | PHONE | visual | no PII found | seconds |
|-----|---------:|------:|------:|-------:|-------------:|--------:|
| tesseract, text only | 205 | 1 | 25 | 0 | 2 | 12.5 |
| tesseract + visual   | 205 | 1 | 7  | 7 | 2 | 13.4 |
| paddle, text only    | **234** | **3** | **27** | 0 | **0** | 285.3 |
| paddle + visual      | **234** | **3** | **27** | 7 | **0** | 289.5 |

PaddleOCR finds ~14% more entities and, more importantly, fixes the
specific misses Tesseract had:

- **the garbled email** (`priya.sharma@gmail.com`, previously OCR'd as
  `oriyasharma@grmal ON`) is now read and redacted
- **the laptop-screen loan form** went from **0 detections to 8**
  (name, email, DOB, URL) — Tesseract could not read it at all
- **`IN_VEHICLE_REGISTRATION`** now matches, because Paddle reads
  `KA05MJ4521` rather than Tesseract's `KAO5MJ4521` (letter `O`)
- **`IN_PASSPORT`** now fires on the synthetic job application

The cost is speed: **~23x slower** (285s vs 12.5s for 20 images), since
it runs detection and recognition models on CPU. Visual PII is
independent of the OCR choice and costs ~1 second for all 20 images.

Recommendation: `--ocr paddle --visual-pii` when redaction quality
matters, plain `tesseract` for quick iteration.

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

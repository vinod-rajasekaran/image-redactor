# image-redactor

A local evaluation harness for [Microsoft Presidio](https://microsoft.github.io/presidio/)'s
image redaction pipeline: local OCR (Tesseract) + local Presidio
analyzer (spaCy NLP) + Presidio's image redactor, run end-to-end
against a folder of images. No cloud calls, no external APIs — OCR and
PII detection both run on-device.

It targets Indian documents specifically: it registers Presidio's
India-specific recognizers (which are not enabled by default), ships a
generator for synthetic Indian test documents, and redacts faces and QR
codes, which Presidio does not.

Crucially it **measures leakage** rather than counting detections —
reading each redacted image back to check whether the PII is still
legible. That distinction has already caught two bugs that made the tool
look better while it redacted less.

> This README describes how the tool works **now**.
> [DECISIONS.md](DECISIONS.md) is the time-ordered history: every default,
> why it was chosen, the evidence, and the options tried and rejected.

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

# Redact input_images/ -> runs/<timestamp>_tesseract_visual/images/
python evaluate_redactor.py

# Score that run for leakage against ground truth
python score_run.py runs/<run-name>
```

Or point at your own folders:

```bash
python evaluate_redactor.py --input path/to/images --runs-dir path/to/runs
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | `input_images` | Folder of images to redact |
| `--runs-dir` | `runs` | Parent folder; each run gets its own subfolder |
| `--run-name` | timestamp + settings | Name for this run's folder |
| `--ocr` | `tesseract` | OCR backend: `tesseract`, `paddle` or `rapidocr` |
| `--psm` | `4` | Tesseract page-segmentation mode (3, 4, 6, 11, 12) |
| `--no-visual-pii` | off | Skip face and QR/barcode redaction (on by default) |
| `--pyzbar` | off | Also decode code payloads with pyzbar (needs `zbar`) |
| `--threshold` | `0.4` | Minimum Presidio confidence score to redact |
| `--entities` | all supported | Restrict to specific entity types |
| `--upscale` | `auto` | Pre-OCR upscale factor; `auto` scales narrow images toward 600px wide, `1` disables |
| `--strict-aadhaar` | off | Disable the OCR-tolerant Aadhaar fallback |
| `--wechat-qr` | off | Also run the WeChat QR detector (supplement, not replacement) |

`--threshold` and `--entities` mirror the `threshold` / `entity_types`
config in [kaapi-guardrails' `pii_remover` validator](https://github.com/ProjectTech4DevAI/kaapi-guardrails/blob/main/docs/validators/pii-remover.md),
so this harness can be pointed at the same settings that validator runs
in production. The one deliberate divergence is the **default** threshold
(0.4 here vs 0.5 there) — see "Why the defaults are what they are" for why
0.5 silently misses PAN, voter and passport numbers.

```bash
# Only redact names and Aadhaar numbers, aggressively
python evaluate_redactor.py --entities PERSON IN_AADHAAR --threshold 0.3
```

**To evaluate your own images:** drop them into `input_images/`
(created by `setup.sh`) and run `evaluate_redactor.py` — no need to
run the generator first. Supported formats: `.png .jpg .jpeg .tiff
.bmp`.

`input_images/`, `runs/` and `ground_truth.json` are git-ignored, since
they describe or contain real PII from images you drop in.

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

## Measuring leakage, not detections

Entity counts cannot tell you what fraction of PII was caught — they move
on both misses and false positives. `ground_truth.json` records the PII
that actually exists in each test image (the synthetic half derived from
the generator, so it stays exact; the real half labelled by reading the
documents), and `score_run.py` measures what survived:

```bash
python build_ground_truth.py        # writes ground_truth.json
python evaluate_redactor.py --run-name mytest
python score_run.py runs/mytest     # writes runs/mytest/score.json
```

Scoring reads the *output* image back with OCR and asks, per PII item:
was it legible before, and is it still legible now? That is stricter than
checking detections, because it also catches boxes drawn in the wrong
place. Items OCR could not read even in the input are reported separately
— counting them as successes would flatter the tool, counting them as
misses would blame Presidio for an OCR problem.

## Why the defaults are what they are

Every default below was chosen against measured evidence on the sample
set, and several are deliberately *not* the obvious choice. If you are
tempted to change one, the "what it buys" column is what you would be
giving up.

| Default | Why not the obvious choice | What it buys |
|---|---|---|
| `--threshold 0.4` | Presidio's +0.35 context boost over a 0.1 base pattern lands at exactly **0.45**, so the conventional 0.5 silently drops every context-boosted weak match | A real PAN card's number is redacted instead of left visible; `IN_VOTER` too. At 0.5, `IN_PASSPORT` can *never* fire |
| `--ocr tesseract` | PaddleOCR leaks less PII — 84.7% recall vs 76.5% | ~17x faster, which makes iteration practical. **Use `--ocr paddle` for any run whose output you intend to rely on**; the speed default is for development, not production redaction |
| `--psm 4` | Tesseract's own default is 3 | +2.4 points of recall (76.5% vs 74.1%) for no extra time. PSM 4, 6 and 11 tie exactly; 4 matches the layout these documents actually have |
| `--upscale auto` | Leaving images at native size is simpler | A real job-application photo went from **0 detections to 7**. Also *raises* precision: the PAN card dropped from 9 spurious `PERSON` hits to a correct 4 |
| visual PII **on** | Presidio only ever redacts OCR'd text | Faces, QR codes and barcodes get redacted. An intact Aadhaar QR encodes name, DOB and address — redacting the printed number while leaving the QR is not redaction |
| OpenCV `detect()`, never `detectAndDecode()` | The decode APIs look strictly more capable | Decode-gated APIs return **no box** for a code they cannot read, silently skipping exactly the unreadable codes that most need blacking out. This bug shipped once here and was caught only because a barcode count stayed at 0 |
| `--pyzbar` **off** | pyzbar is the usual go-to for barcodes | It decoded **0** of the codes in the sample set, and needs the `zbar` system library. OpenCV located all of them, including one pyzbar missed entirely |
| `--wechat-qr` **off** | The WeChat model is genuinely better at small/blurry QR | **Validated and rejected as a default:** it found **0 codes vs the stock detector's 4**, because its only Python entry point is `detectAndDecode()`. A control test on an encodable QR confirmed it works — it is decode-gated, not broken. Kept as an opt-in supplement (unioned, never substituted) for real documents where payloads matter |
| Aadhaar OCR-tolerant fallback **on** | Stock Presidio validates a Verhoeff checksum | Checksum failures are *discarded*, not down-scored, so one OCR digit error leaves a real Aadhaar fully visible. A real sample card's number is checksum-invalid: stock Presidio redacted nothing, the fallback caught it |
| That fallback has **no look-around guards** | Guards would stop it matching inside credit-card numbers | OCR flattens the page into one string with no field boundaries, so an adjacent phone number is indistinguishable from a continuation. Guards were tried and dropped real Aadhaars. Cost is label precision in the report, not redaction quality |
| spaCy `en_core_web_lg` | A newer/Indic NER model sounds better for Indian documents | Aadhaar/PAN/voter are **regex + checksum**, not NER — no model change affects them. For names, this model scored 19/20 on Indian names and matches kaapi-guardrails' production validator |
| YuNet for faces, Haar as fallback | Haar ships with OpenCV and needs no model file | Haar reported **3 faces where 2 exist**, inventing one on the Aadhaar card; YuNet found exactly the 2. Haar still runs if the model file is missing, so a skipped download degrades quality rather than breaking |
| Faces padded 30% | The detector returns a tight box | Tight boxes clip chin, hair and ears. The first run left a recognisable sliver of face visible |
| Clean images copied through | Writing only redacted files is less work | The output folder stays a complete mirror of the input, so a downstream consumer never silently loses a file |

Two caveats on reading the numbers: entity **counts** move on both misses
and false positives, so compare entity *types* and look at the images.
And visual detection does false-positive — QR detection fires on some
dense text blocks, Haar finds a phantom second face on one card. Both
over-redact regions that were PII anyway, which is the right trade here.

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

## Current limitations

What this tool still does not redact, as of the latest run. History and
rationale for every design choice live in [DECISIONS.md](DECISIONS.md).

- **Faces and codes are detected, but text is the weak point.** Remaining
  leaks cluster in `LOCATION` (multi-line addresses partially covered,
  leaving enough to reconstruct) and in values **no Presidio recognizer
  covers** — Indian bank account numbers, hospital UHIDs, airline PNRs,
  policy numbers. Custom `PatternRecognizer`s are the obvious next step.
- **OCR errors defeat exact-pattern entities.** An email read as
  `oriyasharma@grmal ON` never matches `EMAIL_ADDRESS`; a vehicle
  registration read as `KAO5MJ4521` (letter `O` for digit `0`) never
  matches. Image redaction is therefore inherently less reliable than
  text redaction, and degrades with image quality.
- **Handwriting is not read at all.** The handwritten prescription body
  is invisible to both OCR engines.
- **Only English.** OCR and the spaCy model are English-only, so names
  and addresses in Devanagari or Kannada — present on real Aadhaar cards
  and utility bills — are never detected.
- **Cropped values are missed.** A PAN visible only as `DE1234F` does not
  match `IN_PAN`, which needs the full 5-letter/4-digit/1-letter form.
- **Two-column layouts weaken context scoring.** OCR emits every label
  before every value, stranding "Aadhaar No.:" far from its number, so
  Presidio's context enhancer applies no boost. This is why the Aadhaar
  fallback does not rely on context words.
- **Visual detection false-positives.** QR detection fires on some dense
  text blocks. These over-redact regions that were PII anyway, which is
  the intended trade, but the counts are not precision measurements.
- **EXIF is not stripped.** Phone-camera inputs can carry GPS and an
  embedded thumbnail of the *original* image. Not an issue for the
  current PNG test set, but a real leak for real uploads.

## Benchmark: OCR backends, measured by leakage

Produced by `benchmark_ocr.py` over the same 20 images (10 synthetic, 10
photos of Indian documents), scored with `score_run.py`. "Leaked" means
the PII was legible in the input and is **still legible in the redacted
output** — the only measure that matters. 11 further items are illegible
to every engine and are excluded from recall.

| config | redacted | leaked | recall | wall s |
|---|---:|---:|---:|---:|
| **paddle** | 72 | 13 | **84.7%** | 434 |
| tesseract `--psm 4` *(default)* | 65 | 20 | 76.5% | 26 |
| tesseract `--psm 6` | 65 | 20 | 76.5% | 25 |
| tesseract `--psm 11` | 65 | 20 | 76.5% | 27 |
| rapidocr | 64 | 21 | 75.3% | 40 |
| tesseract `--psm 3` | 63 | 22 | 74.1% | 31 |
| tesseract `--psm 12` | 63 | 22 | 74.1% | 37 |

Three things this settles:

- **Page-segmentation mode is a free win.** PSM 4, 6 and 11 all score
  76.5% against Tesseract's own default of 3 at 74.1%, for no extra time.
  PSM 4 (single column of variable-size text) is now the default; the
  three-way tie means the choice between them is arbitrary.
- **RapidOCR is not a middle ground.** It was expected to approach
  Paddle's accuracy on a lighter runtime, on the assumption it ran the
  same models. It does not: it ships **PP-OCRv4 mobile**, while
  PaddleOCR 3.7 runs **PP-OCRv6_medium** — two major versions newer and
  a larger variant. At 75.3% and 40s it is dominated by `--psm 4`, which
  is both more accurate and faster. Pointing RapidOCR at exported v5/v6
  ONNX models might change this, but that is unexplored.
- **There is no cheap path to Paddle's accuracy.** The 8-point gap
  between `--psm 4` and Paddle costs ~17x in wall time. Nothing tested
  sits in between.

Recommendation: `--psm 4` (the default) for iteration, `--ocr paddle`
for any output you intend to rely on.

## Relation to kaapi-guardrails

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
- `ocr_backends.py` — Tesseract / PaddleOCR / RapidOCR adapters
- `visual_redaction.py` — face, QR and barcode detection
- `generate_test_images.py` — synthetic test document generator
- `build_ground_truth.py` → `ground_truth.json` — the PII each image holds
- `score_run.py` — scores a run for leakage, writes `score.json`
- `benchmark_ocr.py` — runs every OCR config and tabulates recall vs cost
- `setup.sh` — one-time environment setup
- `DECISIONS.md` — time-ordered log of every decision and its evidence
- `docs/superpowers/specs/` — original design spec

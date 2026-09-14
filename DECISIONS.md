# Decision Log

Time-ordered record of every design decision in this project, why it was
made, and what evidence supported it. The README describes how the tool
works **now**; this file is the history, including options that were
tried and rejected.

Add a new entry whenever a default changes, a component is swapped, or a
measurement overturns a previous belief. Never rewrite an old entry —
supersede it with a new one and mark the old `Superseded`.

**Entry format:** date, status, decision, why, evidence.
Status is `Active`, `Superseded by <date/title>`, or `Rejected`.

---

## 2026-09-14 — Scope: functional evaluation harness, not accuracy scoring

**Status:** Superseded by *2026-09-14 — Ground-truth leakage scoring*

Build a script that runs a folder of images through local OCR + local
Presidio and writes redacted copies, with no ground-truth comparison.

**Why:** the initial goal was to see Presidio's image redaction work
end-to-end on Indian documents, not to measure it.

**Evidence:** none — a scoping choice.

---

## 2026-09-14 — Tesseract as the OCR engine

**Status:** Active (default; see later entries for alternatives)

**Why:** it is what `presidio-image-redactor` uses by default, is
lightweight, and needs only `brew install tesseract`.

**Evidence:** none at the time. Later benchmarking (below) justified
keeping it as the *default* on latency grounds while recommending other
backends for output that matters.

---

## 2026-09-14 — Python 3.12, not 3.14

**Status:** Active

**Why:** spaCy and Presidio had no wheels for Python 3.14 (the system
Python) as of this date.

**Evidence:** install attempt; `brew install python@3.12` resolved it.

---

## 2026-09-14 — Synthetic Indian test documents

**Status:** Active

Generate 10 Indian-context documents (Aadhaar, PAN, hospital report,
prescription, bank passbook, licence, voter ID, insurance, rental
agreement) with Pillow.

**Why:** no sample images existed, and the target domain is Indian
documents specifically.

**Evidence:** n/a. All values are fabricated; none refer to real people.

---

## 2026-09-14 — Register Presidio's India recognizers explicitly

**Status:** Active

Register `InAadhaarRecognizer`, `InPanRecognizer`, `InVoterRecognizer`,
`InPassportRecognizer`, `InVehicleRegistrationRecognizer`,
`InGstinRecognizer` in `build_engines()`.

**Why:** a stock `AnalyzerEngine()` loads **only US/UK recognizers**.
The India ones ship with Presidio but are never registered, so Aadhaar
and PAN numbers passed through unredacted.

**Evidence:** `AnalyzerEngine().registry.recognizers` listed 17
recognizers, none of them Indian.

---

## 2026-09-14 — Keep spaCy `en_core_web_lg`; reject a different NER model

**Status:** Active

**Why:** the request was to add "a spaCy model for NER of Indian
entities like Aadhaar". Aadhaar/PAN/voter IDs are **regex + checksum**
entities — no NER model detects them, so a model swap could not help.
For names, which *are* NER, the current model was already strong, and it
matches what kaapi-guardrails runs in production.

**Evidence:** `en_core_web_lg` detected **19/20** Indian names in a
direct test.

---

## 2026-09-14 — OCR-tolerant Aadhaar fallback, on by default

**Status:** Active

Add a checksum-free `IN_AADHAAR` pattern recognizer alongside Presidio's.
`--strict-aadhaar` disables it.

**Why:** `InAadhaarRecognizer` validates a Verhoeff checksum and
**discards** failures rather than scoring them low, so no threshold
recovers them. One OCR digit error therefore leaves a real Aadhaar fully
visible.

**Evidence:** a real sample Aadhaar card's printed number
`4587 6321 9876` is checksum-invalid — stock Presidio redacted nothing,
the fallback caught it. Across 20 images: 15 `IN_AADHAAR` spans with the
fallback, 9 without.

---

## 2026-09-14 — That fallback carries no look-around guards

**Status:** Active

**Why:** guards were added first, to stop the pattern matching inside
credit-card and account numbers. They broke real detections: OCR
flattens a page into one string with no field boundaries, so a
neighbouring phone number is indistinguishable from a continuation of
the same number.

**Evidence:** with guards, a real Aadhaar following a phone number in
the OCR text (`...56789 4521 8734 9012`) was excluded. Cost of removing
them is label precision in the report, not redaction quality — those
spans are redacted as `CREDIT_CARD`/`DATE_TIME` anyway.

---

## 2026-09-14 — Default `--threshold` 0.4, not 0.5

**Status:** Active

**Why:** Presidio's context enhancer adds +0.35, and several India
recognizers use a 0.1 base pattern, so a context-boosted weak match
lands at exactly **0.45** — just under a 0.5 threshold. `IN_PASSPORT`
can never fire at 0.5.

**Evidence:** a real PAN card whose number OCR'd perfectly as
`ABCDE1234F` was left **fully visible** at 0.5 and redacted at 0.4
(its 4th character `D` is not a valid holder-type code, so it matched
only the weak pattern). Same for a voter ID's EPIC number.

**Note:** this deliberately diverges from kaapi-guardrails' documented
default of 0.5.

---

## 2026-09-14 — Pre-OCR upscaling, `--upscale auto`

**Status:** Active

Scale narrow images toward 600px wide for the OCR pass only; the saved
image keeps its original dimensions.

**Why:** Tesseract reads small photographed documents very poorly.

**Evidence:** a real job-application photo yielded **0 detections** at
its native ~300px width and **7** at 2x. Upscaling also *raised*
precision — the PAN card went from 9 spurious `PERSON` hits (garbled
text read as names) to a correct 4.

---

## 2026-09-14 — Copy through images with no detections

**Status:** Active

**Why:** images with no PII previously produced no output file at all,
so the output folder was not a complete mirror of the input and a
downstream consumer would silently lose files.

**Evidence:** n/a — a correctness fix.

---

## 2026-09-14 — Per-run output folders with config + summary

**Status:** Active

`runs/<name>/{config.json, summary.json, run.log, images/}`.

**Why:** runs need to be reproducible and comparable; a single
overwritten output folder loses the settings that produced it.

---

## 2026-09-14 — Redact faces and QR/barcodes by default

**Status:** Active

**Why:** Presidio redacts only OCR'd text, leaving ID photos and QR
codes untouched. An Aadhaar QR encodes the holder's name, DOB and
address, so redacting the printed number while leaving the QR intact is
not redaction at all.

**Evidence:** visual inspection of a redacted real Aadhaar card — name,
DOB and number blacked out, photo and QR fully intact.

---

## 2026-09-14 — Locate codes with `detect()`, never `detectAndDecode()`

**Status:** Active

**Why:** decode-gated APIs return **no bounding box** for a code they
cannot read — silently skipping exactly the unreadable codes that most
need blacking out.

**Evidence:** this bug was live in the barcode path and was caught only
because the water-bill barcode count stayed at 0 despite a barcode
being plainly present.

---

## 2026-09-14 — pyzbar demoted to opt-in (`--pyzbar`)

**Status:** Active

**Why:** it adds nothing to *detection* and needs the `zbar` system
library.

**Evidence:** pyzbar decoded **0** of the codes in the sample set —
decorative and low-resolution codes are exactly what a decoder refuses —
while OpenCV located all of them, including a barcode pyzbar missed
entirely.

---

## 2026-09-14 — WeChat QR detector rejected as the default

**Status:** Rejected as default; available via `--wechat-qr`

**Why:** it is genuinely better on small, blurry and angled *real* QR
codes and returns payloads — but its only Python entry point is
`detectAndDecode()`, so it inherits the decode-gating problem above.

**Evidence:** **0 codes located versus the stock detector's 4.** A
control test on an encodable QR confirmed the model works and decodes
correctly, so it is decode-gated, not broken. Kept as a supplement,
unioned with the stock detector, never a substitute.

---

## 2026-09-14 — YuNet replaces the Haar cascade for faces

**Status:** Active (Haar retained as fallback)

**Why:** Haar is a 2001-era cascade and over-triggers.

**Evidence:** Haar reported **3 faces where 2 exist**, inventing one on
the Aadhaar card; YuNet found exactly 2. Haar still runs when the model
file is absent, so a skipped download degrades quality rather than
breaking the run.

---

## 2026-09-14 — Faces padded 30%

**Status:** Active

**Why:** face detectors return a box hugging the eyes and nose.

**Evidence:** the first visual-PII run left a recognisable sliver of
chin and hair visible outside the box.

---

## 2026-09-14 — Ground-truth leakage scoring

**Status:** Active — supersedes *Scope: functional evaluation harness*

`ground_truth.json` (built by `build_ground_truth.py`) records the PII
actually present in each test image. `score_run.py` reads each redacted
output back through OCR and classifies every known item as `redacted`,
`leaked`, or `not_legible`.

**Why:** entity counts move on both misses and false positives, so they
cannot say what fraction of PII was caught. Reading the output back also
catches boxes drawn in the *wrong place*, which detection counts cannot.

**Evidence:** first measurement, Tesseract with defaults: **74.1%**
recall on legible PII (63/85), 22 leaked — materially worse than the
entity counts implied. 96 ground-truth items, 12 of which no Presidio
recognizer covers.

---

## 2026-09-14 — Two PaddleOCR box-alignment bugs fixed

**Status:** Active

1. Paddle detects text *lines*, not words. Estimating word positions by
   character count assumes uniform spacing, which is wrong for
   label/value forms — the wide gap shifted every box onto the label,
   leaving the value legible. Each word now carries its whole line box.
2. PaddleOCR 3.x runs document orientation classification and `UVDoc`
   unwarping by default and reports boxes in that **rectified** space,
   ~40px off from the image being redacted. Both are now disabled.

**Why / evidence:** this is the most important entry in this log.
**Both bugs raised detection counts while lowering actual redaction.**
Paddle reported 234 entities to Tesseract's 205 and looked like the
clear winner, while scoring **62.4%** recall against Tesseract's 74.1%
and leaving a DOB and mobile number fully visible under boxes floating
in the margin. After both fixes Paddle scores **84.7%**.

An entity-count comparison rated the broken configuration as the better
one. Only reading the output back caught it. Do not re-enable Paddle's
document preprocessing, and do not re-introduce proportional word
splitting, without re-running `score_run.py`.

---

## 2026-09-14 — Default Tesseract PSM 4, not Tesseract's own 3

**Status:** Active

**Why:** the question was whether anything sits between Tesseract
(74.1%, cheap) and Paddle (84.7%, ~17x slower). Page-segmentation mode
turned out to be a free improvement.

**Evidence:** PSM 4, 6 and 11 all score **76.5%** against PSM 3's
**74.1%**, at identical cost. The three-way tie makes the choice between
them arbitrary; 4 ("single column of variable-size text") matches the
layout of the documents in scope.

---

## 2026-09-14 — RapidOCR rejected as a middle ground

**Status:** Rejected (backend retained as `--ocr rapidocr`)

**Why it was expected to work:** RapidOCR runs PaddleOCR-family models on
ONNXRuntime, so it should have approached Paddle's accuracy at a fraction
of the cost and without the paddlepaddle runtime.

**Why that reasoning was wrong:** the models are not the same generation.
RapidOCR ships **PP-OCRv4 mobile** (4MB detection, 10MB recognition),
while PaddleOCR 3.7 runs **PP-OCRv6_medium** — two major versions newer
and a larger variant. The assumption of "same model lineage" was simply
incorrect.

**Evidence:** **75.3% recall at 40s**, versus `--psm 4` at **76.5% and
26s**. It is dominated on both axes, so there is no reason to prefer it
as configured. Pointing it at exported v5/v6 ONNX models could change
this and is unexplored.

**Conclusion of the search:** nothing tested sits between `--psm 4` and
Paddle. The 8-point gap costs ~17x in wall time, and that trade is real
rather than an artefact of tuning.

---

## 2026-09-14 — Benchmark harness

**Status:** Active

`benchmark_ocr.py` runs every OCR configuration over the same images,
scores each with `score_run.py`, and tabulates recall against wall-clock
cost into `runs/benchmark.json`.

**Why:** OCR choices had been argued from entity counts and single-image
spot checks, both of which had already produced wrong conclusions.

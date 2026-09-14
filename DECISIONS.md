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

---

## 2026-09-14 — Explicit metadata stripping, with a regression guard

**Status:** Active

`image_hygiene.sanitize_for_processing()` applies EXIF orientation and
returns a metadata-free image; `save_clean()` writes without carrying
metadata across. `test_metadata_stripping.py` guards both.

**Why:** a redacted image can leak through its container rather than its
pixels. Phone photos carry GPS and frequently an embedded thumbnail — a
copy of the image *as it was before* anything was blacked out.

**Evidence, and a correction:** this was first written into the README as
a known limitation ("EXIF is not stripped") **without being tested. That
claim was wrong.** Constructing a JPEG with GPS, device tags and an
embedded thumbnail and running it through both the redaction and
copy-through paths showed the output already clean — Pillow does not
propagate `info["exif"]` unless a caller passes it to `save()`.

The guardrail was still worth adding, because that safety was
*incidental*. A single `save(**img.info)` would reintroduce the leak
silently. The tests were verified to fail when the protection is removed,
so they guard something real rather than passing vacuously.

Orientation is applied rather than discarded, which also helps detection:
a phone photo tagged "rotate 90" is stored sideways, and OCR of a
sideways page finds almost nothing.

---

## 2026-09-14 — Seven custom Indian pattern recognizers

**Status:** Active

`custom_recognizers.py` adds `IN_IFSC`, `IN_DRIVING_LICENCE`,
`IN_BANK_ACCOUNT`, `IN_PATIENT_ID`, `IN_PNR`, `IN_POLICY_NUMBER`,
`IN_MEDICAL_REG`.

**Why:** ground-truth scoring identified twelve values no Presidio
recognizer claims, seven of which leaked.

**Evidence:** recall 76.5% → **81.2%**; the no-recognizer bucket went
from 7 leaked to 2 (both free-text diagnoses).

**Design note:** the two with distinctive shapes (IFSC's mandatory `0`
in position five, the driving-licence state/RTO prefix) fire unaided.
The rest are shapeless — an account number is a digit run, a PNR is six
alphanumerics — so they carry a 0.1 base score and depend on the +0.35
context boost to clear the 0.4 threshold. Negative controls confirm they
stay silent without a label nearby.

---

## 2026-09-14 — Reading-order normalisation

**Status:** Active

Wrap every OCR backend to re-sort words top-to-bottom, then
left-to-right.

**Why:** the context dependency above is only safe if OCR emits each
label beside its value. Tesseract PSM 3 emits every label and then every
value, stranding context words and silently disabling every
context-scored recognizer. PSM 4 happens to order correctly — which is
most of why it beat PSM 3 — but that was luck, not a guarantee.

**Evidence:** on the hospital report under PSM 3, ordering went from
`Patient Name: Age / Sex: Address: ... Mohammed Irfan Ali 52 / Male` to
`Patient Name: Mohammed Irfan Ali Age / Sex: 52 / Male Address: ...`.
It is a no-op where ordering was already correct.

**Bug found while building it:** the first version grouped rows using
every entry in Tesseract's `image_to_data`, which interleaves
page/block/paragraph/line rows carrying empty text and page-spanning
boxes. Their heights swamped the row tolerance and scrambled the output.
It now groups word-level entries only.

---

## 2026-09-14 — Medical NER for clinical free text (opt-in)

**Status:** Active, off by default (`--medical-ner`)

**Why:** a diagnosis is free text, not a pattern — no regex reaches it.
Presidio ships `MedicalNERRecognizer`, wrapping HuggingFace
`blaze999/Medical-NER`.

**Evidence:** with reading-order, recall 81.2% → **88.2%**. Both
remaining diagnosis leaks closed.

**Why not on by default:** it pulls in transformers and torch and
downloads a model on first use. It also over-redacts mildly — "Ward /
Bed" and "Age / Sex" labels get caught as clinical terms — which is
acceptable for redaction but surprising if unexpected.

---

## 2026-09-14 — Best measured configuration: Paddle + all improvements

**Status:** Active (not the default; Tesseract stays default for speed)

**Evidence:** `--ocr paddle --medical-ner` with the custom recognizers
and reading-order scores **94.1%** redaction recall (80/85), against
88.2% for the same configuration on Tesseract. `PERSON` and
`PHONE_NUMBER` leaks fall to zero.

Full progression on the same 20 images: 74.1% (Tesseract PSM 3) → 76.5%
(PSM 4) → 81.2% (custom recognizers) → 88.2% (reading-order + medical
NER) → 94.1% (Paddle).

**What remains:** five leaks, all span-boundary failures. Four are
multi-line or multi-token `LOCATION` values where part of an address is
redacted and the locality or PIN survives; one is a date. Merging
adjacent fragments of the same entity into one region is the next fix,
and it is a geometry problem rather than a recognizer gap.

**Note on method:** this run was predicted to win and did, but two
earlier predictions in this project did not survive measurement (Paddle
appearing better on entity counts while leaking more; RapidOCR assumed
to share Paddle's models). Configurations are not adopted here on
reasoning alone.

---

## 2026-09-14 — Recall redefined to count every unredacted item

**Status:** Active — supersedes the "recall on legible PII" figures in
every entry above

`score_run.py` now reports recall over **all** known PII. Items OCR never
read are counted as leaks (`leaked_ocr_miss`), not excluded.

**Why:** the previous definition excluded items OCR could not read in the
input, reasoning that an OCR failure should not be scored against
Presidio. That was wrong. The user opened the output folder and saw
unredacted names and email addresses in images the scorer had recorded as
having zero misses.

**Evidence:** `19_loan_application.png` — a photographed laptop screen —
shows name, date of birth, mobile number, email and address completely
unredacted. All five were bucketed as "not legible" and excluded, so the
image contributed nothing to the leak count.

**Corrected figures** (previous legible-only number in brackets):

| configuration | recall | still visible |
|---|---:|---:|
| Tesseract PSM 3 baseline | 65.6% (74.1%) | 33 |
| + custom recognizers, PSM 4 | 71.9% (81.2%) | 27 |
| + reading-order + medical NER | 78.1% (88.2%) | 21 |
| Paddle + all of the above | 83.3% (94.1%) | 16 |

**Lesson:** the metric flattered the tool by roughly 9 points, and did so
most where the tool was weakest — documents OCR handles badly. A scoring
rule that excuses a whole failure mode will hide exactly the failures
worth fixing. Eleven of the sixteen remaining leaks are PII no OCR engine
read, which makes OCR quality, not recognizer coverage, the dominant
remaining problem.

---

## 2026-09-14 — Ground truth relabelled from the images; recall reported as a range

**Status:** Active — supersedes every figure in entries above

Two changes, both prompted by the user opening the output folder and
seeing unredacted names and emails that the scorer reported as clean.

**1. Ground truth was under-counted by 35%.** The real documents had been
labelled from a downscaled contact sheet. Re-reading each image at full
resolution found 130 PII items against the previous 96 — the lab report's
age/gender line and all five test results, the prescription's age and all
three medications, all six bank transactions and the closing balance, and
the boarding pass's flight number, times and seat. The omitted items were
disproportionately ones the pipeline does *not* redact, so every earlier
figure was optimistic.

**2. Recall is now a range, not a point.** The scorer had this wrong
twice: first excluding items its OCR could not read (flattering), then
counting them all as leaks (over-correcting — a verified-redacted email
was reported visible because Tesseract could not read the input). An item
is now `leaked` only when readable in the output, `redacted` only when
readable before and not after, and `unverifiable` otherwise.

**Current figure:** Tesseract with every improvement scores
**67.7% – 76.2%** of 130 items — 88 confirmed redacted, 31 confirmed
visible, 11 unverifiable.

**What the category breakdown exposes:** recall is not uniform, and the
single number hid a category with *zero* coverage.

| category | tesseract | paddle |
|---|---:|---:|
| identifier | 84% | 88% |
| health | 83% | 100% |
| quasi_identifier | 67% | 78% |
| contact | 62% | 72% |
| financial | **0%** | **0%** |

Paddle with the same improvements scores 75.4% – 84.6%. Financial is 0%
on *both*, which isolates it as a recognizer gap rather than an OCR one —
the only category where a better reader changes nothing.

Every transaction line and balance on a bank statement survives,
including `UPI - Apollo Pharmacy`, which discloses healthcare usage from
financial data. No recognizer covers transaction descriptions.

**Lesson:** the harness was measured against labels written by the same
process that built it, and agreed with itself. Independent labelling —
here, reading the images rather than trusting the earlier pass — moved
the headline by roughly 10 points and revealed an entire uncovered
category.

---

## 2026-09-14 — Ground truth narrowed to what identifies a person

**Status:** Active — supersedes the 130-item ground truth above

77 items, down from 130. Removed: bare gender, standalone age, blood
group, lab values, amounts, balances, transaction lines, bill periods and
due dates, institution names and addresses, bank helplines, IFSC codes
(which identify a branch), flight numbers, seats and times.

**Why:** the previous pass over-corrected. Having found the original
labels under-counted, the fix swept in anything present on the page, then
scored the harness as failing for not redacting a seat number or a
closing balance. "Financial data is entirely unredacted" was reported as
a headline finding; a bare amount identifies nobody, so it was never a
finding at all.

**Corrected figures:**

| engine | recall | confirmed leaked |
|---|---|---:|
| tesseract | 83.1% – 94.8% | 4 |
| paddle | 85.7% – 97.4% | 2 |

Both remaining Paddle leaks are the same multi-line address.

Health items live in a separate `sensitive` tier rather than the headline,
because whether a medication counts as PII is a policy question. Both
engines redact all five.

**Lesson, third time on the same theme:** this metric has now been wrong
by excluding too much, by counting too much, and by mislabelling what
counts. Each error moved the headline by roughly ten points in whichever
direction the last correction pointed. The number is only ever as good as
the definition behind it, and the definition deserves as much scrutiny as
the code.

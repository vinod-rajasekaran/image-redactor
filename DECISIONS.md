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

---

## 2026-09-14 — Parallel preprocessing variants, unioned; duplicate analysis removed

**Status:** Active

`process_image` now OCRs three preprocessed copies of each image — plain
RGB, greyscale, and CLAHE+Otsu — concurrently with the face/QR detectors,
and unions the resulting boxes. `--single-variant` disables it.

**Why:** no single preprocessing wins on every document, and the failures
land on opposite documents. RGB recovers nothing from a photographed
laptop screen (0 of 5); CLAHE+Otsu fixes that screen but destroys the
coloured gradient on a PAN card (0 of 4). Items recovered of 77: RGB 66,
greyscale 67, CLAHE+Otsu 63, **union 71**.

This was nearly a self-inflicted regression. The plan had been to *swap*
to the enhanced path, which would have taken the Aadhaar and PAN cards
from 7 recovered items to 1 — the highest-value documents in the set,
broken by a change that would have been described as a fix. The union
came from the user asking whether this meant parallel paths and merging.

**Boxes are now drawn directly** rather than via
`ImageRedactorEngine.redact()`, which re-ran the entire OCR and analysis
pass a second time — 7.6s of a 17.4s run. Drawing directly also keeps
output in colour, which the greyscale variants would otherwise have
destroyed.

**Threads, not processes:** pytesseract shells out and releases the GIL.
Verified byte-identical results threaded versus serial across all 20
images before adopting, since silent intermittent divergence would be the
worst possible failure here.

**Result:** Tesseract with the union scores **87.0% – 98.7%** with a
single confirmed leak, beating single-variant Paddle (85.7% – 97.4%, two
leaks) at a tenth of the runtime. The remaining leak is the multi-line
address on the driving licence — a span-merging problem, not a reading
one.

**Cost, and a caveat:** without medical NER the union adds 6% (22.9s →
24.2s for 20 images). With `--medical-ner` it adds 44% (32.9s → 47.5s),
because the transformer model is compute-bound in-process and runs once
per variant. It should run once per image instead; that is not yet fixed.

---

## 2026-09-14 — Evaluated against IndiaPII-Bench (maskflow-ai)

**Status:** Active

`benchmark_indiapii.py` scores our recognizer stack against
[IndiaPII-Bench](https://huggingface.co/datasets/maskflow-ai/indiapii-bench)
— 2,000 synthetic Indian documents, 12,065 labelled PII spans and 1,403
PII-shaped decoys, CC-BY-4.0.

**Why it is worth having:** it is plain text, so it isolates the
recognizer layer from OCR entirely — a miss here is a recognizer gap and
nothing else. And it supplies **hard negatives**, which our own ground
truth has none of. Our sample set can only measure recall; it is
structurally blind to over-redaction.

**Result on 400 documents: 76.2% recall on real PII.**

Our custom recognizers validated at 100%: `IN_BANK_ACCOUNT`, `IN_IFSC`,
`IN_DRIVING_LICENCE`, alongside `IN_PAN`, `IN_AADHAAR`, `IN_VOTER`,
`IN_PASSPORT` and `PHONE_NUMBER`.

**The important correction — `PERSON_NAME` scores 59%.** An earlier entry
concluded `en_core_web_lg` was fine for Indian names on the strength of a
19/20 hand-picked sample. Against 416 varied names it finds 59%. The
sample was too small and biased toward common, well-attested names;
misses cluster on single-token and rarer names (*Syediliyas*,
*Arulananthan*, *Garbhadharin*, *Priyavaarshini*). The NER model is a
real weakness, not a settled question.

**Decoys:** only **3%** are flagged as the type they mimic — and every
one of those is `NON_VERHOEFF_AADHAAR_SHAPED`, which we flag *by design*.
The OCR-tolerant Aadhaar fallback deliberately ignores the checksum,
because in an image a checksum failure usually means a misread digit. In
their text domain there is no OCR, so a checksum failure really does mean
"not an Aadhaar" and flagging it is an error. **The same behaviour is
correct in our domain and wrong in theirs.** Zero false positives on
PAN-shaped invoice numbers, order IDs or timestamps.

**Gaps their entity set exposes:** we have no recognizer for `UPI_VPA`,
`ABHA_NUMBER`/`ABHA_ADDRESS` (health IDs) or `PIN_CODE`, and score 0% on
`AADHAAR_MASKED` (partially masked numbers such as XXXX XXXX 1234).
`IN_VEHICLE_REGISTRATION` manages only 43% against their hyphenated
formats.

**Worth borrowing from MaskFlow's approach:**

- *Hard negatives in the test set.* The single biggest methodological
  gap on our side. Our ground truth cannot detect over-redaction at all.
- *An evidence layer.* MaskFlow records a metadata-only, verifiable trace
  of what was masked, never the values. Our `summary.json` lists types
  and counts but offers no way to prove a run redacted what it claims.
- *Typed, numbered placeholders* (`<AADHAAR_1>`). Not directly applicable
  to black boxes, but the numbering makes an audit trail legible.

**Not applicable:** MaskFlow is a text/LLM-gateway masker. It has no OCR,
no faces, no QR codes — the entire failure surface this project spends
its time on does not exist there.

---

## 2026-09-14 — Merge stacked same-entity boxes into blocks

**Status:** Active (`--no-merge-blocks` disables)

Boxes of one entity type that sit within ~1.6 line-heights of each other
and overlap horizontally are replaced by their enclosing rectangle.

**Why:** a wrapped address is detected line by line and often only
partly. On the sample driving licence the second line matched
"Bengaluru, Karnataka" while the first matched only a 61px fragment at
its right end, leaving "22, Indiranagar 100ft" legible. Redacting each
box separately can never fix that, because the missed words were never
detected. The enclosing rectangle of the cluster covers them, since the
second line's horizontal extent reaches past where the first line failed.

**Result: the last confirmed leak is gone.** Tesseract with everything
enabled scores **88.3% – 100.0%** of 77 items: 68 confirmed redacted,
**0 confirmed visible**, 9 unverifiable. Cost is +0.7 percentage points
of blacked-out area.

**Two bugs found while building it, both silent:**

- Clustering in one pass over reading order stranded the leftmost
  fragment, because the cluster only grew wide enough to reach it *after*
  a later box joined. Merging now repeats until nothing changes.
- The line-gap threshold used a median height computed across *all*
  entity types. The address lines sat 21px apart while that global median
  was 17, so they failed to merge by four pixels — and an isolated test
  had passed only because its median happened to be 21. Heights are now
  per label, which is the only meaningful way to measure them.

**Rejected alternative:** a YOLO layout model
(`arnabdhar/YOLOv8-nano-aadhar-card`) located the same address block
correctly, including on the laptop-screen form our OCR cannot read. It
was not adopted: its weights are Apache-2.0 but `ultralytics`, the only
practical way to run them, is **AGPL-3.0** — network copyleft, and the
only non-permissive dependency this project would have. Its non-ADDRESS
classes were also unusable outside Aadhaar cards, labelling a statement
period and "UPI - Swiggy" as AADHAR_NUMBER. Solving the problem
ourselves cost twenty lines and no licence exposure.

**Known, pre-existing and unrelated:** several documents black out the
whole label column. It is present with merging disabled, so it is not
caused by this change; it has not been diagnosed.

---

## 2026-09-14 — Vision scoring resolves the unverifiable bucket

**Status:** Active

`score_run.py` now reads an optional `vision_verdicts.json` from the run
folder. Where a verdict exists for an item it overrides the OCR verdict.

**Why:** the OCR scorer can only see what its OCR sees, and on exactly
the low-contrast photos where redaction fails it reads almost nothing. It
was therefore wrong in both directions at once — reporting visible PII as
"unverifiable", and, worse, as "redacted". Reading the output of
`19_loan_application.png` it recovered only the words "personal" and
"details" from a page whose address is plainly legible; on
`15_job_application_form.png` it garbled `98765` into `gos765` and so
scored a clearly visible phone number as redacted.

**Result with vision verdicts: 96.1% (74/77), 3 confirmed leaks, zero
unverifiable.** The range collapses to a point because nothing is left
unknown.

The three leaks are all on the two hardest photographs: a given name and
a phone number still legible on the job-application form, and the
residential address on the laptop-screen loan form.

**This corrects a headline claim.** The previous entry reported "zero
confirmed leaks" at 88.3% – 100.0%. There were three; the scorer could
not read them.

**Limitations, stated plainly:**

- The pass is manual. There is no API key in this environment, so it was
  done by viewing each output image in-session, not by an automated
  vision call. It is an artifact, not a reproducible scorer.
- Verdicts are tied to the images in that run folder. Re-running into the
  same folder name would silently apply stale verdicts to new output.
- Judgement calls are recorded in the file: a fragment too short to
  identify anyone (a PIN-code tail, a surname ending) counts as redacted,
  while a legible given name counts as leaked, on the principle that
  over-reporting leaks is the safer error.

**Fifth correction to this metric.** It has now been wrong by excluding
unreadable items, by counting them all as leaks, by mislabelling what
counts as PII, by under-reading the output, and by reporting a leak count
of zero. Every correction moved the headline. The consistent cause is
that a scorer built from the same components as the tool shares its blind
spots.

---

## 2026-09-14 — Automated vision scoring (`vision_score.py`)

**Status:** Active

Shows each redacted output image to `claude-opus-5` alongside the values
ground truth says were on that page, and asks which remain readable.
Writes `runs/<run>/vision_verdicts.json`, which `score_run.py` prefers
over its own OCR verdicts. Needs `ANTHROPIC_API_KEY` in `.env`.

**Final figure: 93.5% (72/77), five confirmed leaks, zero unverifiable.**

**It beat both previous scorers, including the manual pass.** Sequence on
the same run:

| scorer | recall | leaks found |
|---|---|---:|
| OCR | 88.3% – 100.0% | 0 |
| manual, by eye | 96.1% | 3 |
| **vision** | **93.5%** | **5** |

The two the manual pass missed: `12, MG Road, Andheri West,` on the
synthetic Aadhaar card, where `12, MG R` is legible before the box and
`shtra - 400058` after it — enough to reconstruct the address — and
`Deepika Iyer` on the rental agreement. The eyeball pass had not reviewed
the synthetic images at all, assuming OCR was reliable there. It was not.

The five leaks are all partial-coverage failures on address and name
fields, not missed detections.

**Prompt choice that matters:** the model is told to answer "leaked" when
a value is ambiguous, because under-reporting a leak is the more
dangerous error in a privacy audit. `Deepika Iyer` is exactly that case —
the manual pass called a visible `lyer` fragment redacted; the model
called it leaked. Both defensible; the scorer is deliberately biased
toward the safer answer.

**Sixth and final correction to this metric.** It has been wrong by
excluding unreadable items, by counting them all as leaks, by
mislabelling what counts as PII, by under-reading the output, by
reporting zero leaks, and by trusting a manual pass that skipped half the
corpus. The through-line every time: a scorer that shares the tool's
blind spots cannot find the tool's failures.

---

## 2026-09-14 — Vision annotation of inputs: adopted as an auditor, rejected as a coverage metric

**Status:** Active as a ground-truth auditor (`annotate_inputs.py`);
per-region coverage built, measured, and removed.

**Adopted — auditing the labels.** The label set has been this project's
largest single source of error, swinging 96 -> 130 -> 77 items across
three revisions and moving the headline recall about ten points each
time. `annotate_inputs.py` asks Claude what personal data is on each
*input* page and diffs it against `ground_truth.json`. On the sample set
it surfaced two items never labelled: a signature bearing a name on the
PAN card, and the prescribing doctor's name on the synthetic prescription.

It reports rather than rewrites. What counts as PII is a policy question
and belongs to a person, and keeping the labels human-owned also keeps
them independent of the model that grades the output.

The five "unseen" items — diagnoses and medications — are a prompt/policy
mismatch rather than a miss: the annotation prompt excludes
non-identifying data, while ground truth tracks them in a separate
`sensitive` tier.

**Rejected — per-region coverage.** The plan was to measure what fraction
of each annotated box the redactor actually covered and flag anything
under 100% as a likely leak. Every outstanding leak is a partial-coverage
failure, so the signal would have been valuable, and the measurement is
deterministic and needs no model call at scoring time.

It does not work, because the boxes are not accurate enough. Rendered
over the source image they are inconsistently off by roughly one text
row: on the sample Aadhaar card the `person_name` box sat on the date of
birth and the `date_of_birth` box sat on "Male", while three others were
correct. Coverage computed from them reported **0% for a field that is
plainly blacked out**, and the numbers showed no correlation with the
five known leaks.

Vision models are reliable about *what* is on a page and unreliable about
precisely *where*. The box coordinates are still written to
`input_annotations.json` for human inspection, but nothing is computed
from them. A metric that produces confident wrong numbers is worse than
no metric — which is the most expensive lesson of this project, learned
six times over on the scorer before this.

**Also rejected earlier, for the same underlying reason:** replacing
legibility scoring with geometric box matching. A box can be ~85% covered
and still leak — `12, MG R` plus `shtra - 400058` reconstructs an address
— so "is it still readable" remains the right question.

---

## 2026-09-14 — Documentation upkeep is part of the change

**Status:** Active

`CLAUDE.md` now opens with a rule: `README.md`, `DECISIONS.md` and
`CLAUDE.md` are updated in the *same commit* as the change they describe,
with a table of which file carries what.

**Why:** the three files drifted badly. `CLAUDE.md` still described
`ocr_backends.py` and `visual_redaction.py` weeks after they moved into
the package, referenced an `output_images/` folder and a
`redaction_report.json` that no longer exist, and claimed there was no
test suite after one had been added. `README.md` carried recall figures
from three revisions earlier and documented a removed `--output` flag.

Stale guidance is worse than none. A default whose rationale has gone
missing gets "simplified" away by the next session — and every default
here that looks wrong is load-bearing, because the obvious choice was
measured and rejected.

**The rule that matters most:** when a published number turns out to be
wrong, say so explicitly here and correct it everywhere it appears. The
headline recall has been corrected six times; each correction is recorded
with what was wrong and why. That record has proven more useful than any
individual number, because the same failure — a measurement that shares
the tool's blind spots — kept recurring in new disguises.

---

## 2026-09-14 — Two more open datasets, both permissively licensed

**Status:** Active

Searched for open Indian PII datasets under MIT or Apache-2.0 —
IndiaPII-Bench, already in use, is CC-BY-4.0. Two qualify.

**`somukandula/maskara-indian-pii-200k` — MIT, text.** 268k rows,
character-level spans, 17 entity types including AADHAAR, PAN_CARD,
UPI_ID and VEHICLE_REG. Fully synthetic, with a `real_world_eval` split
that is not template-generated, hard negatives, and — the reason it earns
a place beside IndiaPII-Bench — an **`ocr` domain of deliberately
OCR-corrupted text**. `benchmark_maskara.py` runs it.

Result on the 2,600-row real-world split: **75.6% overall**. The `ocr`
domain scores **93%, the highest of any domain**, which is direct
evidence for the OCR-tolerant Aadhaar fallback rather than the indirect
argument that has justified it so far.

Gaps it exposes, and they are mostly one gap:

| entity | recall | why |
|---|---:|---|
| DRIVER_LICENSE | 0% | their `DLFY1997840749` puts letters where our regex expects RTO digits |
| VEHICLE_REG | 22% | spaced form `AP 51 NK 6401` — we only match unspaced |
| PHONE | 66% | `(+91) 01770 42568` defeats Presidio's phone recognizer |
| PAN_CARD | 70% | spaced form `AGNVL 0925 B` |
| UPI_ID | 62% | no recognizer; partially caught as EMAIL |

**Spacing is the theme.** PAN and vehicle registration both fail on spaced
forms, which people genuinely write and OCR genuinely produces. That is a
real fix, not an artefact of their generator. The driving-licence format
is arguably theirs being non-standard — worth matching loosely rather
than contorting our regex to it.

Hard negatives: 86/200 flagged, higher than IndiaPII-Bench's 3% on the
mimicked type. Not yet broken down by cause.

**`jaganadhg/cheque-synthetic-images` — Apache-2.0, images.** 295
synthetic Indian cheques across four bank layouts, with ground-truth
bounding boxes for payee name, account number, IFSC, date, amount and
signature. Not yet used.

It is worth more than its size suggests: it is an **image** set with
**human-authored boxes**, so it can measure per-region coverage — the
metric that had to be abandoned because vision-generated boxes were off by
about a text row. It would also be the first test data here that nobody
on this project labelled.

**A licence caveat:** the paper announcing it states CC-BY-SA-4.0 in its
metadata while the Hugging Face card says `apache-2.0`. The companion
`cheque-field-annotations` set (real cheques) is licensed `other` and
should be left alone. Confirm the licence before depending on it.

---

## 2026-09-14 — Cheque benchmark: the 93.5% does not generalise

**Status:** Active — `cheque_benchmark.py`

20 synthetic Indian cheques from `jaganadhg/cheque-synthetic-images`
(Apache-2.0), with human-authored boxes for payee name, account number
and signature. The first test data in this project that nobody here
labelled.

**Result: 2 of 60 PII regions fully covered.** Mean coverage — account
number 17%, payee name 28%, signature 13%.

Verified by eye rather than trusted, since loose boxes would dilute the
ratio. The failure is real: on `syndicate_syn_0049` the payee name
"J. Ravi Kumar Singh" is entirely unredacted, the account number has a box
over its middle with digits legible either side, and the signature is
untouched.

**Three causes, none of them new, all of them worse here:**

- **Handwriting.** The payee name is handwritten on every cheque, and
  neither OCR engine reads it. Listed as a limitation for a while; this
  is the first corpus where it is the *dominant* failure rather than an
  edge case.
- **No signature detection.** We detect faces and codes. A signature is
  personal data — the ground-truth auditor flagged one on the PAN card
  too — and nothing looks for it.
- **Partial coverage** on the account number, the same span-boundary
  failure as everywhere else.

**What this says about the headline.** 93.5% was measured on 20 printed
forms and ID cards, half of them generated by this project. Cheques are a
document type the pipeline has never seen, with handwriting and signatures
throughout, and it performs dramatically worse. The number was never
wrong, but it describes that corpus and not Indian documents in general —
and only independent test data could show that.

**Coverage as a metric is vindicated here.** It was removed when computed
from vision-generated boxes, which were off by about a text row. Given
trustworthy boxes it produced a signal that matched what the eye sees,
without a model call. The distinction was the box quality, not the metric.

---

## 2026-09-14 — Signature detection

**Status:** Active, on by default

`detect_signatures()` in `redactor/detect.py`. Signature coverage on the
cheque benchmark rises from **13% to 51%**, with **zero false positives**
on the main corpus and its recall unchanged at 93.5%.

**Why it was needed:** a signature is personal data and nothing looked for
one. The cheque benchmark measured 13% of signature area redacted, and the
ground-truth auditor had separately flagged an unlabelled signature on a
PAN card.

**Pure shape analysis was tried and rejected.** Ranking every connected
component by how much it sprawls put the true signature at rank 3-8 on the
sample cheques, so taking the top few would have blacked out unrelated
ink.

**What works is label-anchored.** OCR already reads the page; a signature
cue word ("sign", "signature", "signatory") says *where to look*, and
connected components find the ink. No page geometry is assumed, so the
same code works on a cheque, a card or a prescription. Cue words are
matched as whole tokens — "signs and symptoms" on a medical note must not
summon a box.

**A false positive caught before shipping.** The first version boxed the
entire *label column* of a PAN card: dilation had merged Name/Father's
Name/DOB/PAN/Signature into one sprawling blob that scored well on area
and fill. Rendering the box over the source image showed it immediately.

The fix uses a measurement made earlier while characterising the problem:
cursive connects and print does not. A signature region averages ~24
connected components with 56% of its ink in the largest; a printed name
field averages ~239 with 15%. Candidates are now checked against the
*undilated* ink and rejected if they look like print.

**The trade taken:** that check cost 2 of 15 detections (15/20 → 13/20)
and removed the false positive. Accepted deliberately. The usual
preference here is recall over precision, but a *misplaced* box is not
over-redaction — it damages the document without protecting anything, so
placement is judged on precision.

**Its ceiling is the label.** The misses are the cheques where OCR never
read the cue word. A signature with no printed label nearby will not be
found.

---

## 2026-09-14 — Land record and property registration recognizers

**Status:** Active

`IN_LAND_RECORD` (survey / khasra / khata numbers) and
`IN_PROPERTY_REGISTRATION` (sub-registrar document numbers). On the
synthetic document pack, `SURVEY_NUMBER` coverage goes **0% → 77%** and
`LAND_REGISTRATION_NUMBER` **0% → 100%**; overall pack coverage 86% → 90%.
Main corpus unchanged at 93.5%, and IndiaPII-Bench decoys unchanged at 4%.

**Why they are context-anchored rather than shape-matched.** There is no
single format to match. The plot identifier is a survey number in the
south and west, a khasra in the north, a khesra in the east and a dag in
the northeast; ownership records are jamabandi, khatauni, khatian, pahani
or a 7/12 extract by state; registration numbers are issued per
Sub-Registrar Office, so the scheme varies by office rather than merely by
state. Real formats would have to come from state portals — Bhulekh,
Dharani, Kaveri, Mahabhulekh — each documenting its own.

A regex written without that research would have been fitted to whatever
the nearest example invented, passing its own benchmark and telling us
nothing about real documents. That is the RapidOCR mistake — assuming a
format from a plausible source and finding out only after measuring.

So these follow the pattern already validated for `IN_BANK_ACCOUNT`, which
reached 100% on an independent benchmark without knowing any bank's
numbering scheme: a permissive shape, a base score too low to fire alone,
and the well-documented *labels* doing the work.

**Confirmed mid-build.** The first registration pattern assumed
prefix-serial-year and missed `REG-2026-28726`, which is
prefix-year-serial. Rather than flip it to match the example in hand —
fitting to a generator again — the pattern now accepts either order, since
neither is canonical and the label gates it regardless.

**Two limitations, accepted openly when this was agreed:**

- It only fires next to a label. A bare survey number in free text is
  missed, by design.
- **There is no independent test data for it.** The only corpus exercising
  these entities is the same synthetic pack that prompted them, so the
  77% and 100% above prove the recognizers work *on that generator* and
  nothing more. Real land documents would settle it, and bring back the
  provenance problem that ruled out the Roboflow Aadhaar set.

---

## 2026-09-14 — One `datasets/` tree, one annotation schema

**Status:** Active

Validation corpora had accumulated as three top-level folders —
`input_images/`, `cheque_images/`, `pack_images/` — with three
near-identical annotation files and every script hardcoding its own paths.
Adding a fourth corpus meant editing all of them, and the schemas had
already drifted: `ground_truth.json` carried `text` but no `box`, the two
region files the reverse.

They now live under `datasets/<name>/{images,annotations.json}`, loaded
through `redactor.datasets.load(name)`. One schema carries both `text` and
`box`, each optional, at least one present — because they answer different
questions. `text` supports legibility scoring, the headline metric, since
a box 85% covered can still leak. `box` supports coverage, which is weaker
but deterministic and free of a model call, and is only trustworthy where
the boxes were computed at render time or authored by a person.

`datasets/README.md` records what each corpus is, its licence and its
provenance, and each `annotations.json` repeats it in `_meta` where a
script can read it.

**Correction, made the same day.** The tree was first committed with
`datasets/*` gitignored wholesale, on the stated reasoning that the
documents corpus held real photographs. It does not. Images 11–20 were
generated with an OpenAI image model and only *look* photographed —
perspective, glare, low contrast are what the generator was asked for,
which is also why they are the hardest images here. The pack is Claude-
generated, and the cheques are publisher-declared synthetic under
Apache-2.0. Nothing in the tree needed hiding, and hiding it cost the one
thing a benchmark is for: a clone that reproduces the numbers.

`documents/` and `pack/` are now tracked — 3.6MB, and the headline
figures reproduce with no downloads. `cheques/images` (87MB) and `text/`
(93MB) stay out for size alone, both re-fetchable in one command, with
the cheque annotations and provenance still tracked so the Apache-2.0
attribution lives in the repo rather than in a download. `runs/` and
`input_annotations.json` remain ignored on the original reasoning, which
holds for them: they describe whatever images a *user* fed the tool.

**The lesson worth keeping:** "may contain PII" was an assumption I never
checked, and it propagated into three files as though it were a finding.
A provenance claim is a fact about where bytes came from — it gets
recorded when the bytes arrive, or it is not knowable later.

**Verified as a move, not a rewrite:** documents 72 redacted / 5 visible,
cheques acno 17% / name 28% / sign 51%, pack 90% with 47/87 fully covered
— every figure identical to before.

**Also added to `CLAUDE.md`:** re-check the repo layout before any
significant push. Two structural problems have already been caught and
fixed here — the scattered corpora above, and `evaluate_redactor.py`
reaching 782 lines doing seven jobs. Both were cheap when caught and would
have compounded. The rule carries its own guard: a structural change is
only safe with a demonstration that behaviour did not move, and without
one it is a rewrite.

---

## 2026-09-15 — Cheque corpus trimmed to 10 and committed

**Status:** Active — `datasets/cheques/`

The cheque images were the one corpus left out of the repo yesterday, on
size: 87MB for 20. They are now **10 images, 44MB, tracked**, so every
image benchmark in this file reproduces from a bare clone.

**What the 10 are.** All four bank layouts (axis 3, canara 3, icici 2,
syndicate 2), including `syndicate_syn_0049` — the cheque cited above as
the concrete failure, where the payee name is entirely unredacted. A
benchmark that drops its own worst case is not a benchmark.

**Restated on the slice** (the 20-cheque figures above stand as measured):

| field | 20 cheques | 10 cheques |
|---|---:|---:|
| account number | 17% | 27% |
| payee name | 28% | 37% |
| signature | 51% | 53% |
| fully covered | 2/60 | 2/30 |

**The slice is easier than the full set, and not by accident.** Taking the
first images per bank is not random sampling; account number and payee
name both come out ~10 points better. Quote these numbers against this
slice, not as an improvement — nothing in the pipeline changed. The
conclusion is the one that matters and it is unmoved: **2 regions in 30
fully covered.** 93.5% describes printed forms, not cheques.

**Why not compress further.** 2365×1065 with paper texture and ~138k
unique colours: lossless PNG re-encoding recovered 5%. JPEG q95 would be
15MB instead of 44MB, and was rejected — pixels are the input to both the
OCR and the coverage measurement, so re-encoding them lossily is a
re-measurement wearing a compression's clothes.

**Bug found while doing this.** `cheque_benchmark.py --limit N` wrote the
annotation file with `json.dumps(regions)`, which dropped the `_meta`
block — the licence and upstream URL — and wrote a bare list where the
loader expects `{"pii": [...]}`. Harmless while the file was gitignored
and rebuilt every time; a silent licence deletion now that it is tracked.
It now reads the existing `_meta` back and writes through
`datasets.save()`.

---

## 2026-09-15 — Cheques stored as JPEG, and the numbers moved

**Status:** Active — supersedes the coverage figures in *Cheque corpus
trimmed to 10 and committed*, earlier today

44MB of PNG for 10 images was most of the repo. Stored as **JPEG q95 with
no chroma subsampling** they are 14MB. The same 10 cheques, the same
boxes — the annotations carried over verbatim, since dimensions are
unchanged and the boxes are pixel coordinates.

**The figures were re-measured, not carried over, and they moved:**

| field | PNG | JPEG q95 |
|---|---:|---:|
| account number | 27% | **20%** |
| payee name | 37% | **46%** |
| signature | 51%¹ → 53% | **58%** |
| fully covered | 2/30 | **0/30** |

¹ the 51% is from the 20-cheque set, kept for continuity.

**This is the finding, and it is not about JPEG.** Re-encoding at q95 is
invisible to the coverage metric itself — an unredacted re-encode of every
cheque, scored against its own source, reports **0.00% covered, worst
region 0.00%**, so not one pixel moved past the 30-unit threshold. Yet the
same pipeline on the same pages now covers account numbers 7 points worse,
payee names 9 points better, and fully covers nothing at all. Sub-threshold
changes no metric here can see are enough to flip what OCR reads and where
the boxes land.

So cheque performance is not merely low, it is **unstable**: it moves
under a perturbation small enough to be undetectable. That strengthens
rather than softens the existing conclusion. The headline stays 93.5% for
printed forms, and cheques stay the proof it does not generalise.

**Why this is sound here and was not for the source PNGs.** Lossy
re-encoding is a re-measurement, never a compression — so it is only
acceptable when you actually re-measure and publish what you get. That was
done. The alternative, carrying the old numbers across a pixel change,
would have published figures no image in the repo produces.

**`cheque_benchmark.py --limit N` now writes JPEG too**, so a refetch
cannot silently rebuild a PNG corpus that scores differently from the
committed one.

**Addendum — the 42MB of PNG blobs stay in history.** Converting the
cheques did not shrink `.git`; it grew it, 47MB to 60MB, because the
PNGs remain in the commit that added them. A `filter-branch` over the
unpushed range would remove them, and was deliberately declined: linear,
unrewritten history is worth more than 42MB.

**Do not revisit this after the branch is pushed.** The rewrite is cheap
and safe only while nothing downstream references those commits. Once
pushed it is a forced update that breaks every clone, to reclaim space
that a single `git clone --depth 1` already avoids. The working tree is
14MB either way.

---

## 2026-09-15 — A 50-document photoreal corpus, and 79.0%

**Status:** Active — `generate_openai_documents.py`, `datasets/generated/`

Fifty photoreal Indian documents across eight types, rendered by
`gpt-image-2` from values drawn by the new `redactor/synth.py`, verified
by Claude, and **never tuned against**. 224 ground-truth items, three
times the `documents/` corpus.

**Result: 79.0% redacted — 177 of 224, 47 leaks.** Against 93.5% on
`documents/`. That gap is the honest size of the home-field advantage:
half of `documents/` was drawn by this project, and the label set was
revised three times while looking at it.

| field | n | redacted |
|---|---:|---:|
| every structured identifier (Aadhaar, PAN, DL, account, IFSC, phone, email, DOB, survey, registration) | 117 | **100%** |
| address | 37 | 76% |
| person name | 50 | 60% |
| medical record no. | 6 | 50% |
| doctor name | 6 | 33% |
| FIR number | 6 | 17% (no recognizer) |
| diagnosis | 6 | 0% (no recognizer) |

Excluding the 12 items nothing here claims to detect: **83.0%** (176/212).

**The finding: the regex layer is solid and the NER layer is not.** Every
recognizer written for this project held at 100% on unseen documents —
including the land and survey recognizers added blind, without knowing the
formats. What fails is names: **20 of 47 leaks are a person's name** that
spaCy missed once glare, perspective and a form grid were in the way.
`documents/`'s printed half is clean enough for NER to succeed, so this
was invisible there.

**Why the ground truth is what was rendered, not what was asked for.** An
image model can drop digits and invent text, and cannot say where it put
anything. So each finished page is read back by Claude and the annotation
records *that*; where it differs, the request is kept under `requested`.
The verifier is deliberately a different vendor from the generator,
because a model grading its own output can confirm a value it
hallucinated. As it turned out `gpt-image-2` altered **none** of the 224
values — which is a measurement rather than a lucky assumption precisely
because the read-back happened.

**No bounding boxes**, though an image generator would normally be the one
source that could provide them: here it cannot, and vision-derived boxes
were already measured at about a text row off and the metric built on them
removed. This corpus scores by legibility.

**Two bugs caught before spending on 50 images:**

- The verifier counted the grey portrait *silhouette* as a face. That
  would have written a permanent `face: 1` into every ID-card annotation
  for something YuNet cannot detect — a failure no tool could ever pass.
- Verdicts were matched to fields by printed label, which differs per
  template ("Name" / "Patient Name" / "Account Holder"). Now keyed on the
  category.

**And one in the analysis, which is the recurring lesson.** The first
per-field breakdown reported 0 leaks in every field — while the scorer it
was reading had just reported 47. The join looked for a `verdicts` list;
the file is a flat `{value: verdict}` map, so every lookup missed and
every field showed 100%. A clean, plausible, entirely wrong table. It was
caught only because a total contradicted a number from two minutes
earlier.

**Stored as JPEG q95**: 126MB of PNG to 28MB. Sound here for the reason it
was not for the cheques' source PNGs — no measurement predated the
encoding, so the stored file simply *is* the corpus. A photographed
document arrives as a JPEG anyway.

**Cost:** ~$3.50 in image generation, 50 Claude vision calls. The script
prints an estimate and asks before spending, is resumable so a crash never
pays twice, and `--verify-existing` re-runs the read-back without
redrawing anything.

---

## 2026-09-15 — Realism probe: the documents were the problem, not the photography

**Status:** Active — `--realism`, `compare_realism.py`

The first 50 came out as fifty near-identical A4 forms: spacious
label:value rows, clean English sans-serif, pristine paper, dead centre on
the same desk. Not representative of Indian paperwork in three ways that
matter — no non-Latin script, no handwriting in printed fields, no dense
small type.

**The cause was my prompt, not the model.** It dictated the layout
("label-and-value rows in a clean sans-serif face, ruled lines or a light
form grid") and hedged every photographic instruction ("*slight*
perspective", "*mild* uneven lighting", "the whole page is in frame").
Worse, dictating the layout **suppressed what the model already knows**:
it renders the correct UIDAI emblem, wordmark and 1947 helpline unprompted.
The fix was to stop describing a form and describe the artefact — physical
format, language, printed or handwritten — and let it supply the layout.

**Probe: 6 document types × 2 settings, 11 images, ~$0.85.**

| setting | read-back | redacted |
|---|---:|---:|
| `clean` — the original 50 | 100% | **79%** |
| `authentic` — real layout, format, script, handwriting | 100% | **54%** |
| `field` — authentic plus sampled capture and paper wear | 100% | **50%** |

**Document structure is the lever; photography is a rounding error.**
79 → 54 came from layout, language and handwriting. 54 → 50 came from
everything photographic. My instinct had been the reverse.

Read-back held at 100% throughout, which is what makes those numbers
usable: `compare_realism.py` exists to watch exactly this, because a
corpus can be made arbitrarily hard by making it illegible, and an item
the verifier cannot read cannot be scored. The stopping rule is the
hardest setting whose read-back has not begun to fall. We are not there
yet.

**Small n.** 24 and 28 items. The direction is unambiguous at 25 points;
the precise values are not.

### The finding that matters more: the ground truth is structurally incomplete

Realistic documents carry PII **nobody asked for**. Across the 11 probe
images: **52 labelled items, 75 unlabelled ones.**

A real bank statement invents a customer ID, an email, a MICR code, and a
transaction narration reading `NEFT/KKBK24013004567/RENT/RAHUL KUMAR` —
another person's name entirely. A lab report adds the pathologist's name
and their medical registration number, twice, once inside a rubber stamp.
Every ID card adds a signature bearing the holder's name.

This is a flaw in values-first generation that only appears once the
documents stop being sparse: the annotation knows what was *requested*,
and a rich page contains far more than that. Every score in this project
is therefore measured against a subset of the PII actually present —
**79%, 54%, 50%, and the headline 93.5% are all optimistic by an unknown
margin**, and most of what is missing is the hard kind: handwriting,
third-party names, stamps.

Fixing it means the read-back must stop being a checklist and start being
a survey — "what else is on this page?" — with the result reported for a
person to accept or reject, as `annotate_inputs.py` already does, because
what counts as PII is a policy question and not the model's to settle.

**Not regenerating the 50 until that is fixed**, since doing so would only
bake an incomplete ground truth in at scale.

### Where the realism push stops

The `authentic` Aadhaar prompt was **rejected by OpenAI's moderation at
input** — it asked for a card "exactly as issued today" carrying "the
16-digit VID line that a real card carries". That is document fidelity for
its own sake, and the filter was reading it correctly.

The line, kept deliberately: chase **layout and capture** realism, which
is what makes OCR hard; do not chase **security-feature** fidelity —
holograms, microprint, guilloche, exact VID placement — which adds nothing
to OCR difficulty and whose only effect is helping a fake pass as genuine.
The spec will be softened rather than reworded to slip past the filter.

---

## 2026-09-15 — Deleted the self-generated corpora; stopped scoring against our own imagination

**Status:** Active — supersedes *A 50-document photoreal corpus, and 79.0%*
and every figure measured on `pack/`

`datasets/pack/` and `datasets/generated/` are **deleted**. Both were
images this project produced, and both were being used as evidence that
this project's code works.

**The circularity, stated plainly.** The recognizers and the test data had
the same author. `synth.py` and the pack generator invented formats —
`MRN-458361`, `MH/MED/2011/45892`, `REG-2026-28726` — and the recognizers
were regexes fitted to those inventions. They agreed with each other and
disagreed with reality. The scores follow exactly that split:

| data | whose | score |
|---|---|---|
| `documents/` | ours | 93.5% |
| `pack/` | ours | 90% |
| `generated/` | ours | 79.0% |
| IndiaPII-Bench | independent | 76.2% |
| maskara | independent | 75.6% |
| cheques | independent | **0/30 regions fully covered** |

Every number above the line was produced by grading homework against its
own answer key.

**What survives.** `documents/` stays — it is also ours, but it is the
original corpus, its 77 items were audited by an independent vision pass,
and its leaks are documented. Its 93.5% is now stated in `README.md` as a
**ceiling on familiar material, not performance**. `cheques/` and the two
text benchmarks are the only independent evidence this project holds, and
they are what a change must be measured on from here.

**Also removed: seven recognizers** — `IN_PATIENT_ID`, `IN_PNR`,
`IN_POLICY_NUMBER`, `IN_MEDICAL_REG`, `IN_LAND_RECORD`,
`IN_PROPERTY_REGISTRATION`, `IN_BANK_ACCOUNT`. Each encoded an invented
shape for an identifier that has no national format. Four never fired once
across 67 pages, and the misses were the variants nobody had thought of:

    Medical Record No.: MRN-458361   -> nothing  (pattern wanted AB1234567)
    Reg. No.: MMC/2010/06/12345      -> nothing  (pattern wanted MH/MED/2011/45892)
    Reg. No. : 63281                 -> nothing  (no shape at all)
    Customer ID : 100724681          -> nothing  (nobody wrote that one)

**Kept:** `IN_IFSC` — genuinely specified by the RBI, 11 characters with a
mandatory `0` at position five, which is why it can fire without a label.
`IN_DRIVING_LICENCE` — kept on notice: the state/RTO/year/serial
convention is externally attested but no authoritative spec was findable
and sources disagree on whether the RTO code is two characters or three,
so both are now accepted. The bar for any future recognizer: **cite the
published specification**, or treat it as a label problem.

**The replacement is `redactor/labels.py`**, which redacts the value
*beside* a personal-data label using the OCR geometry, whatever shape the
value has. Unit-tested on synthetic geometry only; **not yet validated on
independent data**, and deliberately not validated on the corpora above,
which is what caused this entry.

**Standing rule, now in `CLAUDE.md`:** do not develop or test against a
corpus this project generated.

**Known stale, accepted:** `expected_type` in `datasets/documents/
annotations.json` was nulled for the seven culled types in place rather
than regenerated, because that file's 77 items are the product of three
revisions and an independent audit that `build_ground_truth.py` would
overwrite. Item count and text verified unchanged; scoring is
legibility-based and never read the field.

**Addendum — the generator tooling went too.** `generate_openai_documents.py`,
`compare_realism.py` and `redactor/synth.py` are deleted, along with the
`openai` dependency and the `OPENAI_API_KEY` field. They worked, and the
realism probe they ran produced a genuine finding (document structure is
the lever, not photography). But their only product was a corpus that
cannot count as evidence, and keeping a generator whose output must never
be cited is worse than keeping no generator: the next session would use
it. The probe's findings stay recorded above; the machinery does not.

---

## 2026-09-15 — The label lexicon, measured on independent Indian forms

**Status:** Active — `redactor/labels.py`, `benchmark_labels.py`, `test_labels.py`

The search for independent Indian document *images* came up empty, and
that is worth recording as a result rather than a gap in effort:

| candidate | why not |
|---|---|
| presidio-research | a template+Faker **generator**, ships no corpus. Presidio's own India recognizers therefore have no independent evidence either. |
| IndicDLP (MIT, 121k real Indian pages) | 11 of its 12 domains carry no field-PII, public forms are blank templates, and it is layout boxes with no text |
| FUNSD (199 forms, human label→value links) | non-commercial research licence — and it is the *perfect* shape |
| XFUND | CC BY-NC-SA 4.0 |
| LeakageBench (500 images, 11,954 PII annotations) | Data Use Agreement, GDPR/European, days old |
| nvisycom/synthetic (MIT) | "only text-bearing formats render" — images unimplemented |

The structural reason: documents containing real PII are not published,
and almost nobody builds synthetic replacements. The cheque dataset's own
paper is titled *"Open Annotations and Synthetic Data for Field
Localisation in Indian Bank Cheques"* — released Apache-2.0 because the
field had nothing.

**But the lexicon half was testable all along, and we had the data.** Every
one of IndiaPII-Bench's 2,000 documents is a `Label: Value` form written
by someone else. That is 9,782 PII values sitting after a label.

**First measurement: 43.5% recall.** The misses were not exotic vocabulary,
they were morphology — the lexicon knew "mobile" but not "mobile number",
"account number" but not "bank account number", "driving licence" but not
"driving licence no". Enumerating variants is the same losing game as
enumerating number formats, one level up.

**So matching moved from the phrase to its words**: strong terms decide
outright, weak terms ("name", "address") decide only when no institutional
term is present, filler is stripped. "Bank Account Number" matches, "Bank
Name" does not.

| | recall | precision |
|---|---:|---:|
| exact-phrase | 43.5% | — |
| **token matching** | **100.0%** | **97.2%** |
| control: match every labelled line | 100.0% | 87.6% |

**The control is the honest part.** This corpus is 87.6% PII-dense, so a
rule that matches everything already gets 100% recall. What the token rule
buys is discrimination: **1,103 of the 1,382 non-PII labelled lines are
rejected, with no PII lost.** On maskara, the deliberately OCR-corrupted
domain scores 100% and the rest 94.6%.

**Three bugs found, each by a different kind of evidence:**

- *Independent data* found that `"customer_name"` never matched: underscore
  is a `\w` character, so a JSON-style key survived as one token. 200 misses.
- *A unit test* found that switching to "contains a term" broke
  longest-match — `Customer ID 100724681` matched as a four-word label and
  swallowed the value it was supposed to anchor. Fixed by requiring every
  word of a label to be label vocabulary.
- *The same unit test* found the value-truncation bug **twice**: the
  positional gap limit was applied to every word of a value instead of only
  to where the value starts, so "Anita Iyer" became "Anita" and an address
  became "H.No.". Fixed identically in both branches.

**A fourth was caught by reading output rather than trusting a tool:** a
`str.replace` meant to fix the underscore silently matched nothing, because
the file held a literal Devanagari range where the patch expected a `\u`
escape. The "fix" was applied and changed nothing; only checking the result
revealed it.

**Still untested:** the geometry that pairs label to value on a real page,
Devanagari labels at scale (both text corpora are Latin script), and real
OCR noise on labels rather than maskara's synthetic corruption.
`test_labels.py` pins the geometry on hand-built OCR dicts and says out
loud that this is the weaker kind of evidence.

**Correction to an earlier claim in this file:** the maskara "false
positives" on `Address` labels were not errors. That corpus's `ocr` domain
annotates only `PERSON_NAME` and `AADHAAR`, so the addresses we found are
real PII its ground truth omits. Precision measured against incomplete
truth understates itself.

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

---

## 2026-09-15 — Re-measured after the cull; VALIDATION.md added

**Status:** Active — corrects figures published earlier today

Two benchmark numbers quoted in `README.md` were **stale**: 76.2% and
75.6% were measured with nine custom recognizers, and there are now two.
Re-running both:

| benchmark | before the cull | after |
|---|---:|---:|
| IndiaPII-Bench | 76.2% | **67.2%** |
| maskara | 75.6% | **75.6%** (unchanged — it maps none of the culled entities) |

**The cull cost 9 points on text.** `BANK_ACCOUNT_IN` fell to 0% — 1,142
spans. That is the measured price of removing `IN_BANK_ACCOUNT`.
Label-anchored redaction is the intended replacement, but it works on page
geometry, which a text benchmark cannot exercise, so on text this is a
straight loss and the recovery on images is **untested**. Recorded rather
than defended.

### The driving-licence recognizer is not validated, it is lucky

The earlier question — "are the formats clear for `IN_IFSC` and
`IN_DRIVING_LICENCE`?" — now has an answer from independent data.

- **`IN_IFSC`: 100% on 1,142 examples.** The format is genuinely published
  (RBI, 11 characters, `0` fixed at position five). It earns its place.
- **`IN_DRIVING_LICENCE`: 100% on IndiaPII, 0% on maskara.**

Two independent corpora disagree completely. maskara's licences read
`KL-2009-119628` and `WBBY1990931178` — six-digit serials and four-letter
prefixes, both of which our pattern forbids, because the pattern was built
from an example this project invented (`KA05 20230012345`). It matches
IndiaPII only because that author guessed the same way.

**A recognizer scoring 100% and 0% on two independent corpora has not been
validated; it has been shown to match one opinion.** It is kept for now
only because the label mechanism covers the maskara cases anyway — their
text reads `DL No: TSJB2003555471`, and `DL No` is a label. It should be
treated as a candidate for the same cull as the other seven.

### Other findings worth recording

- **`IN_AADHAAR` scores 0% on masked Aadhaar numbers** (285 examples) —
  the `XXXX XXXX 1234` form that appears on documents which are *already*
  partially redacted.
- **19% of detections match no labelled PII** (3,159 of 16,619), and 76%
  of timestamp-shaped decoys are flagged as something. Over-redaction is
  this project's stated preference, but its cost has never been quantified.
- **Presidio ships no test data at all.** `presidio-research` is a
  template-and-Faker generator; the recognizer tests are hardcoded strings.
  These benchmarks may be the only independent evidence that exists about
  Presidio's India recognizers.

### VALIDATION.md

Added as a fourth standing document: what is measured, on whose data, and
what is not. It exists because the honest summary of this project does not
fit in a headline percentage — the recognizer layer has real independent
evidence at 67–76%, and the image pipeline has almost none, resting on 20
documents this project drew and 10 cheques of a single type.

It carries the gap list, the per-recognizer evidence table, the recurring
failure modes, and one rule learned today: **any new metric must report
its trivial baseline.** The label benchmark's 100% recall looks like a
triumph until the control shows that matching every labelled line scores
the same, because the corpus is 87.6% PII-dense.

---

## 2026-09-15 — Local VLM: the integration works, this machine does not

**Status:** Active — `redactor/vlm.py` shipped and correct; **not viable on
8GB**, and not yet measured for accuracy

Ollama 0.34 installed (it pulls MLX, so it uses Apple's runtime on Apple
Silicon — the one reason LM Studio was under consideration, now moot),
`qwen2.5vl:3b` pulled, served at `:11434/v1`, reached by our client.

**The coordinate bug was real and was caught by drawing the boxes.** The
model ignored a request for fractional coordinates and answered in
absolute pixels: `[72, 172, 558, 192]` on a 900×1100 page. Read as
per-mille — the rule this file recommended a few hours earlier — the box
became x=64–502 where the name ran to 558, **clipping the end of a name
that was supposed to be covered**. A box in the wrong place is a leak that
looks like a redaction, which is the exact failure that killed per-region
coverage earlier.

Fixed at the source rather than by inference: the prompt now states the
image dimensions and asks for absolute pixels, and the fallback inference
now treats a coordinate that *fits inside the image* as pixels, inferring
per-mille only when a coordinate is too large to be a pixel. The residual
ambiguity is pinned in `test_vlm.py` with a comment saying which way it
resolves and why.

**Accuracy, one image, indicative only: 1 of 6 items.** On
`01_aadhaar_card.png` it found the name — a tight, correctly placed box —
and missed the DOB, the Aadhaar number, both address lines and the mobile.

**Throughput, measured: 0.8 tokens/sec sustained, dipping to 0.08**, with
system memory free at 13%. The machine is swapping. The arithmetic is what
settles it, and it contains a perverse incentive:

| reply | tokens | per image | 20 images |
|---|---:|---:|---:|
| 1 item found | ~42 | 0.9 min | 0.3 h |
| 6 items found | ~252 | **5.2 min** | **1.8 h** |
| 12 items found | ~504 | 10.5 min | 3.5 h |

Against the Presidio pipeline's measured **1.75 s/image**. So the better
the recall, the longer the reply, and the slower it gets — the useful case
is the unaffordable one. A prompt variant asking for exhaustive extraction
timed out at 300s for this reason.

**What this does and does not establish.** It does not show that a vision
model is a poor PII detector; a 3B model under memory pressure is not a
fair test of the idea, and the one box it did produce was accurate. It
establishes that **this approach cannot be evaluated on 8GB**, and that
`--vlm` should stay off by default.

**Three ways forward, unranked because the choice is about cost:**

1. **More RAM.** A 7B model on 16–32GB is the fair test of the hypothesis.
2. **A hosted VLM as the backup catch.** `vision.py` already talks to
   Claude, and `compare_runs.py` already prices a second pass in seconds
   per prevented leak. But this project's stated boundary is that the only
   network call is for *scoring*, never redaction — routing detection
   through an API crosses it, and that is a policy decision, not a
   technical one.
3. **Leave it.** The integration is committed, tested and off by default;
   it costs nothing until someone has the hardware.

---

## 2026-09-15 — Label-anchored geometry, measured on real pages at last

**Status:** Active — `ktp_benchmark.py`, `datasets/ktp/` (fetched, not committed)

`redactor/labels.py` has been enabled by default since it was written, on
the strength of OCR dictionaries typed by hand. It now has real evidence.

**The corpus.** 20 synthetic Indonesian national ID cards from
`cloverx-id/indonesian-id-card-dummy` (CC-BY-4.0, publisher-declared dummy
data), carrying **publisher-authored per-field boxes** — the only
circumstance where coverage means anything here. 180 PII regions. A KTP is
structurally an Aadhaar card: national ID number, name, date of birth,
address.

**The isolation that makes it a geometry result.** The lexicon knew
**0 of 6** Indonesian labels, so a score taken straight away would have
measured the OCR path and been read as geometry. Six Indonesian terms were
added first — `nik`, `nama`, `alamat`, `lahir`, `agama`, `darah` — which
are printed on every card, the same "cite the published thing" bar a
recognizer has to clear. `ktp_benchmark.py --diagnose` exists to force
that check before anyone reads a coverage number.

**Result, A/B on the same 20 cards:**

| field | anchoring off | on | gain |
|---|---:|---:|---:|
| address | 16% | **61%** | +45 |
| id_number | 32% | **82%** | +50 |
| name | 21% | **63%** | +42 |
| birth_info | 40% | **75%** | +35 |
| religion | 13% | **60%** | +47 |
| blood_type | 62% | **91%** | +29 |
| **regions fully covered** | **12/180** | **44/180** | **3.7×** |

**The cleanest evidence is the bottom two rows.** `religion` and
`blood_type` have *no recognizer at all* — no regex matches `BUDHA` or
`O`. Nothing but label-anchoring can cover them, and they move 13→60 and
62→91. The mechanism does what it was built to do, on pages nobody here
drew.

**A leak found by looking at the image, not the table.** `RT/RW : 009/014`
was completely unredacted: `rt` and `rw` had been classified as *filler*,
so the label reduced to nothing and never anchored. RT/RW is the
neighbourhood unit of an Indonesian address. Moved to strong terms;
address coverage 55% → 61%, fully covered 41 → 44. The table looked
reasonable before the fix — only the drawn output showed the hole.

**The coverage figures understate, and the reason matters.** The
publishers' boxes are **padded to a fixed column width**, extending well
past the text they contain. A perfectly covered value therefore scores
around 65%. So 44/180 is a floor, not an estimate, and this is one more
reason legibility stays the headline metric while coverage stays a warning
signal. Whether these cards are *readable* after redaction has not been
scored yet.

**What this does not establish:** nothing about Devanagari, handwriting,
or Indian form conventions. It establishes that the label→value geometry
works on real pages, which is exactly the half that was unevidenced.

**Adding the Indonesian terms did not disturb the Indian result** —
`benchmark_labels.py` still reports 100% recall / 97.2% precision on
IndiaPII-Bench, checked before and after.

---

## 2026-09-16 — Eight specified identifiers added; recall 67.2% → 76.6%

**Status:** Active — `redactor/recognizers.py`

Recognizers added only where a **published specification** exists, with the
checksum-carrying ones validated rather than trusted to shape alone.

| entity | specification | independent recall |
|---|---|---|
| `IN_ABHA` | 14 digits, **Luhn-10** — NHA / ABDM | 6% → **100%** |
| `IN_AADHAAR_MASKED` | `XXXX XXXX 1234` — UIDAI masking | 0% → **100%** |
| `IN_ABHA_ADDRESS` | `handle@abdm` / `@sbx` — NHA | 3% → **100%** |
| `IN_UPI_VPA` | `handle@psp`, no dot after `@` — NPCI | 5% → **97% / 100%** |
| `IN_VEHICLE_REGISTRATION` | CMVR 1989 Rule 50, incl. BH series | 31% → **100% / 98%** |
| `IN_AADHAAR_VID` | 16 digits, **Verhoeff** — UIDAI | spec-backed, unmeasured |

**Totals: IndiaPII-Bench 67.2% → 76.6%, maskara 75.6% → 82.7%.** Decoys
flagged as the type they mimic stayed at 4%, and detections matching no
labelled PII fell from 3,160 to 3,026 — so precision improved slightly
rather than being traded away.

**A checksum is what makes a recognizer falsifiable.** That is the
difference between these and the seven removed on 2026-09-15: `1234 5678
9012 37` either passes Luhn or it does not, which is not an opinion about
what a health ID looks like. `ChecksumPatternRecognizer` discards failures;
`_verhoeff_ok` delegates to Presidio's implementation rather than
re-deriving the permutation tables, because a silently wrong table would
make every VID look invalid and the recognizer would simply never fire.

**Declined, with reasons.** UAN and PRAN are 12 bare digits — colliding
with Aadhaar and carrying no checksum. PIN code is six bare digits, and a
postcode identifies an area rather than a person. All three are label
problems, which `redactor/labels.py` already handles.

### The driving licence, kept on explicit terms

No authoritative specification was findable, and two independent corpora
contain incompatible shapes. The pattern now accepts the **union of what
both corpora contain** — `KA05 20230012345`, `KL-2009-119628`,
`WBBY1990931178` — with a year in the middle as the invariant. 0% → 100%
on maskara, still 100% on IndiaPII, and invoice numbers of similar shape
are still rejected.

Fitted to two independent sources is weaker than a specification and
stronger than an invention. The docstring says exactly that.

### Three bugs, each found by checking rather than assuming

- **The masked-Aadhaar pattern could never match `****-****-1234`.** `\b`
  before `*` requires a word boundary, and `*` is not a word character, so
  only the `XXXX` form matched. 91 of 285 spans were invisible. Replaced
  with a lookbehind.
- **ABHA scored 6%, and the cause was the corpus, not the checksum.** My
  Luhn was verified against known card numbers; only 9% of IndiaPII's ABHA
  numbers pass Luhn, which is chance — their generator never applied it.
  Resolved the way Aadhaar already was: strict checksum for confidence,
  plus a context-anchored fallback for failures.
- **`AADHAAR_MASKED` read 0% because the benchmark's mapping was stale**,
  not because detection failed. It accepted only `IN_AADHAAR`. Fixing the
  *measurement* also tightened three entities from "any overlap counts" to
  "the correct type counts", which lowered the apparent score before the
  real fixes raised it.

**And one self-inflicted:** an edit spliced `redactor/recognizers.py`
between two function names whose order had changed earlier in the session,
silently deleting `build_registry`, `build_custom_recognizers` and the
checksum helpers. Caught by an import error immediately; restored from
git. Slicing a file by `.index()` assumes an ordering that a previous edit
may have changed.

---

## 2026-09-16 — Fresh run on both corpora; the cheque metric was misleading

**Status:** Active — supersedes the `0 of 30 regions fully covered` claim

Both corpora re-run and vision-scored with the current stack.

**Documents: 70/72 core = 97.2%.** The two remaining core leaks are a name
and a phone number on one photographed form. The other five leaks are all
`sensitive` tier — diagnoses and medications — and `--medical-ner` takes
those from **0/5 to 5/5**, putting the overall figure at **97.4% (75/77)**.
That flag stays off by default because it pulls in torch, but the cost of
leaving it off is now measured rather than assumed.

**Two label-vocabulary gaps found by the run, not by reading the code:**

- `Doctor Reg. No.` never anchored, because **`reg` was not vocabulary
  while `registration` was** — the same morphology failure that cost 56%
  recall before token matching replaced exact-phrase matching. `doctor`
  was missing too. Both added; IndiaPII precision unchanged at 100% / 97.2%.
- `A/C NO.` normalised to `a c no`: stripping the slash split the standard
  Indian abbreviation for an account into two single letters. `normalise()`
  now rejoins runs of single characters, which also fixes `S/O`, `D/O`,
  `W/O`.

### The cheque claim was wrong, and the metric was the reason

`0 of 30 regions fully covered` has been this project's headline evidence
that the documents figure does not generalise. The account number is in
fact **fully covered** — confirmed by drawing it — while the metric
reported 22%.

The publishers' regions span whole form rows, so they contain the printed
label, the cell border and the bank's watermark as well as the value. A
correct redaction scores about 20% by construction. Ink coverage is no
better: the ink includes the label and watermark.

Measured by legibility instead — `cheque_benchmark.py --legibility`, which
reads both the original and the redacted image so an element that was
never legible cannot be counted as a success:

| element | covered |
|---|---:|
| branch IFSC | 10/10 |
| payee name | 6/10 |
| signature | 6/10 |
| MICR line | 6/10 |
| account number | 4/10 |

Cheques remain the weakest case and handwriting remains the reason, but
the failure was smaller than reported and the error was in the measurement.

**`annotate_leaks.py` overstated too.** It prints items OCR read as leaked
*or* could not confirm redacted, and called the total "still visible".
Unverifiable is not visible: it reported 15 where vision found 7. The
wording now says "to check by eye" and explains the difference.

**Runs kept for inspection:** `runs/documents`, `runs/documents_medner`,
`runs/cheques`, each with `scored/` images where failures are outlined.

---

## 2026-09-16 — Why six of ten cheque account numbers still leak

**Status:** Active — diagnosis, not a fix

Inspection of the drawn output confirms the legibility score exactly:
**4 of 10 account numbers covered, 6 readable.** Axis (3) and one
Syndicate are covered; all three Canara, both ICICI and one Syndicate are
not.

**The label logic is not at fault; OCR is.**

- **Canara** — Tesseract reads *no* account label at all. `खा. सं. / A/c No.`
  sits on a dense blue guilloche background and does not survive OCR. No
  label, no anchor.
- **ICICI** — the number is at (407, 570) and the only `account` label OCR
  finds is at (1283, 665), in the footer prose "…ICICI Bank Limited in
  India". Its value words are `Bank Limited in India`. The real `A/c No.`
  label is never read as a unit.
- **Axis** — reads `A/C` and `NO.` cleanly on a plain background, the
  label resolves, and the value beside it is covered.

So the gap is OCR on cheque security backgrounds, which is the same root
cause as the handwriting failures on these images. A better label lexicon
cannot fix it; a backend that reads patterned backgrounds might.

**Removed again: `so` / `do` / `wo`.** Added hours earlier for s/o, d/o
and w/o on the reasoning that they precede a relative's name. Across 30
images they accounted for 2 of 92 labels found and **both were OCR noise**
— one had `aoe` as its value — while neither corpus contains an actual
s/o field. No measured benefit and an observed cost, so they are out.
Added on plausibility rather than evidence, which is the error this
project keeps having to correct; re-add only alongside a corpus that
contains such fields.

---

## 2026-09-16 — PaddleOCR nearly solves the cheques; it costs 25x

**Status:** Active — measured, not yet a default

The cheque failure has been this project's standing evidence that its
headline does not generalise. Most of it was the OCR backend.

Legibility on the same 10 cheques, same pipeline, backend swapped:

| element | tesseract | paddle |
|---|---:|---:|
| account number | 40% | **100%** |
| payee name | 60% | **90%** |
| signature | 60% | **80%** |
| MICR line | 60% | **100%** |
| branch IFSC | 100% | 100% |

Across the three fields this project counts as personal data:
**16/30 → 27/30.**

**Why.** Tesseract cannot read `A/c No.` on a Canara or ICICI security
background under *any* preprocessing — not RGB, greyscale or CLAHE+Otsu,
and not the R, G, B, HSV-value or desaturated-ink variants tried
afterwards. Paddle reads it directly. With no label there is nothing to
anchor, which is why six of ten account numbers were readable.

**A geometry fix came with it.** Once Paddle supplied the label, ICICI
still failed: the `A/c No.` cell sits 0.69 of its own height above the
value, so the boxes overlapped by 11px where `SAME_ROW_TOLERANCE = 0.6`
demanded 22. Lowered to 0.3 — adjacent rows in a form do not overlap at
all, so a lower bar still separates them. Checked against the independent
KTP corpus: 44 → 45 regions fully covered, no regression.

**The cost is the problem: 131.6 s/image against Tesseract's 5.2 — 25x.**
On 2365x1065 cheques that is 22 minutes for ten images.

**Not made the default.** Tesseract stays, because it is 25x cheaper and
loses nothing on printed forms. `--ocr paddle` is the right choice for
cheques and any document with a patterned or coloured background, and that
is now a measured recommendation rather than a hunch.

**Speed follow-up — where Paddle's time actually goes.**

Measured on a 2365x1100 cheque, OCR step only:

| config | 3 variants | 1 variant |
|---|---:|---:|
| textline orientation on (current) | 127.2s | 49.0s |
| textline orientation off | 133.9s | 57.6s |
| + `text_det_limit_side_len=960` | 120.7s | 48.6s |

**Disabling `use_textline_orientation` does nothing** — 5% slower, i.e.
noise — despite visibly loading a third model (`PP-LCNet_x1_0_textline_ori`)
in the logs. It is the change that looks most obviously right and is not.
`text_det_limit_side_len` buys ~5%.

**The three-variant union is the cost**, and it exists for Tesseract's
benefit: Paddle read `A/c No.` straight off the RGB image where all three
Tesseract variants failed. End to end on the cheques, `--single-variant`
takes Paddle from **131.6 to 75.5 s/image (1.7x)** — less than the 2.6x the
OCR micro-benchmark suggested, because the rest of the pipeline does not
shrink.

**It is not free.** The three counted PII fields are unchanged (account
100%, payee 90%, signature 80%), but **MICR coverage falls 100% -> 60%**.
The MICR line encodes account digits, so covering the A/C box while
leaving MICR readable leaks the same number by another route. For cheques,
keep the union.

**Advice from general PaddleOCR speed guides does not transfer here.**
`enable_mkldnn` is Intel x86 and this machine is arm64; and neither
`enable_mkldnn` nor `cpu_threads` exists in PaddleOCR 3.7's constructor —
both were 2.x arguments, moved behind a `paddlex` engine config in 3.x.

---

## 2026-09-16 — Auto-escalating the OCR backend: viable per corpus, not per image

**Status:** Investigated, not built — the evidence says what it can and
cannot do

Since Paddle nearly solves cheques at 25x the cost, the obvious design is
to detect the hard images and pay only for those. Two candidate signals
were measured.

**Background statistics do not work.** Mean saturation and white-pixel
fraction separate *coloured* from *plain*, not *hard* from *easy*:

| corpus | saturation | near-white |
|---|---:|---:|
| documents | 0.06 | 86% |
| cheques — Axis (Tesseract succeeds) | 0.07 | 85% |
| cheques — Canara (Tesseract fails) | 0.20 | 35% |
| KTP cards (Tesseract adequate) | 0.34 | **0%** |

KTP cards are the most coloured thing here and Tesseract copes; Axis
cheques look statistically like plain documents. A threshold that catches
Canara also catches every KTP card, whose benefit from Paddle is unmeasured.

**OCR confidence separates corpora cleanly and images not at all.**

| corpus | mean confidence | low-confidence tokens |
|---|---:|---:|
| documents | 93-95 | 0% |
| KTP | 72-78 | 17-26% |
| cheques | 44-72 | 28-68% |

A threshold near 85 routes every cheque to Paddle and leaves every document
on Tesseract, which is the intended behaviour. **But within the cheques it
is backwards**: Canara leaks at confidence 64-65 while Axis succeeds at
55-59. Tesseract reads the guilloche pattern as text and is *confidently
wrong* — it never sees the label at all, so nothing in its own output
reports the failure.

**Conclusion.** Escalation can be a document-class decision, not a
per-image one. A useful rule is "mean OCR confidence below ~85 implies a
patterned or photographed source, re-run with Paddle", costing one extra
Tesseract pass (5.2s on a cheque) before the Paddle pass. What it cannot
do is find the hard page inside an otherwise easy batch.

**Restricting entity types saves little, because OCR dominates.** Measured
on the 20-document corpus:

| run | per image |
|---|---:|
| all entities, visual detection on | 1.00s |
| three ID entities only | 0.83s |
| three ID entities, no visual detection | 0.74s |

Naming the entities skips the recognizers that cannot produce them —
spaCy NER included — for **17%**, and dropping the visual detectors adds
another 9%. Worth having, and `--entities` already does it, but it cannot
approach the 25x that the backend choice costs. Time is in OCR, so the
lever that matters is how many OCR passes run, not how many recognizers.

---

## 2026-09-16 — Paddle measured on all three corpora; the escalation case

**Status:** Evidence for `--ocr auto`, not yet built

| corpus | tesseract | paddle | cost |
|---|---|---|---:|
| `documents/` (Indian, 20) | 7 leaks, 1.0 s/img | **+2 caught, −1 lost**, 48.2 s/img | 48x |
| `cheques/` (Indian, 10) | acno 40%, payee 60% | **acno 100%, payee 90%**, 131.6 s/img | 25x |
| `ktp/` (cross-check) | 45/180 covered | **61/180**, 62.8 s/img | 42x |

**On Indian documents Paddle catches exactly the two leaks predicted** —
`Priya Sharma` and a phone number, both on `15_job_application_form`,
which has the lowest OCR confidence of all twenty pages (49.8).

**And it loses one Tesseract found**: `6E3F7K` on the flight booking. That
is the case for unioning rather than switching. A backend swap trades
leaks; escalate-and-union keeps both, net +2 with no regression. The
existing rule — union, never substitute — holds here for a measured
reason, not an aesthetic one.

**Threshold, from Indian data only.** Mean Tesseract word confidence:

| Indian source | confidence |
|---|---:|
| `documents/` 01-10, flat Pillow renders | 91-95 |
| `documents/` 11-20, photoreal | **49.8-76.7** |
| `cheques/` | **44-72** |

A threshold near 85 separates synthetically-clean pages from everything
photographed or patterned. KTP lands at 72-78, consistent, but is a
cross-check and sets nothing.

**Cost of default-on, measured.** On `documents/`, 10 of 20 pages escalate:
+482s to prevent 2 leaks, about **four minutes per prevented leak**. For a
user with 200 photographed forms it is 3 minutes to 2.7 hours. That is the
number to decide against, and it argues for a visible warning and a budget
cap rather than a silent 25x.

**`14_passport.png` needs an explicit rule**: it reads zero words, so its
confidence is `nan`. It is a closed passport cover with no PII, where
escalation buys nothing — but "no words read" is indistinguishable from
total OCR failure, which is the dangerous case. Escalate on `nan`.

**Re-validation on Indian data.** `SAME_ROW_TOLERANCE` 0.6 → 0.3 had been
checked only against the Indonesian KTP corpus, which is exactly what the
rule above forbids. Re-run on `documents/`: **0 marginal catches, 0
regressions**, 70/77 unchanged. The change is safe, but it was validated
in the wrong order and the check is now recorded.

---

## 2026-09-16 — Audited against Tesseract's ImproveQuality guidance

**Status:** Active — three techniques tested and rejected, three untested

Checked the pipeline against
[Tesseract's own quality guidance](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html).

**Already done:** binarisation (the CLAHE+Otsu variant), page-segmentation
tuning (PSM 4, benchmarked against 3/6/11/12), alpha-channel removal
(everything is converted to RGB), and rescaling — though our rule targets a
pixel *width*, not the character height the guidance is actually about.

**Tested and inert — do not re-try without new evidence:**

- **Disabling the dictionaries** (`load_system_dawg=0`, `load_freq_dawg=0`),
  which the guidance recommends for codes and receipts. Byte-identical
  output on every Indian ID card tested. Verified the config mechanism does
  work by whitelisting digits and watching the output change, so this is a
  real negative and not a silently ignored parameter.
- **More upscaling.** Tesseract wants capitals 30-33px; ours measure 9-17px,
  so this looked like the strongest lever. At 3x, raw OCR reads **five more
  exact PII strings (59 -> 64 of 77)** and confidence on photoreal pages
  jumps — `15_job_application_form` 49.8 -> 71.7, `18_bank_statement`
  54.5 -> 87.7. **End to end it changes nothing**: 70 redacted, 7 leaked,
  zero marginal catches, zero regressions. It also costs accuracy on the
  clean Pillow renders, two of which lose a string at 3x.
- **Deskew.** The guidance calls skew severe. Measured across the corpus:
  0 images improved, 1 worsened. Most pages register ~0 degrees because the
  photoreal documents carry *perspective*, not rotation, and a global
  rotation cannot fix that.

**The finding underneath all three: the pipeline's redundancy absorbs
OCR-quality gains.** Three preprocessing variants, label anchoring and the
recognizers already cover what sharper OCR would have found, so improving
OCR quality moves raw text accuracy without moving redaction. That is why
the upscale experiment produced five more strings and not one more
redaction.

Effort is better spent on the **backend**, where the same corpus moved
cheque account numbers 40% -> 100%, than on tuning Tesseract's input.

**Untested:** noise removal, dilation/erosion, border handling. Given the
above, expect them to move raw OCR and not the end metric.

**One thing worth fixing regardless:** `AUTO_UPSCALE_TARGET_WIDTH = 600`
targets image width, when the guidance is about character height. It
happens to give sensible factors here — 2x for the ~300px photoreal crops,
1x for the 900px renders — but for the wrong reason, and it will mislead on
a large scan of small text.

---

## 2026-09-16 — Upscale targets character height; and the scorer has a noise floor

**Status:** Active — `AUTO_UPSCALE_TARGET_TEXT_HEIGHT`, replacing
`AUTO_UPSCALE_TARGET_WIDTH`

**The rule was measuring the wrong thing.** Tesseract's guidance is about
character height; ours targeted a 600px image width, which is a proxy for
nothing. A 2365px cheque with 5px text was left at 1x while a 300px crop of
larger type was doubled.

`estimate_text_height()` now measures the median height of text-shaped
connected components — cheap CV, no probe OCR pass, which would double the
cost of the thing being optimised — and the factor aims for **24px**.

**Result on `documents/`: 7 leaks → 5.** Two marginal catches, a phone
number and a medication, with the one remaining core leak a name.
`documents/` core moves 97.2% → 98.6%. `ktp/` improves 45 → 50 regions
fully covered. And it is *faster*, 1.1 → 0.7 s/image, because several pages
now resolve to a lower factor than the width rule gave them.

**A ceiling was needed, and the cheques found it.** Targeting height alone
sent the 2365px cheques to 3x — a 7095px image — and Tesseract read them
**worse**: MICR coverage 60% → **0%**, account number 40% → 30%, payee 60%
→ 50%. Small text on a large page is a property of a dense document, and
the fix for that is a better backend, not more pixels.
`AUTO_UPSCALE_MAX_LONG_SIDE = 2400` caps the result rather than the factor,
which restores cheque behaviour exactly while keeping the document gain.

### The scorer is not deterministic, and that sets a floor under every figure

Two runs of the same configuration produced 5 leaks and then 6. The
**pipeline is deterministic** — all 20 redacted images byte-identical
across runs — so the variance is in `vision_score.py`.

Measured directly: scoring the same images twice, **1 of 77 verdicts
flipped** — a partially-covered address, genuinely borderline. So the
headline metric carries roughly **±1.3%**, and *a difference of one item
is not a result*. The "1 regression" reported for this change earlier in
the session was that flip, not a real loss.

`compare_runs.py` now says so in its docstring and warns when a comparison
turns on a single item. Every A/B in this file with a margin of one should
be read with that in mind.

---

## 2026-09-16 — `DATE_TIME` off by default, `ORGANIZATION` on

**Status:** Active — changes what a default run redacts

Prompted by a concrete use case: a prescription passing through a
downstream AI, where the patient, doctor, hospital and signature must go
but the conditions, diagnosis and dosage must stay.

**What a default run used to do to a prescription.** `DATE_TIME` matched
`daily` twice, `weekly`, and `8 weeks` twice — the entire dosage schedule —
and block merging spread those boxes onto the drug names beside them. The
patient name was covered correctly and the document was useless to the
reader it was being prepared for.

**`DATE_TIME` is now off by default.** It is the one entity whose instances
split cleanly into personal and not — a date of birth identifies someone, a
dosage schedule or statement period does not — and no entity type can tell
them apart. **Labels can**: `Date of Birth` and `DOB` are personal-data
labels while `Date` and `Visit Date` are not, which recovers **6 of 7 DOBs**
on the documents corpus. `--dates` restores it.

**`ORGANIZATION` is now on.** It was never a decision here: Presidio's
`NerModelConfiguration` lists `ORGANIZATION` in `labels_to_ignore`, so
spaCy tagged `Sundaram Medical Centre` as `ORG` correctly, Presidio mapped
`ORG -> ORGANIZATION`, and then threw it away. Re-enabled by constructing
the NLP engine with that label removed from the ignore list.

**Measured on `documents/`:**

| | core PII | prescription |
|---|---:|---|
| before | 97.2% (70/72) | dosage schedule destroyed |
| after | **95.8%** (69/72) | **dosage schedule intact, hospital name covered** |

The two changes very nearly cancel: dropping `DATE_TIME` alone cost 3
items, and enabling `ORGANIZATION` recovered all 3 — verified as a clean
A/B, +3 catches and 0 regressions. The net 1-item difference is on
`11_aadhaar_card.png`, where OCR reads the number out of order
(`9876 ... 4587 6321`) so the 4-4-4 pattern never forms; `DATE_TIME` had
been covering those stray digit groups by accident. That is an OCR failure
the entity change merely stopped masking.

**Known limit, unfixed.** spaCy tags some drug names as `PERSON` —
`Atorvastatin` and `Vitamin D3 60K` are still redacted on the prescription.
That is the same recognizer that covers the patient, so no entity setting
separates them. `--no-merge-blocks` tightens the boxes and stops the spill
onto neighbouring words, at no measured cost on this corpus.

---

## 2026-09-16 — Clinical content protected by a model, not by rules

**Status:** Active — new flag `--protect-clinical`, off by default

Closes the known limit recorded in the entry above: spaCy tags
`Atorvastatin` as `LOCATION` in one preprocessing variant and as
`ORGANIZATION` in another, both at 0.85, so a default run blacks out the
drug names on a prescription. It is the same recognizer that covers the
patient, so no entity setting separates them.

**Options considered:**

1. *Leave it.* The dosage schedule survives; the drug names do not. A
   prescription is still unusable to the reader it is prepared for.
2. *A dose-adjacency rule* — a word followed by a quantity and a unit is a
   medication. Tried on paper; **rejected**. It works on this prescription
   and fails on a lab report, a discharge summary or a vaccination card,
   and it misses `Vitamin D3 60K`, which carries no `mg`. It is also
   exactly the mistake the seven culled recognizers made: a shape fitted
   to the document in front of us. The user rejected it in the same terms
   — "we are adding too many rules in option 2 and this wont work for
   other images of forms".
3. *A clinical model.* **Chosen.** Presidio's `MedicalNERRecognizer`
   carries real clinical vocabulary: it tags `Metformin`, `Atorvastatin`
   and `Vitamin D3 60K` as `MEDICAL_MEDICATION`, the schedules as
   `DOSAGE`, `Type 2 Diabetes Mellitus` as a disorder, and claims neither
   `Priya Sharma` nor `R. Venkat`.

**The mechanism withdraws boxes; it never adds them.** A `PERSON`,
`LOCATION`, `ORGANIZATION` or `NRP` box is dropped when at least half of
it lies on protected clinical text. Those four types are the whole
suppressible set, so **no identifier can be withdrawn** — a
checksum-validated Aadhaar, an IFSC or a label-anchored account number
inside a clinical sentence is still covered. `NONBIOLOGICAL_LOCATION` is
deliberately outside the protected set, which is what keeps
`Sundaram Medical Centre` redacted; medical *history* labels are excluded
for the same reason, since a history can name a person or a place.

**The 0.5 score threshold is the part that needed measuring.** Without it
the model tagged `PAN`, `Aadhaar`, `Passport`, `Blood Group` and
`Health Insurance` as `DIAGNOSTIC_PROCEDURE` — form vocabulary on
documents with no clinical content — all between 0.31 and 0.38, while
every genuine clinical span scored 0.48 or better and the real vocabulary
(`Metformin`, `Hemoglobin`, `TSH`, the dosages) scored 0.58 to 0.99. One
threshold separates them, which is the practical argument for a scored
model over a list of per-document rules. It cut withdrawals from 19 to 12
and every one it removed was a false positive.

**Measured on `documents/`, defaults vs `--protect-clinical`:**

| | result |
|---|---|
| boxes withdrawn | 12, across 3 of 20 images (10 on the prescription) |
| images byte-identical | 17 of 20 |
| verdicts changed | 2 — `Atorvastatin 10 mg` and `Vitamin D3 60K` |
| identifiers affected | **none** |
| cost | +9s over a 13s run, after caching the model |

Both changed verdicts are items the corpus annotates as PII and this flag
exists to leave readable, so `compare_runs.py` reports them as
regressions. That is the metric working correctly on a flag whose purpose
it does not know about, not a fault.

`compare_runs.py` also reported one *marginal catch* — an address on
`15_job_application_form.png`. Withdrawing boxes cannot cover anything, so
that is scorer noise on a partially-covered value, and it is recorded here
as noise rather than quoted as a catch.

**Performance bug found and fixed in the same change.** The first
implementation built `MedicalNERRecognizer` inside the per-image call,
loading a transformer from disk 20 times: 69s against a 13s baseline.
Cached at module level and moved into the existing thread pool, the same
work costs 9s.

**Also corrected here:** the scorer's noise floor, re-measured. Scoring
one run's images twice produced **0 of 77 verdicts flipped**, against the
1 of 77 recorded on an earlier pair. Both samples stand; the band is
0-1 items, and a single-item difference remains unresolved until it
reproduces.

**And:** `documents/` images 11-20 carried `"source": "real"` in the
annotations, a leftover from believing they were photographs. They are
OpenAI image-model generations that *imitate* photographed pages. The
field now reads `photographic`, which describes appearance rather than
asserting provenance; `_meta` had been correct all along.

**Headline restated for the current defaults:** 94.4% core (68/72), 90.9%
overall (70/77). The 97.2% quoted before this week's default changes was
measured with `DATE_TIME` on and `ORGANIZATION` off and is not comparable.

---

## 2026-09-16 — Correction: an Aadhaar number was leaked for two commits, and the cause was mine

**Status:** Active — fixes `reading_order.py`; supersedes the diagnosis in
the `DATE_TIME` entry above

`11_aadhaar_card.png` was exposing `6321 9876` — 8 of its 12 digits — and
its date of birth, on the default configuration. Bisected by re-running
that one image at each commit:

| commit | upscale | entities found | number |
|---|---:|---|---|
| `040f685` … `3193d84` | 2x | `IN_AADHAAR`, DATE_TIME, PERSON | covered |
| `eda4de0` upscale by character height | **3x** | **no `IN_AADHAAR`** | covered by accident |
| `273f57c` `DATE_TIME` off | 3x | no `IN_AADHAAR` | **leaked** |

**Root cause, and it is not what the previous entry said.** That entry
blamed "OCR reads the number out of order" and called it "an OCR failure
the entity change merely stopped masking". The reading order was wrong,
but it was wrong *because of a bug in `reading_order.py`*, and `eda4de0`
introduced it two commits earlier by raising this card's upscale factor
from 2 to 3.

Words were assigned to the **first** row whose vertical band they fell
into, in row-creation order, with the band taken from whichever word
seeded the row. On this tilted card Tesseract emits a garbage token just
above the number — `ae` (height 104) at 2x, `OVS` (height 43) at 3x. At
2x the tall token's band swallowed all three digit groups, so the line
came out intact by luck. At 3x the shorter token's band reached far enough
to capture `9876` alone, stranding `4587 6321` in the row below:

```
2x  row seed 'ae'  h=104 tol=62.4 -> ['4587', '6321', '9876', 'ae']
3x  row seed 'OVS' h=43  tol=25.8 -> ['9876', 'OVS'] + ['4587', '6321']
```

Flattened that reads `9876 OVS 4587 6321`, the 4-4-4 grouping never forms,
and `IN_AADHAAR` does not fire at all. The number stayed covered only
because `DATE_TIME` boxes happened to land on the digit groups; removing
`DATE_TIME` removed the accident.

**Fix:** a word joins the row whose centre is **nearest** among those
within tolerance, the band is measured against the row's **running mean**
centre and height rather than its seed word, and rows are emitted ordered
by that centre rather than by creation order. A single high, short token
can no longer set the band for a whole line.

**Measured, `documents/` (vision-scored, before -> after):**

| | before | after |
|---|---|---|
| core | 68/72 (94.4%) | **69/72 (95.8%)** |
| overall | 70/77 (90.9%) | 70/77 (90.9%) |
| `4587 6321 9876` | leaked | **redacted** |
| `Atorvastatin 10 mg` | redacted | leaked |

The one item traded away is clinical content on a prescription, which is
what `--protect-clinical` exists to keep readable anyway. Trading a
covered drug name for a covered Aadhaar is the right direction for a
default.

**Measured, `datasets/cheques/` (legibility, same code A/B):**

| element | before | after |
|---|---:|---:|
| payee name | 90% | 80% |
| account number | 70% | 70% |
| signature | 80% | 90% |
| IFSC | 100% | 100% |
| MICR | 70% | **40%** |

Ten images, so one image is 10 points and the PII fields are a wash. MICR
is the one real movement and is **not** counted as personal data here
(like IFSC, it identifies an account route rather than a person), but it
is recorded rather than passed over.

**Cross-check, `datasets/ktp/`:** 46/180 regions fully covered, against
44/180 documented. No regression.

**Still leaking on that card: the date of birth.** Label anchoring cannot
reach it, because Tesseract reads the label `DOB:` as `pos:` on this
low-contrast tilted card — there is no label left to anchor to. Adding
`pos` to the lexicon would be an overfit to one image of exactly the kind
this project has removed before, and `pos` is a real word. `--dates`
covers it; that remains the trade recorded in the `DATE_TIME` entry.

**Headline corrected, twice in one day.** 94.4% core was published this
morning after the defaults change and is superseded by **95.8% (69/72)**,
90.9% overall (70/77). The 97.2% before that was measured with
`DATE_TIME` on and `ORGANIZATION` off and is not comparable to either.

---

## 2026-09-17 — Every published number re-measured; nine were wrong, and one benchmark had been broken since the corpus move

**Status:** Active — corrects figures in `README.md`, `VALIDATION.md` and
`SOURCES.md`, and supersedes the clinical measurement in the
`--protect-clinical` entry above

Prompted by an audit that `check_docs.py` cannot do: it enforces tense and
that every reference resolves, which is why it passed while nine published
figures had drifted from what the code does. Every measurement the docs
quote was re-run on `87c72d8`.

**The pipeline had not moved.** The 20 `documents/` outputs are
byte-identical to the run behind the published headline, so nothing below
is a code regression; it is the record catching up with the code, plus one
script that had stopped working.

### What was wrong

| claim | published | measured |
|---|---|---|
| KTP regions covered, anchoring off → on | 12/180 → 44/180 | **21/180 → 46/180** |
| KTP per field, on | id 82%, name 63%, address 61%, religion 60% | **92% / 76% / 60% / 77%** |
| `--medical-ner` on the sensitive tier | 2/5 → 5/5 | **1/5 → 4/5** (corpus 96.1%, 74/77) |
| cheque region coverage | sign 58%, payee 46%, acno 20% | **75% / 71% / 39%** |
| union vs one variant | 71/77 against 67 | 71/77 against **65** |
| `--ocr paddle` on `documents/` | 7 leaks, 2 caught, 1 lost, 48× | **5 leaks, 1 caught, 2 lost, 68×** |
| signature detector | 13/20 on cheques | **7 of 10** on the committed corpus |
| maskara `ocr` domain | 93%, the highest of any domain | 93%, **second to `transport` at 97%** |
| clinical withdrawals | 12 boxes on 3 images (entry above) | **5 boxes on 2 images**, +13 s |

`VALIDATION.md` carried its own copies of several of these and is brought
current with them, along with three figures it alone held: over-redaction
on IndiaPII (19% of detections matching no labelled PII, 3,159 of 16,619 →
**17%, 3,026 of 18,164**), timestamp-shaped decoys flagged as something
(76% → **67%**), and the cheque legibility counts (payee 6/10 → **8/10**,
signature 6/10 → **9/10**, account 4/10 → **7/10**, MICR 6/10 → **4/10**).
Its `ktp/` paddle cross-check, 61/180, is the one figure left standing from
an earlier commit; it is labelled as not re-run rather than restated.

Confirmed unchanged: the headline (95.8% core, 90.9% overall), the cheque
legibility percentages, IndiaPII-Bench at 76.6% with 4% of decoys flagged,
the label lexicon at 100% recall / 97.2% precision, maskara at 82.7%, and
every entry in the per-recognizer table.

### The clinical figure, and why this project keeps making this mistake

The entry above measured 12 boxes across 3 images at `ae5b729`. The
reading-order fix in `87c72d8` changed it to **5 across 2**, because the
regrouped rows leave fewer `PERSON`/`LOCATION` boxes sitting on clinical
text in the first place. README and VALIDATION were updated in that commit;
neither the commit message nor an entry here recorded the new measurement,
so the decision log kept asserting 12 while the code produced 5. A number
changed in the docs with no entry is a number with no evidence behind it —
next time, the entry goes in the same commit as the figure.

### `benchmark_ocr.py` has been broken since the corpora moved

It invoked `evaluate_redactor.py` with no `--input`, so it fell back to the
pre-migration default `input_images/`, which no longer exists. Every one of
its seven configurations failed, and it reported this as an empty error
string and an empty results table — the exact failure mode the
"never abort the batch" convention exists to prevent, inverted: it aborted
every config and still printed a table. It now takes `--input`, defaulting
to `datasets/documents/images`, and prints the exit code with whichever of
stderr or stdout is non-empty.

**A second break sat behind the first.** With the configurations running
again, the table assembly raised `KeyError: 'recall_on_legible_pct'` —
`score_run.py` reports `recall_floor_pct` / `recall_ceiling_pct` over an
`unverifiable` bucket now, and the benchmark still asked for the single
collapsed recall over a `not_legible` one. So the script had two
independent faults, and the first one hid the second: every configuration
failed early enough that the table was never reached. It now prints the
floor-ceiling range and the unverifiable count.

The backend table in the README is restated from this run, and now carries
what it was missing: these seven configurations are **OCR-scored**, because
seven configurations would otherwise be seven vision passes. Nine of the 77
items are unverifiable in every row, which is why each recall is a range.
The four middle rows sit one item apart — inside the noise. Paddle buys
about a point of floor for 50× the wall clock.

### Paddle now fails outright on two documents

`PaddleX 3.7` raises `TypeError: '>=' not supported between instances of
'list' and 'float'` inside `paddlex/inference/pipelines/ocr/pipeline.py`.
It is **deterministic on `11_aadhaar_card.png`** — both paddle runs today
lost it — and **intermittent on `20_flight_booking.png`**, which failed in
one run of the two. The per-image catch did its job: each batch finished
and named what it dropped. But a dropped page gets no output at all, which
is the worst way to lose one, and an intermittent version of that is worse
still. The documents comparison is therefore scored on the 17 pages both
backends produced. On those, Paddle covers one name Tesseract leaks and
loses two items Tesseract covers, at 892 s extra. **On `documents/`,
`--ocr paddle` is no longer a net gain.** On cheques it still is: account
70% → 100%, payee 80% → 100%, MICR 40% → 80%, at 31×.

### The scorer's noise floor, now characterised rather than bounded

Earlier entries recorded 1 of 77 and then 0 of 77 verdicts flipping on a
re-score, and left a single-item difference "unresolved until it
reproduces". It has now reproduced, repeatedly, and it is not random:

- `15_job_application_form.png`'s address has been scored `leaked`,
  `redacted`, `leaked` across three scorings of the **same** image.
- On the Paddle output, `01_aadhaar_card.png`'s name has been scored each
  way twice across four scorings.

Both are values a box covers *partly*, where legibility is a genuine
judgement rather than a model error. The band is **0–1 of 77**, it lands
on partial coverage, and the headline is published as the floor: 69/72,
not the 70/72 that the same images also score. A single-item difference
between two runs remains noise until it reproduces.

**Method note:** `vision_score.py` overwrites `vision_verdicts.json` with
whatever it scored this pass, so an API error mid-run silently produces a
*shorter* verdict file rather than a partial one. Two runs here came back
with images missing and had to be re-scored. Worth a merge-on-write, or at
least a warning when the file shrinks.

**Headline unchanged:** 95.8% core (69/72), 90.9% overall (70/77).

---

## 2026-09-18 — A held-out corpus, and a guard because a comment would not have held

`datasets/holdout/` is new: 11 synthetic Indian pages, 71 PII items, 9 of
them sensitive-tier, generated with an OpenAI image model and contributed by
the repository owner with one condition — **it may never be used to tune any
OCR system**, stated as absolute and permanent.

### Why a corpus that is not independent evidence still earns its place

It does not clear the bar `SOURCES.md` sets for evidence. The repository
owner generated it, which puts it exactly where `datasets/documents/` sits:
a ceiling on familiar material. Holding it out does not move it across that
line, and this entry is not claiming otherwise.

What it buys is narrower and was missing. Every self-produced figure here so
far was measured on images that existed while the recognizers were being
written — `documents/` most of all, which is why its 95.8% is published as a
ceiling. `holdout/` will produce **a number nothing was fitted to**. That is
weaker than independence and stronger than anything else in the
self-produced half of the table.

It also reaches three cases no image corpus here has had:

- a **Devanagari** name (`नेहा शर्मा`) on an Aadhaar card. The label lexicon
  has carried Devanagari terms with no image exercising them; `SOURCES.md`
  lists MIDV-500 as a candidate for exactly this and it is still unfetched.
- a **second checksum-invalid Aadhaar** — `4123 5687 9012`, Verhoeff
  verified failing. `IN_AADHAAR` discards checksum failures rather than
  down-scoring them, so only the OCR-tolerant fallback can cover it. Until
  now that path had one canary, `documents/04_hospital_admission_report.png`.
- **two different people on one page** (a shipping label with a sender and a
  recipient), which any single-subject assumption gets wrong.

### The guard, and why it is code rather than a note

The rule is enforced, not documented and hoped for. `_meta` carries
`held_out: true`; `redactor.datasets.refuse_if_tuning()` raises
`HeldOutCorpusError` for the corpus name or any path inside it;
`benchmark_ocr.py` calls it before the first configuration runs and exits 2;
`test_holdout_guard.py` pins both directions.

The line drawn is **scoring versus choosing**. One run of an
already-chosen configuration is the corpus's entire purpose and stays
allowed — `evaluate_redactor.py --input datasets/holdout/images` works. A
sweep that picks a backend or a parameter from these images is refused.

A comment would not have held, because this failure is invisible. Sweep
seven OCR configurations over a held-out corpus and the number that comes
out looks exactly like the measurement it was before: same images, same
annotations, same scorer. Nothing in a diff shows that a test set became a
training set. Compare the two Paddle landmines, which *raised* detection
counts while *lowering* redaction — they were caught only because someone
scored leakage instead of counts. This one has no equivalent tell.

### Evidence that the guard works: it was broken on purpose, and it bit

`test_holdout_guard.py` was verified to fail when the protection is removed,
the way `test_metadata_stripping.py` was. With the flag on, 23 checks pass.
Setting `_meta.held_out` to `false` produces 10 failures and exit 1;
restoring it returns all 23.

That verification produced an unplanned demonstration. With the flag off,
`benchmark_ocr.py` did precisely what it is built to do: it began redacting
the held-out corpus under six Tesseract configurations and had to be killed,
leaving **five run folders full of holdout output under `bench_` names**.
Nothing was read from them and `runs/benchmark.json` was never rewritten —
the sweep did not finish — and all five directories were deleted. But that
is how the contamination would arrive in practice: not as a decision anybody
made, as a default `--input` nobody changed.

The test now bounds its own failure with a 30-second timeout and reports a
timeout as "it started the sweep instead of refusing". **A test whose
failure mode is a twenty-minute sweep over the corpus it exists to protect
is not a safe test.**

### Annotations: text, no boxes, and human-owned

71 items carrying `text` and no `box`. Boxes for these images could only
come from a vision pass, and per-region coverage from vision boxes was
built, measured and removed here because those boxes sit about a text row
off. Text-only matches `documents/`.

The draft is Claude's and is marked
`labelled_by: "claude-draft-pending-human-audit"`. What counts as PII is a
policy question for a person, which is why `annotate_inputs.py` reports
rather than rewrites, and the same reasoning applies to a corpus this
project did not previously have.

Three judgement calls in the draft are flagged for that audit rather than
settled quietly:

- **`S020 4433 7788`** (account number, `03_bank_account_statement.png`).
  The leading glyph is the letter `S`, not a `5` — verified at 8×. Recorded
  verbatim, because ground truth records what is on the page.
- **`NR8K0001234`** (IFSC, same page) is **malformed**: RBI requires four
  alphabetic characters at positions 1–4 and this has an `8` at position 3.
  `IN_IFSC` therefore cannot fire, by specification. A miss here is the
  image's fault, and `IN_IFSC` must not be widened to catch it — that
  recognizer is one of the few that clears the cited-specification bar.
- **`UPI/9876543210`** in a transaction narration is a bare 10-digit number
  shaped exactly like an Indian mobile. Genuinely ambiguous. Annotated as an
  item, because over-redaction is this project's stated preference, but it
  is a person's call.

`Medical Conditions: None` on the ID card is deliberately **not** annotated:
the value is the word "None", so there is nothing to conceal and a
legibility verdict on it would mean nothing.

### No number is published in this entry

The corpus is registered and scored nothing. `VALIDATION.md` records it as
*registered, not yet scored*. The headline stays **95.8% core (69/72),
90.9% overall (70/77)** on `documents/`, unchanged by this entry.

---

## 2026-09-18 — Signature geometry measured against the cue word, not the page

`detect.py` sized its signature search window as fractions of the whole
image — `int(width * 0.14)`, `int(height * 0.28)`, `int(height * 0.04)` —
and its minimum-ink filter as fractions of the crop. Both are constants that
describe the sheet rather than the document printed on it. They are now
multiples of the **cue word's own height**: `SIGNATURE_PAD_X_RATIO = 14.0`,
`SIGNATURE_LOOK_UP_RATIO = 12.5`, `SIGNATURE_LOOK_DOWN_RATIO = 2.0`,
`SIGNATURE_MIN_INK_WIDTH_RATIO = 3.4`, `SIGNATURE_MIN_INK_HEIGHT_RATIO = 1.25`.

### Why the old form never showed up in any score

Every cheque in the corpus has the same aspect and the same body text size,
so the two formulations agree to within a few percent there: across the cue
words found on the ten cheques the page-relative window works out at
13.2–14.4, 12.2–13.4 and 1.7–1.9 times the cue word's height. The ratios
above are that same window. A corpus of one shape cannot distinguish a
constant that measures the text from one that measures the page.

What separates them is padding the same page onto a different canvas — a
photograph of a cheque on A4, or on a phone screen. There the page-relative
window stops being a band above the label and sweeps most of the document,
so the largest sprawling blob in it is some other field's ink: of six
detected signatures, two are lost outright and two move onto unrelated ink,
which leaves the signature legible *and* blacks out something else.
`test_geometry_invariance.py` finds this with no new corpus — the same page
with more margin is a different problem to a constant that measures the page.

### Verification: the cheque score does not move

Required before calling this a refactor rather than a rewrite.

| measure | published | after |
|---|---|---|
| signature coverage | 75% | **75%** |
| payee name coverage | 71% | **71%** |
| account number coverage | 39% | **39%** |
| signatures detected | 7 of 10 | **7 of 10** |

Identical on every field. `runs/verify-cheques`.

### The residual, which is Otsu and not geometry

One case does not hold, and it is worth stating precisely because it looks
like a geometry failure and is not. `canara_syn_0009.jpg` padded to
landscape 3:1 loses its one signature region. The *wanted* window is
747×387 before and after — the ratios are doing their job. What changes is
clipping: unpadded, the window runs 29px off the right edge and is cut to
718 wide; padded, it fits. Those 29 columns of white shift the Otsu
threshold over that crop from **140 to 210**, and the region is lost.

Back-filling the clipped window was tried and rejected: filling with white
or by replication puts invented pixels into a histogram computed over
exactly that region, and it changed what was found on *unpadded* pages —
three signatures on this corpus. A clipped window is less input, which is
honest.

So `test_geometry_invariance.py` **reports** clipped-window divergences
rather than asserting on them, and only on the axis the padding actually
grows — vertical padding cannot un-clip a right-hand edge, which is why the
same image passes at portrait 1:2 and diverges at landscape 3:1.

**The exemption is wider than one image and the test now says so.** On the
cheque corpus the cue word sits near the right margin, so 5 of the 6
signature-bearing cheques already run their window off the right edge.
Horizontal padding is therefore weak evidence here; the crop and
vertical-padding cases carry the claim. The test prints that coverage with
every run, because an exemption nobody can see is an exemption that grows.

**Count to watch:** 1 reported case of 26 checks. A rising number means the
detector is getting more sensitive to how much margin a scan happens to
have, not less.

### A hazard found while verifying this

`cheque_benchmark.py` with no arguments **re-fetches and rewrites**
`datasets/cheques/` — it replaced the committed 10-image subset with a
different one (adding `axis_syn_0061`, `canara_syn_0082`,
`syndicate_syn_0036`, `syndicate_syn_0037`) and rewrote `annotations.json`,
122 insertions and 167 deletions. The tracked images survived and
`git checkout` restored the annotations, but the corpus is committed
precisely so that published figures reproduce from a clone, and a bare run
of the benchmark script silently invalidates that. **To score cheques, use
`--score`:** `python cheque_benchmark.py --score runs/<name>`. The bare form
is the fetch-and-rebuild path, not the scoring path.

---

## 2026-09-18 — `holdout/` scored once: 78.9%, and what the 12-point gap means

First and only score of `datasets/holdout/`, vision-scored, defaults, no
flags, `runs/holdout`. **56 of 71 redacted — 78.9%.** Core 53/62 (85.5%),
sensitive 3/9 (33.3%). `vision_score.py` and `score_run.py` differ by one
item (57/14 against 56/15), the same 0–1 noise band `documents/` shows, so
the floor is published.

Against `documents/`' 90.9% overall, this is **12 points lower on the same
project's own images.** That is the corpus doing its job rather than a
regression: the recognizers were written while looking at `documents/` and
have never seen these pages. The honest reading is that roughly 12 points of
the `documents/` figure is familiarity, which is why `VALIDATION.md` has
always called it a ceiling. This is the first number here that quantifies it.

### The largest block of failure is not a pattern gap

Nine of the fifteen leaks carry `expected_type: null` — no recognizer exists
or should: `S020 4433 7788`, `GPU1234567`, `BMT2024-091`, `UK24-77890`,
`SSP123456789IN`, and similar. This is the September 2026 decision playing
out exactly as predicted: seven invented-shape recognizers were removed on
the grounds that anything without a cited specification is a label problem,
and here 60% of the leakage is precisely that. It is evidence for
`labels.py` and against ever restoring those patterns.

### The Aadhaar fallback held on an image it had never seen

`4123 5687 9012` fails Verhoeff — verified — so `IN_AADHAAR` discards it and
only the OCR-tolerant fallback can reach it. **It was covered:** IN_AADHAAR
scores 1 redacted, 0 leaked. The fallback now has a second regression canary
that is not `documents/04_hospital_admission_report.png`, on a photorealistic
card rather than a Pillow render.

### "English only" is now measured rather than asserted

The Devanagari name `नेहा शर्मा` leaked. The README has listed Devanagari and
Kannada as never detected; until now no image corpus here contained any, so
the limitation was stated on reasoning alone. It is now a measurement, and
the two names on that card — one Devanagari, one Latin, same person — make
the comparison direct: the Latin form was covered and the Devanagari was not.

### Two hazards found while producing this score

**`vision_score.py` and `score_run.py` silently scored the wrong corpus.**
Both read `REDACTOR_CORPUS` and default to `documents`. The holdout run was
first scored without it, and because `holdout/01_aadhaar_card.png` collided
exactly with `documents/01_aadhaar_card.png`, one page matched: the output
read `4 redacted, 1 leaked` and named `Rajesh Kumar Sharma`, who is on the
*documents* card. A whole-corpus verdict shape, carrying one page's numbers,
graded against a different document's ground truth, with nothing in the
output saying so. The item-count check in `CLAUDE.md` is what caught it.

Fixed twice over. Holdout filenames now carry an `h` prefix so no corpus's
filenames collide. And `redactor.datasets.check_run_matches()` refuses to
score a run when fewer than half its images appear in the chosen corpus,
naming the corpus that does match:

    score_run.py: this run's images are not corpus 'documents'.
      0 of 11 image(s) in runs/holdout/images appear in 'documents''s ground truth.
      Those images look like corpus 'holdout'. Re-run with REDACTOR_CORPUS=holdout ...

Both scorers exit 2 on it. This is the "don't ship a metric that lies" rule
applied to the scorer itself.

**Duplicate values share one verdict.** `vision_score.py` dedupes by text
within a page, so a signature annotated with the same text as the printed
name — `Arjun Mehta`, `Kavya Reddy` — is asked about once and both items
inherit the answer. Per-page counts are of unique values (69) while the
totals are of items (71). Not wrong, but a signature is a different object
from a printed name and a verdict on one is weak evidence about the other.
Worth separating if signature coverage is ever measured directly.

### Not tuned, and that is the whole point

No parameter was chosen from any of this. The sensitive tier at 3/9 would go
up with `--medical-ner`; the nine label-shaped leaks would move with changes
to `labels.py`. **Neither may be decided from these images.** If a change is
made, the evidence comes from `cheques/`, IndiaPII-Bench or maskara, and this
corpus gets re-scored afterwards to see what happened — once.

---

## 2026-09-18 — A report on every run, and a committed trend behind it

`score_run.py` now writes a self-contained `runs/<name>/report.html` and
opens it, and appends one line to `benchmarks/history.jsonl`. `--no-open`
writes without launching a browser. The renderer lives in
`redactor/report.py`, since the top-level files here are thin CLIs.

The history is **committed**, for the same reason `documents/` and
`cheques/` are: a trend that only exists in a gitignored `runs/` folder
disappears on the next clean, and this project has already lost the working
notes behind published figures that way. Each line carries the recall, the
totals by tier, the config keys that change behaviour, and the **git SHA
with a dirty-tree flag** — a performance history that cannot say which code
produced a number is how a headline gets corrected six times.

### Held-out corpora are recorded, not excluded — and the choice was close

The first design left `holdout/` out of the history entirely, on the
grounds that a trend line is a target. That was rejected after thinking
about which failure it actually prevents.

Excluding it prevents nobody from scoring the corpus; it only prevents the
scoring from being **visible**. A corpus with no record invites being run
quietly, and an unrecorded score is precisely the one that cannot be
audited afterwards. Recording every scoring puts the pressure where it can
do some good.

So `holdout/` is tracked and marked at every point a reader could look:
`held_out: true` in the data, a banner on the report, its trend drawn in the
**warning colour** rather than the accent, and two counts — how many times
the corpus has been scored in total, and whether **this commit has scored it
before**. Re-scoring one commit is called out by name, because that is the
shape of chasing a result until it reads the way you wanted.

**None of this is a guard and it should not be mistaken for one.**
`refuse_if_tuning()` stops a sweep. Nothing can stop a person reading a
trend and keeping the changes that move it up — that is hill-climbing on the
test set at human speed, and the only defence available is that it happens
in the open with a counter attached. **The count is the thing to watch.** A
rising one means the corpus has become a target, whatever anyone intended.

`test_holdout_guard.py` pins the marking rather than the numbers: the flag
in the recorded entry, the banner text, the warning colour on the trend, the
repeat-commit warning, and that a corpus which is *not* held out gets none
of it. Tests use a temporary history file, so running them never writes to
the committed one.

**Current count: `holdout/` scored once, at `4b44f75`, 78.9%.**

---

## 2026-09-18 — The run report leads with failures, and shows the page

The first version of `runs/<name>/report.html` was a headline, two tables
and a trend. It was reviewed and the verdict was fair: a number and a
breakdown do not tell you what went wrong, and the corpus you can act on is
the one you can see. It now leads with **every item still legible, each
beside the page it is on**, with filters for the sensitive tier and for
identifiers no recognizer covers.

Images are read from the run folder by **relative path** — `scored/<name>`
where `annotate_leaks.py` has drawn the failures, `images/<name>` otherwise.
That keeps the page self-contained and offline: it moves with the run, and
copying a run folder copies a working report. It is also why this stayed a
local file rather than becoming a published page, which cannot reference
anything on disk.

### Two annotation shapes, one report

`documents/` and `holdout/` carry ground-truth text, so
`vision_verdicts.json` gives a verdict per *value* and a failure can name
what leaked. `cheques/` carries boxes and no text, so legibility is asked per
*element* and a failure names `micr` or `payee_name` rather than a value.
`report.failures()` reads whichever exists and returns the same shape, so the
renderer does not branch.

### `cheque_benchmark.py --legibility` now persists what it measured

It printed a table and kept nothing. That measurement costs **two vision
passes per image** — the original and the redacted output, because an element
that was never legible cannot be counted as a redaction success — and it was
being thrown away at the end of every run. It now writes `legibility.json`
with per-image detail alongside the aggregate. The aggregate is what gets
quoted; the per-image detail is what makes a quoted number auditable, and it
is what the report's failure list reads.

Reproduced on a second pass, unchanged: payee 80%, account 70%, signature
90%, IFSC 100%, amount 60%, MICR 40%. **MICR at 4 of 10 is the worst element
measured anywhere in this project.**

### Scores from this pass, and one that is not an improvement

| corpus | this run | note |
|---|---|---|
| `documents/` | 92.2% (71/77), core 97%, sensitive 20% | **ceiling of the known band, not a gain** |
| `cheques/` | 73.3% of elements (44/60) | independent; handwriting throughout |
| `holdout/` | 78.9% (56/71) | confirmation 1 |

**`documents/` at 92.2% must not be read as an improvement.** The published
headline is the *floor* of a 69–70 band the scorer moves on partially covered
values; this run landed on 70/72 core where the floor is 69/72. Nothing in
the pipeline changed between them. The published figures stand: **95.8% core,
90.9% overall.**

One incidental confirmation: `14_passport.png` is absent from the documents
verdict list because it is a closed passport cover annotated with **zero**
items and the note "any detection here is a false positive". The pipeline
detected none and copied it through. It is a false-positive control and it
passed — worth stating, because an image missing from a score listing
normally means a dropped page.

---

## 2026-09-18 — One run, three corpora, one folder, one tabbed report

`run_all.py <name>` redacts and scores `documents/`, `cheques/` and
`holdout/` in a single command and writes one tabbed
`runs/<name>/report.html`. Each corpus gets a **complete run folder inside**
that one:

    runs/<name>/
      report.html          tabbed, all three
      documents/           an ordinary run folder
      cheques/
      holdout/

### Nested, not merged, and that is the whole design

Every tool here takes a run directory and expects `images/`, `scored/` and
`score.json` beside each other. Nesting keeps each subfolder a run folder
those tools already understand, so nothing needed rewriting:

    python score_run.py runs/<name>/documents
    python compare_runs.py runs/old/cheques runs/new/cheques

`evaluate_redactor.py` builds its output path as `runs_dir / run_name`, so a
run name containing a slash nests for free — no change to that script at all.

Merging the three into one flat folder was the alternative and it is worse in
a specific way: it would have meant teaching every tool which corpus each
image belonged to, and **a filename collision between corpora would have been
silent.** That is not hypothetical — `holdout/01_aadhaar_card.png` collided
with `documents/01_aadhaar_card.png` earlier today and produced a
whole-corpus verdict shape carrying one page's numbers. Same folder, same
failure, but with no `h` prefix available to fix it.

### The tabs are deliberately not a leaderboard

Three percentages side by side invite a comparison that is not valid, so the
report says so above the tabs and the terminal summary repeats it:

- `documents/` and `holdout/` are scored **per annotated value**.
- `cheques/` carries boxes and no ground-truth text, so it is scored **per
  element** by a vision model. Its percentage is a different measurement.
- `documents/` is familiar material the recognizers were written against and
  reads high for that reason; `cheques/` is the only independent image corpus
  here and reads low. The gap between them is mostly that, not quality.

### Scoring `holdout/` on every run broke the warning signal, so the signal changed

The suite scores all three every time, by request. That makes the held-out
**run count** meaningless as a warning: it now measures how often the suite
ran, not how often the corpus was consulted about a decision.

The signal is therefore **distinct commits scored**. Run the suite ten times
without committing and it stays at one; change the code and look again and it
moves. Re-scoring a single commit is still called out separately, because
that is the specific shape of chasing a result. `test_holdout_guard.py` pins
both: that the count is of commits, and that a second run at one commit does
not move it.

**This is a weakening and it should be recorded as one.** Seeing the holdout
number on every run makes steering on it easier, not harder. The guard still
refuses sweeps; the counter still records; but the discipline is now more
of a human one than it was this morning. `--skip holdout` exists for runs
where the number is not wanted.

### Failures never abort the suite

Each corpus is caught independently, in keeping with the standing rule that a
per-image failure never aborts a batch — the same now applies a level up. A
corpus that fails to redact is reported and skipped, and the report is
written for whatever did complete.

---

## 2026-09-18 — First suite run, and `holdout/` turns out to have its own noise band

First `run_all.py` run, `runs/suite-1`, defaults, at `e914d29`:

| corpus | covered | leaked | floor | scored by |
|---|---:|---:|---:|---|
| `documents/` | 70 | 7 | **90.9%** | value legibility |
| `cheques/` | 44 | 16 | **73.3%** | element legibility |
| `holdout/` | 55 | 16 | **77.5%** | value legibility |

### The interesting result is not any of those numbers, it is that two moved

`documents/` scored 92.2% (71/77) at `5376bb3` and 90.9% (70/77) at
`e914d29`. `holdout/` scored 78.9% (56/71) at `4b44f75` and 77.5% (55/71) at
`e914d29`.

**No detection code changed across any of those commits.** `5376bb3` added
the report and the history; `e914d29` restyled the report and persisted
cheque legibility. Neither touched OCR, recognizers, geometry or rendering.
The redacted images are byte-identical. So both movements are the **vision
scorer disagreeing with itself**, which is the 0–1 band already documented
for `documents/` — now measured a second time, and on a second corpus.

Two consequences, and the second is a correction:

- `documents/` at 90.9% overall is the **floor**, confirmed by landing on it
  again from above. The published headline is unchanged and now has one more
  observation behind it.
- **`holdout/`'s published figure was wrong by one item.** The earlier entry
  reported 78.9% (56/71) as its score. That is the **ceiling** of a 55–56
  band; the floor is **77.5%**. `VALIDATION.md` is corrected to state 77.5%
  and the band. The entry reporting 78.9% stands as written — this supersedes
  its headline rather than rewriting it.

This is the seventh correction to a published number in this project, and it
arrived the same way as several earlier ones: by measuring twice rather than
by finding a bug.

### What it says about the holdout counter

The distinct-commit count is now **2**, and both scorings were confirmations
of changes that could not have affected redaction. That is the counter
working as intended — it rose because the code moved, not because the suite
ran twice. It is also a reminder that a 1-point movement on this corpus means
nothing on its own: the band is a point and a half wide.

---

## 2026-09-18 — Visual PII was never scored, and the QR detector is the weak one

Prompted by a question about a holdout page: why is the QR code on
`h01_aadhaar_card.png` uncovered? The answer turned out to have three layers,
and the second is the serious one.

### 1. The QR is uncovered, and it is not the decode-gating trap

`detect_codes` correctly uses `detect`, not `detectAndDecode` — the
documented trap is not the cause. It is scale and input sensitivity.
`detectMulti` fails on **all four** annotated holdout QRs at native scale;
the `detect()` single-code fallback rescues two; `h01` and `h08` fail both.

`h01` is not undetectable at 1x, which was my first and wrong conclusion. At
1x it is found after an Otsu threshold or a 3x3 Gaussian blur, and not on raw
greyscale. But no single preprocessing wins:

| path | documents (2 QRs) | holdout (4 QRs) |
|---|---|---|
| raw greyscale (ships) | **2/2** | 2/4 |
| 3x3 blur | 0/2 | **3/4** |
| Otsu | 0/2 | **3/4** |
| 5x5 blur | 0/2 | 1/4 |

A naive swap to blur would lose both `documents/` QRs. **No detector change
was made**, because the evidence said the ground truth was the bottleneck.

### 2. Visual PII has never been scored at all

`score_run.py` and `vision_score.py` contained **zero** references to faces,
QR codes or barcodes. The `visual` block in every corpus was ground truth
that nothing compared against. So every published figure — 95.8%, 90.9%,
77.5% — is **text-only**, and an uncovered Aadhaar QR, which encodes the
holder's name, date of birth and address, moves none of them.

That is the gap the README's own rationale points at: the visual layer is one
of the main reasons this project exists, and it was the one part with no
metric.

`vision_score.py` now scores it, as **legibility** rather than detection
count — is a face still recognisable, is a QR's data area still scannable —
for the same reason the text scoring is legibility. `score_run.py` reports it
as a **separate block, deliberately outside the item totals**: folding a new
measurement into the published headline would move it without a single
detection changing.

### 3. The visual ground truth was unreliable, so it was audited

`documents/` annotated two QR codes while the detector reported four, and
nothing said which side was wrong. `audit_visual.py` reads the **unredacted
originals** and proposes a ground truth, reports disagreements, and scores
the detector's precision and recall against it. It writes
`runs/visual_audit.json` and **does not touch `datasets/`** — the same rule
`annotate_inputs.py` follows, and doubly so here because a truth generated by
the model family that grades the output is not independent evidence.

First audit, against `runs/suite-1`:

| kind | TP | FP | missed | precision | recall |
|---|---:|---:|---:|---:|---:|
| face | 5 | 0 | 0 | **100%** | **100%** |
| barcode | 6 | 0 | 0 | **100%** | **100%** |
| qr_code | 4 | 3 | 2 | **57%** | **67%** |

**QR is the only weak visual detector, and it fails in both directions.**
Two false positives on `documents/` (`01_aadhaar_card.png`,
`10_rental_agreement.png` — vision confirms neither page has a QR, so these
are the detector seeing things, not missing annotations), one on `cheques/`,
and two misses on `holdout/`.

Two annotation findings, neither applied:

- `cheques/` has **three real barcodes** — `axis_syn_0001`, `axis_syn_0022`,
  `axis_syn_0027` — annotated nowhere. Its `visual` block is empty throughout.
- `documents/` and `holdout/` annotations **agree with the audit exactly**.
  The documents QR disagreement is the detector's, not the annotation's.

### A hazard demonstrated rather than described

`vision_score.py --limit 3` overwrote a 20-image verdict file with three
entries. CLAUDE.md has warned about this since it was first noticed —
"an API error mid-run yields a *shorter* file, not a partial one" — and
suggested merge-on-write. It happened here in the ordinary course of testing
and cost a full re-score. Still not fixed; now with a reproduction.

**No published number changes in this entry.** Visual scoring is reported
separately and the text totals are untouched.

---

## 2026-09-19 — Merge-on-write, and the cheque corpus gets its visual truth

Two fixes, one of which is the same bug twice.

### `vision_score.py` merges rather than overwrites

The file was written with exactly what the current pass scored, which made
two ordinary situations silently destructive: `--limit 3` replaced a
20-image verdict file with three, and an API error part-way through produced
a *shorter* file rather than a partial one. `score_run.py` then fell back to
OCR verdicts for the missing pages and reported a whole-corpus number built
mostly from the weaker scorer — the scorer this project switched away from
precisely because it is blind where redaction fails.

This was a known trap. `CLAUDE.md` has carried it since it was first noticed,
with the suggested fix written down — "worth a merge-on-write, or at least a
warning when the file shrinks" — and it sat there until it cost a full
re-score during ordinary testing. **A documented trap is not a fixed trap.**

Now: pages scored this pass win, earlier pages survive, entries whose image
has left the run are dropped so a corpus change cannot leave stale verdicts,
and the count carried over is printed. It still warns if the file shrinks.
Verified by re-running `--limit 2` over a 19-page file: all 19 pages and all
20 visual entries survived.

### The same bug, written an hour later

`audit_visual.py` — written earlier the same session — replaced
`runs/visual_audit.json` wholesale, so `--corpus cheques` discarded the
`documents` and `holdout` proposals. Identical shape, identical cause, and
written **after** the first one was diagnosed.

That is the useful part of this entry. The rule is not "remember that
`vision_score.py` truncates"; it is **any script that writes a whole results
file from a partial pass has this bug**, and `CLAUDE.md` now says so in those
terms rather than naming one script.

### `cheques/` had no visual ground truth at all

Not wrong — absent. No entry carried a `visual` block, which is why
`entry["visual"]` raised a `KeyError` the first time anything asked. Three
real barcodes on `axis_syn_0001`, `axis_syn_0022` and `axis_syn_0027` were
ground truth nowhere, so the barcode detector could not be scored on the only
independent image corpus here.

All ten entries now carry a block, from `audit_visual.py` reading the
unredacted originals and agreeing with the detector on all three barcodes.
No face or QR code is present on any cheque. The `qr_code` the detector
reports on `syndicate_syn_0049` is the bank's dog logo — a confirmed false
positive, and it stays annotated as absent.

After the change, `cheques/` visual scoring is barcode **100% precision, 100%
recall**, with the one standing QR false positive. The corpus-wide QR figures
are unchanged at **57% precision, 67% recall**; adding the barcodes moved no
QR number.

**Provenance is recorded in the corpus `_meta`**, including that the counts
are model-proposed and detector-confirmed rather than independently authored.

---

## 2026-09-19 — `holdout/` grows to 21 pages, and QR detection finally has a sample

Ten pages added, chosen partly to fix a measurement gap: **QR ground truth
went from 4 regions to 9**, which is why the detector's QR figures can now be
read with something better than four true positives behind them.

`holdout/` is now 21 images and 118 items, 14 sensitive-tier. The new pages
add a boarding pass, lab report, water bill, handwritten school-admission
letter, hotel receipt, prescription, shipping label, loan application, cafe
receipt and a second ID card.

**The corpus changed size, so scores across the change are not comparable.**
The two earlier holdout entries — 78.9% and 77.5%, both on 11 images — belong
to the smaller corpus. `_delta_line` now refuses to compute a delta when
`image_count` differs between runs and says why: a percentage across a moved
denominator is not a trend. The sparkline still spans both points, and the
text tells the reader to read them separately.

### Suite results, `runs/suite-2`

| corpus | covered | leaked | | note |
|---|---:|---:|---:|---|
| `documents/` | 71 | 6 | 92.2% | ceiling of the known band again |
| `cheques/` | 46 | 14 | 76.7% | up from 73.3% with no pipeline change |
| `holdout/` | 89 | 29 | 75.4% | new corpus — not comparable with 77.5% |

`cheques/` moving 73.3% → 76.7% on two elements, with nothing in the pipeline
changed, is the vision scorer's own disagreement. That corpus is scored by
asking a model per element, so it has a band like the others; this is the
first time it has been observed, and it means a two-element cheque difference
is noise.

### QR detection: 75% precision, 82% recall — and the misses are two different bugs

| kind | found | false positives | missed | precision | recall |
|---|---:|---:|---:|---:|---:|
| face | 6 | 0 | 0 | **100%** | **100%** |
| barcode | 7 | 0 | 1 | **100%** | **88%** |
| qr_code | 9 | 3 | 2 | **75%** | **82%** |

Up from 57% / 67% on the smaller sample. **All five QR codes on the new pages
were detected**; the two misses are still `h01_aadhaar_card.png` and
`h08_retail_invoice.png`. The new barcode miss is `h13_boarding_pass.png`,
whose code is a dense 2-D symbology printed between 1-D guard bars.

**`cv2.QRCodeDetector.detectMulti` failed on all eleven real QR codes.**
Every detection in this project comes from the `detect()` single-code
fallback. `detectMulti` is contributing nothing on this data and is worth
either dropping or understanding.

**Size is not the discriminator, which was the obvious hypothesis and is
wrong.** `h01`'s QR is 319px — the *largest* in the whole set, 20.8% of its
page width — and it is missed, while `h02`'s 138px at 9.7% is found. `h08`'s
59px is the same size as `h11`'s 61px, and one is found and the other is not.

The two misses are two distinct failures:

- **`h01` is a contrast failure.** Its QR sits on the Aadhaar guilloche
  security pattern. At native scale, Otsu binarisation or a 3x3 blur both
  rescue it; upscaling rescues it only at exactly 2x.
- **`h08` is a module-resolution failure.** Small *and* dense, so each module
  is around a pixel. No preprocessing at 1x rescues it; only upscaling to
  2.5x or beyond does.

That is why no single preprocessing path fixed both, which was the reason the
detector was left alone yesterday.

### A cascade would reach 100% recall, at a precision cost — and is NOT adopted

Trying raw, then Otsu, then 2.5x, first hit wins:

| | found | false positives | missed | precision | recall |
|---|---:|---:|---:|---:|---:|
| shipped today | 9 | 3 | 2 | 75% | 82% |
| raw → Otsu → 2.5x | 11 | 5 | 0 | **69%** | **100%** |

It covers both misses and adds two false positives
(`documents/05_doctor_prescription.png` at 2.5x,
`holdout/h05_electricity_bill.png` at Otsu).

By this project's stated preference — recall over precision, since a missed
Aadhaar QR encodes name, date of birth and address while a false positive
blacks out a harmless patch — that is the right trade. **It is still not
adopted, and the reason is the holdout rule.** Both misses are holdout pages,
and the specific choices of *Otsu* and *2.5x* were picked by looking at what
rescued them. That is choosing a parameter from the held-out corpus, which is
exactly what `refuse_if_tuning()` exists to prevent a script from doing — and
a person doing it by hand is the same act.

**What would make it adoptable:** QR-bearing pages in `documents/` or
`cheques/`, or a third-party corpus, that exhibit the same two failure modes.
The precision cost is already measurable on the permitted corpora; it is the
recall evidence that lives in the wrong place.

## 2026-09-19 — README carried the pre-growth holdout and QR figures for a commit

**Corrected.** Three figures in `README.md` described the state before
`0d19021`, while `VALIDATION.md`, `DECISIONS.md` and `datasets/README.md` had
all moved on. This is the failure the documentation rule exists to catch, so
it is recorded rather than quietly patched.

| Where | Said | Is |
|---|---|---|
| holdout description | held-out test set of **11 pages and 71 items** | **21 pages and 118 items** |
| visual detection | barcodes **100% / 100%**, QR **57% / 67%**, two false positives | barcodes **100% / 88%**, QR **75% / 82%**, **three** false positives |
| the run report | trend across previous runs, no mention of the denominator guard | `_delta_line` states no delta when the corpus has changed size |

**Why it happened.** The commit that grew the corpus rewrote `VALIDATION.md`
wholesale — that file is organised by corpus, so a corpus changing size forces
the edit. `README.md` mentions the same counts in prose, in two sections that
the change did not otherwise touch, and nothing pointed from one to the other.

**Why `check_docs.py` passed.** It enforces tense, link and anchor resolution,
and that every script is documented. A figure going stale breaks none of
those: the sentence is still present tense, and `datasets/holdout/` still
resolves. Numeric freshness is not machine-checkable here without a canonical
source for each figure, which does not exist — the numbers live in prose in
three files by design, because each states a different thing about them.

**Not corrected, because it is not wrong:** the 95.8% core / 90.9% overall
headline in `README.md` and `CLAUDE.md`. suite-2 scored `documents/` at 92.2%
overall, which is 70/72 core — the ceiling of the known 69-70 band, not a new
result. The project publishes the floor, so the headline stands.

**What would prevent a recurrence:** the check that would have caught this is
a grep for a corpus's item count appearing in more than one file with
different values. Worth writing when a fourth file carries these numbers; with
three, the rule in `CLAUDE.md` is to update all of them in the same commit,
and the failure here is that the rule was followed for two of three.

# Validation: what is measured, how, and what is not

This project's headline number has been wrong six times. Each correction
is recorded in [DECISIONS.md](DECISIONS.md); this file is the standing
answer to a different question — **how much should you trust any number
here, and what is still unmeasured?**

The short version: the recognizer layer has real independent evidence and
scores in the **60–75%** range on it. The image pipeline has almost none —
every image-level figure rests on either 20 documents this project drew
itself or 10 cheques of a single document type.

That is a gap in work done, not a gap in available data. Non-commercial
licences are acceptable for corpora used locally and never redistributed,
which puts several suitable datasets in scope; see
[the gaps](#1-there-is-no-independent-indian-form-corpus-that-is-safe-to-use).
What remains genuinely absent is an Indian **form** corpus that is both
annotated and safe to use.

---

## Two rules govern everything below

**Indian data sets the numbers.** Thresholds, tolerances and defaults are
tuned on `documents/` and `cheques/`. `ktp/` is Indonesian and validates
the *mechanism* — the label-to-value geometry, which is locale-independent
— but never the parameters, however much larger it is.

## The rule that governs everything below

**Evidence must come from data this project did not produce.**

That rule exists because it was broken. Two corpora — `pack/` and
`generated/` — were built here, scored here, and quoted as proof the code
worked. The recognizers and the test data had the same author: this
project invented formats like `MRN-458361` and `MH/MED/2011/45892`, then
wrote regexes matching them. They agreed with each other and disagreed
with reality, and the scores split exactly along that line:

| corpus | produced by | score |
|---|---|---|
| `documents/` | this project | 97.2% core |
| `pack/` | this project | 90% |
| `generated/` | this project | 79.0% |
| IndiaPII-Bench | independent | 76.6% |
| maskara | independent | 82.7% |
| cheques | independent | **payee name 60%, account number 40%** (legibility) |

`pack/` and `generated/` were deleted rather than kept as benchmarks, and
the generator that made them was deleted with them, so that no later
session could reach for it.

---

## What is actually measured

### Independent evidence

| what | data | who made it | licence | result |
|---|---|---|---|---|
| recognizers on text | IndiaPII-Bench, 2,000 docs, 12,065 PII spans | third party | CC-BY-4.0 | **76.6% recall** |
| recognizers on text | maskara, 2,600 docs, 7,600 spans | third party | MIT | **82.7% recall** |
| label lexicon | IndiaPII-Bench, 9,782 labelled values | third party | CC-BY-4.0 | **100% recall, 97.2% precision** |
| legibility on images | 10 cheques, 6 elements each, vision-scored | third party | Apache-2.0 | **IFSC 100%, payee name 60%, signature 60%, account number 40%** |
| label-anchored geometry | 20 Indonesian ID cards, 180 regions, publisher boxes | third party | CC-BY-4.0 | **44/180 fully covered, vs 12/180 with the mechanism off** |

### Project-produced evidence, and therefore weaker

| what | data | result |
|---|---|---|
| end-to-end legibility | `documents/`, 20 images, 77 items, vision-scored | **97.2% core** (70/72); 97.4% overall with `--medical-ner` |
| label geometry | hand-built OCR dicts, `test_labels.py` | 17 checks pass |
| metadata hygiene | synthetic EXIF/GPS fixtures, `test_metadata_stripping.py` | 3 checks pass |

`documents/` is kept because it is the original corpus, its 77 items were
audited by an independent vision pass, and its leaks are documented. But
**97.2% is a ceiling on familiar material, not performance.**

---

## Per-recognizer evidence

Only two custom recognizers survive. The other seven were removed in
September 2026 because each encoded a shape this project invented; four of
them had never fired once across 67 pages.

| recognizer | independent evidence | verdict |
|---|---|---|
| `IN_IFSC` | **100%** on 1,142 IndiaPII examples | published RBI format, 11 characters with a mandatory `0` at position five |
| `IN_ABHA` | **100%** (286) | 14 digits, Luhn-10 (NHA/ABDM). Checksum-validated, with a context-anchored fallback for checksum failures |
| `IN_AADHAAR_MASKED` | **100%** (285) | UIDAI masking convention |
| `IN_ABHA_ADDRESS` | **100%** (141) | fixed `@abdm` / `@sbx` suffix |
| `IN_UPI_VPA` | **97%** / **100%** | NPCI VPA shape — no dot after the `@` |
| `IN_VEHICLE_REGISTRATION` | **100%** / **98%** | CMVR 1989 Rule 50, including the BH series |
| `IN_AADHAAR_VID` | no corpus exercises it | 16 digits, Verhoeff (UIDAI). Spec-backed but **unmeasured** |
| `IN_DRIVING_LICENCE` | **100%** / **100%** | **empirical, not specified** — see below |

### The driving licence is the one exception, and it is marked as such

Every other pattern here cites a published specification. The driving
licence has none that could be found: Wikipedia's licence article does not
cover numbering, and secondary sources disagree on whether the RTO code is
two characters or three. Two independent corpora contain incompatible
shapes — `KA05 20230012345` against `KL-2009-119628` and `WBBY1990931178`.

It is therefore **empirical**: the pattern accepts the union of what those
two corpora contain, with a year in the middle as the invariant that keeps
it from matching arbitrary alphanumerics. It reaches 100% on both, and
rejects invoice numbers of similar shape.

The distinction that matters: this is fitted to **two independent
sources**, not to data this project generated. That is weaker than a
specification and stronger than an invention, and the docstring says so.
`DL No` is also a label, so `redactor/labels.py` covers these on a page
regardless of shape.

### Presidio's own recognizers

`IN_AADHAAR`, `IN_PAN`, `IN_VOTER`, `IN_PASSPORT`, `IN_GSTIN` all score
98–100% on IndiaPII. Two caveats:

- **`IN_AADHAAR` scores 0% on masked Aadhaar numbers** (285 examples) —
  the `XXXX XXXX 1234` form that appears on real redacted documents.
- **`IN_VEHICLE_REGISTRATION` scores 22–31%** across both corpora.

Also worth recording: **Presidio ships no test data.** `presidio-research`
is a template-and-Faker generator, and Presidio's own recognizer tests are
hardcoded strings. So the numbers above may be the only independent
evidence that exists about its India recognizers.

---

## The gaps

### 1. There is no independent Indian **form** corpus that is safe to use

The first version of this section said "there is no independent Indian
document-image corpus" and treated the search as closed. That was wrong on
both counts, and the correction matters more than the original claim.

**The framing error.** The unvalidated half of our approach — the geometry
that pairs a label to its value — is **locale-independent**. A French ID
card tests it exactly as well as an Aadhaar card. Searching only for
*Indian* image data was looking for a constraint that does not apply, and
it hid an entire family of usable datasets.

#### Usable for the geometry half

A systematic sweep of the HuggingFace **API** — rather than web search,
which had missed all of these — turned up the strongest candidate:
**24,000 synthetic Indonesian national ID cards under CC-BY-4.0, with
per-field bounding boxes carried alongside the text**, plus 109,000
augmented variants. Its fields map onto an Aadhaar card almost exactly.
That is the geometry gap closed, pending the work of using it.

| dataset | scale | annotations | licence |
|---|---|---|---|
| **cloverx-id/indonesian-id-card-dummy** | 24k flat + 109k augmented | **per-field boxes + text**, synthetic, no real people | **CC-BY-4.0** |
| **naver-clova-ix/cord-v2** | 1k–10k receipts | key-value field annotations | **CC-BY-4.0** |
| **DocILE** | 6.7k annotated + 100k synthetic | 55 classes **with localization** | code MIT, dataset gated by request form |
| **MIDV-500** | 50 document types, 15,000 annotated frames | field quadrangles, document types | source images from Wikimedia Commons, **public domain / open licences**; plain FTP, no gate |
| **MIDV-2020** | 72,409 images, 1,000 mock IDs | 546 text fields, 48 photo, 40 signature — values *and* positions | **undisclosed**, 124GB behind a form |
| **DocXPand-25k** | 24,994 images, 9 fictitious ID designs | rich per-field labels, synthetic faces and values | **CC BY-NC-SA 4.0** (its code is MIT) |
| **BID** | 28,800 Brazilian IDs, 8 templates | text regions, OCR | **unstated** in the repository |
| **FUNSD** | 199 real scanned forms | **human-annotated question→answer links** — label paired to value by a person | non-commercial research and educational use |
| **XFUND** | 7 languages | human key-value form annotations | CC BY-NC-SA 4.0 |

**FUNSD is the closest fit to what is unvalidated here**, and it only came
into scope when non-commercial licences were accepted for local use. Its
annotation *is* the thing `labels.py` computes: a person decided which
value belongs to which label. Nothing else on this list tests the geometry
that directly. It is English and American, so it tests the mechanism and
not the lexicon — which is the right division of labour, since the lexicon
is already measured on Indian data.

All are synthetic or open-licensed mock documents, so none carries real
personal data. MIDV-500 and MIDV-2020 also span Cyrillic, Greek and
Chinese fields, which would be the first real test of non-Latin labels.

#### Not usable, and not for licence reasons

| dataset | why not |
|---|---|
| **FIR dataset** (TransDocAnalyser) | **real** First Information Reports collected from Indian police stations — real complainants, addresses and case details, with no anonymisation described |
| Kaggle / Roboflow Aadhaar sets | field-annotated **real Aadhaar cards** |

These are the closest match to what this tool protects, and that is
precisely the objection. A permissive licence does not make it acceptable
to process real people's national identity numbers or police reports —
people who did not consent to being in an ML benchmark — and FIRs carry
crime-report data about victims and accused persons. **This is an ethics
constraint, not a licensing one, and it does not expire.**

#### Still not usable, licence

| candidate | why |
|---|---|
| IndicDLP (MIT, 121k real Indian pages) | 11 of 12 domains carry no field-PII; publicly scrapeable forms are blank templates; layout boxes only, no text |
| LeakageBench (500 images, 11,954 PII annotations) | Data Use Agreement, GDPR/European |
| LeakageBench (500 images, 11,954 PII annotations) | Data Use Agreement, GDPR/European |
| nvisycom/synthetic (MIT) | images unimplemented — "only text-bearing formats render" |
| presidio-research | a generator, no corpus |

**What remains genuinely absent** is an Indian *form* corpus — filled-in
applications, bills, medical and government forms — that is both annotated
and safe to use. The structural reason holds: documents containing real
PII are not published, the ones that leak out are real people's, and
almost nobody builds synthetic replacements. The cheque dataset's own
paper is titled *"Open Annotations and Synthetic Data for Field
Localisation in Indian Bank Cheques"* — released Apache-2.0 because the
field had nothing. Closing that gap honestly means commissioned or
consented data, not a better search.

**Repositories swept:** HuggingFace, GitHub, Kaggle, Roboflow Universe,
Mendeley Data, Zenodo, arXiv. **Not yet swept:** ICDAR/DAS competition
archives, data.gov.in, Papers-with-Code.

### 2. The cheque corpus is 3% used

295 images are available with publisher-drawn boxes. Every cheque figure
in this repo rests on **10 of them** — 30 regions where 885 were free. The
cheapest available improvement to the evidence base.

### 3. Label-anchored redaction is half-validated

`redactor/labels.py` has two halves that fail independently:

- the **lexicon** — does it recognise a label as introducing PII?
  **Measured**: 100% recall / 97.2% precision on 2,000 independent forms.
- the **geometry** — does it pair that label with the right value on a
  page? **Now measured**: on 20 synthetic Indonesian ID cards with
  publisher-authored boxes, turning it on lifts regions fully covered from
  **12/180 to 44/180**, with per-field gains of +29 to +50 points. The
  sharpest evidence is `religion` (13%→60%) and `blood_type` (62%→91%),
  which no recognizer covers at all — nothing but label-anchoring can
  redact those. Still unmeasured: Devanagari, handwriting, Indian form
  conventions.

### 4. The recognizer cull cost 9 points on text, and the replacement is unproven there

Removing `IN_BANK_ACCOUNT` and six others dropped IndiaPII recall from
**76.2% to 67.2%**, with `BANK_ACCOUNT_IN` falling to 0% — 1,142 items.
Label-anchoring is meant to cover those, but it needs page geometry, which
a text benchmark cannot exercise. On text the cull is a pure loss; whether
images recover it is **untested**.

### 5. The vision-model path is unevaluated, and cannot be evaluated here

`redactor/vlm.py` is shipped, tested and **off by default**. What is known:

- the integration is correct — Ollama reached, boxes parsed, and a
  coordinate bug found and fixed by *drawing the boxes and looking at them*
- accuracy on one image: **1 of 6 PII items** (indicative only)
- throughput on this machine: **0.8 tokens/sec**, memory free at 13%, so a
  reply listing six items takes ~5 minutes per image against the Presidio
  pipeline's measured 1.75 s/image

That is an infeasibility result about 8GB of RAM, not evidence about
vision models. A 3B model under memory pressure is not a fair test of the
idea, and the single box it produced was accurate and tightly placed.
Re-test on a machine that can hold a 7B model before drawing any
conclusion about whether this replaces or supplements the OCR path.

### 6. Untested entirely

- **Devanagari and other Indic scripts.** Both text corpora are Latin. The
  lexicon carries Devanagari terms that no benchmark exercises.
- **Handwriting.** The one place it was measured — cheques — was
  catastrophic.
- **Real OCR noise on labels.** maskara's `ocr` domain is synthetic corruption.
- **Over-redaction cost.** 19% of detections on IndiaPII (3,159 of 16,619)
  match no labelled PII, and 76% of timestamp-shaped decoys are flagged as
  something. This project prefers over-redaction to a miss, but the cost
  is unquantified in terms of document usability.

---

## How the numbers are produced

Scoring asks whether each known PII item is **still legible in the
output**, not whether a box overlapped it. A box can cover 85% of a value
and still leak it.

- `vision_score.py` shows each redacted image to Claude and asks what
  remains readable. It has found leaks that both OCR and a careful manual
  pass missed.
- An OCR-based scorer is blind exactly where redaction fails — on
  low-contrast photographs it reads almost nothing and reports plainly
  visible PII as "redacted".
- **Per-region coverage from vision-generated boxes was built, measured
  and removed**: those boxes sat about a text row off and reported 0% for
  a field that was plainly blacked out. Coverage survives only for the
  cheques, whose boxes were drawn by the dataset's publishers.

### Controls, and why they matter

The label-lexicon benchmark reports a third row nobody asked for: what a
rule that matches **every** labelled line would score. It gets 100% recall
and 87.6% precision, because that corpus is 87.6% PII-dense. Without that
control, "100% recall" reads as a triumph instead of as the expected
result. Any new metric here should carry its trivial baseline.

---

## Failure modes this project keeps hitting

Recorded because they recur, not as history:

1. **Grading homework against its own answer key.** Caused the deletion of
   two corpora and seven recognizers.
2. **Metrics that move for the wrong reason.** Two PaddleOCR bugs *raised*
   entity counts while *lowering* actual redaction. Entity counts are not
   a measure of anything.
3. **Silent zeros.** A per-field analysis once reported 0 leaks in every
   field while the scorer it read had just reported 47 — it looked for a
   `verdicts` list in a file that is a flat map. Clean, plausible, and
   entirely wrong.
4. **Ground truth assumed rather than read.** An image model does not
   render the values you asked for; a corpus scored against the prompt is
   scored against text no image contains.
5. **Incomplete ground truth flattering the score.** Richer documents
   carry PII nobody labelled — 52 labelled items against 75 unlabelled
   ones on one sample. Every score here is optimistic by an unknown
   margin.
6. **Perfect scores.** Treat any 100% as a bug report until a trivial
   baseline has been computed.

---

## What would close the gaps, in order of value

1. **Use the other 285 cheques.** Free, independent, already licensed.
2. **Find or commission Indian form images with field annotations.** The
   binding constraint on everything else. A small consented set from real
   workflows would be worth more than any amount of generated data.
3. **Quantify over-redaction.** Recall is measured; the cost of false
   positives is not.
4. **Re-measure the cull on images.** Whether label-anchoring recovers the
   1,142 bank-account items lost on text is the open question behind the
   current architecture.

---

## Reproducing

```bash
python benchmark_indiapii.py          # recognizers vs 2,000 independent forms
python benchmark_maskara.py           # recognizers vs 2,600 independent docs
python benchmark_labels.py            # label lexicon, with its trivial baseline
python cheque_benchmark.py --score runs/cheques   # independent image coverage
python test_labels.py                 # label geometry (hand-built, weak evidence)
python test_metadata_stripping.py     # EXIF/GPS/thumbnail stripping
```

The text benchmarks need their corpora downloaded first — see each
script's docstring. The cheques are committed.

---

## Correction — cheque region coverage was misread as failure

`0 of 30 regions fully covered` was quoted here and in `README.md` as the
headline proof that the documents figure does not generalise. It does not
mean what it was taken to mean.

The publishers' regions span whole form rows. An `acno` box is ~730×95 and
contains the printed "A/C NO." label, the cell border and the bank's
watermark as well as the number; a `name` box is ~2,260 wide — the entire
"PAY ......... OR BEARER" line — of which a handwritten name occupies about
a fifth. **A correct redaction scores around 20% by construction.** Ink
coverage was tried as a fix and is no better, because the ink includes the
label and the watermark that should not be covered.

Measured by legibility instead — what a reader can still make out, which
needs no ground-truth text:

| element | covered |
|---|---:|
| branch IFSC | **10/10** |
| payee name | 6/10 |
| signature | 6/10 |
| MICR line | 6/10 |
| account number | 4/10 |

Cheques remain by far the weakest case, and handwriting remains the
reason. But "nothing is covered" was wrong, and the error was in the
metric rather than in the redactor.

# Validation: what is measured, how, and what is not

This project's headline number has been wrong six times. Each correction
is recorded in [DECISIONS.md](DECISIONS.md); this file is the standing
answer to a different question — **how much should you trust any number
here, and what is still unmeasured?**

The short version: the recognizer layer has real independent evidence and
scores in the **60–75%** range on it. The image pipeline has almost none,
because annotated Indian document images with PII do not exist under a
permissive licence. Every image-level figure rests on either 20 documents
this project drew itself or 10 cheques of a single document type.

---

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
| `documents/` | this project | 93.5% |
| `pack/` | this project | 90% |
| `generated/` | this project | 79.0% |
| IndiaPII-Bench | independent | 67.2% |
| maskara | independent | 75.6% |
| cheques | independent | **0 of 30 regions fully covered** |

`pack/` and `generated/` were deleted rather than kept as benchmarks, and
the generator that made them was deleted with them, so that no later
session could reach for it.

---

## What is actually measured

### Independent evidence

| what | data | who made it | licence | result |
|---|---|---|---|---|
| recognizers on text | IndiaPII-Bench, 2,000 docs, 12,065 PII spans | third party | CC-BY-4.0 | **67.2% recall** |
| recognizers on text | maskara, 2,600 docs, 7,600 spans | third party | MIT | **75.6% recall** |
| label lexicon | IndiaPII-Bench, 9,782 labelled values | third party | CC-BY-4.0 | **100% recall, 97.2% precision** |
| region coverage on images | 10 cheques, 30 regions, boxes drawn by the publishers | third party | Apache-2.0 | **0 of 30 fully covered** |

### Project-produced evidence, and therefore weaker

| what | data | result |
|---|---|---|
| end-to-end legibility | `documents/`, 20 images, 77 items, vision-scored | 93.5%, 5 leaks |
| label geometry | hand-built OCR dicts, `test_labels.py` | 17 checks pass |
| metadata hygiene | synthetic EXIF/GPS fixtures, `test_metadata_stripping.py` | 3 checks pass |

`documents/` is kept because it is the original corpus, its 77 items were
audited by an independent vision pass, and its leaks are documented. But
**93.5% is a ceiling on familiar material, not performance.**

---

## Per-recognizer evidence

Only two custom recognizers survive. The other seven were removed in
September 2026 because each encoded a shape this project invented; four of
them had never fired once across 67 pages.

| recognizer | independent evidence | verdict |
|---|---|---|
| `IN_IFSC` | **100%** on 1,142 IndiaPII examples | **earns its place.** The format is genuinely published — RBI, 11 characters, mandatory `0` at position five — which is also why it can fire without a label |
| `IN_DRIVING_LICENCE` | **100%** on IndiaPII (286), **0%** on maskara (200) | **encodes a guess, not a format** — see below |

### The driving-licence problem, stated plainly

Two independent corpora disagree completely about what an Indian driving
licence looks like. maskara's values look like `KL-2009-119628` and
`WBBY1990931178` — six-digit serials, four-letter prefixes. Our pattern
forbids both, because it was built from an example this project invented
(`KA05 20230012345`), and it matches IndiaPII only because IndiaPII's
author happened to guess the same way.

No authoritative specification was findable: Wikipedia's licence article
does not cover numbering, and secondary sources disagree on whether the
RTO code is two characters or three. **A recognizer that scores 100% and
0% on two independent corpora has not been validated — it has been shown
to match one author's opinion.**

Note that the label mechanism catches the maskara cases anyway: their text
reads `DL No: TSJB2003555471`, and `DL No` is a label.

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

### 1. There is no independent Indian document-image corpus

This is the central gap and it is not for want of looking:

| candidate | why it does not work |
|---|---|
| IndicDLP (MIT, 121k real Indian pages) | 11 of 12 domains carry no field-PII; publicly scrapeable forms are blank templates; layout boxes only, no text |
| FUNSD (199 forms, human label→value links) | non-commercial research licence — and it is exactly the right shape |
| XFUND | CC BY-NC-SA 4.0 |
| LeakageBench (500 images, 11,954 PII annotations) | Data Use Agreement, GDPR/European |
| nvisycom/synthetic (MIT) | images unimplemented — "only text-bearing formats render" |
| presidio-research | a generator, no corpus |

The reason is structural: **documents containing real PII are not
published, and almost nobody builds synthetic replacements.** The cheque
dataset's own paper is titled *"Open Annotations and Synthetic Data for
Field Localisation in Indian Bank Cheques"* — released Apache-2.0 because
the field had nothing.

### 2. The cheque corpus is 3% used

295 images are available with publisher-drawn boxes. Every cheque figure
in this repo rests on **10 of them** — 30 regions where 885 were free. The
cheapest available improvement to the evidence base.

### 3. Label-anchored redaction is half-validated

`redactor/labels.py` has two halves that fail independently:

- the **lexicon** — does it recognise a label as introducing PII?
  **Measured**: 100% recall / 97.2% precision on 2,000 independent forms.
- the **geometry** — does it pair that label with the right value on a
  page? **Not measured on real data at all.** Pinned only by
  `test_labels.py` on hand-built OCR dicts.

### 4. The recognizer cull cost 9 points on text, and the replacement is unproven there

Removing `IN_BANK_ACCOUNT` and six others dropped IndiaPII recall from
**76.2% to 67.2%**, with `BANK_ACCOUNT_IN` falling to 0% — 1,142 items.
Label-anchoring is meant to cover those, but it needs page geometry, which
a text benchmark cannot exercise. On text the cull is a pure loss; whether
images recover it is **untested**.

### 5. Untested entirely

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

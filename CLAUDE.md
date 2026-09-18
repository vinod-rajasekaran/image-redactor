# CLAUDE.md

Guidance for Claude Code working in this repo.

## Keep the documentation current — this is not optional

Three files carry this project's knowledge, and each has a distinct job.
**Update them as part of the change, in the same commit, not afterwards.**
A default whose rationale is undocumented gets "simplified" away by the
next session, and a measurement whose caveats are undocumented gets quoted
as fact.

| File | Job | Rule |
|---|---|---|
| `README.md` | How the tool works **now** | Present tense. No history, no "we used to". Every flag and filename in it must exist — check before committing. |
| `DECISIONS.md` | Time-ordered history: decision, why, evidence | **Append; never rewrite an entry.** Supersede an old one and mark it `Superseded`. Keep rejected options — they stop the next session re-litigating them. |
| `CLAUDE.md` | Working guidance for Claude | The traps, the invariants, the things that look wrong but aren't. |
| `VALIDATION.md` | What is measured, on whose data, and what is not | Update whenever a benchmark is run, a corpus changes, or a gap opens or closes. Every claim in it names its data source and who produced it. |
| `LICENSE` | MIT, Project Tech4Dev | Covers the code and everything authored here. Data terms are per corpus in `SOURCES.md`, because they differ. |
| `SOURCES.md` | Every dataset and model: licence as checked, link, and purpose | Add the row **before** using a source. Record how the licence was verified — API, page, or search — because those are different strengths of claim. Keep rejections; ethics rejections never expire. |

**`python check_docs.py` enforces the first two rows** — run it before a
push. It catches what a diff cannot: a README sentence that has drifted
into narrating history ("was tested", "no longer", "previously", a date), a
filename or anchor that no longer resolves, and a script that exists but is
undocumented. `DECISIONS.md` is exempt from the tense rule by design.

Update all three when you:

- change a default, or the evidence behind one
- add, remove or rename a module, script or flag
- produce a new measurement, or invalidate an old one
- find a bug whose cause is non-obvious, or reject an approach after testing

When a published number turns out to be wrong, **say so explicitly in
`DECISIONS.md` and correct it everywhere it appears.** This project's
headline recall has been corrected six times; each correction is recorded
with what was wrong and why. That record is more useful than the number.

## Re-check the structure before any significant push

Alongside the documentation rule above: when a push adds a script, a
corpus, a benchmark or a module, **look at the repo layout before you
push it** and ask whether the new thing landed somewhere defensible.

The two failures this catches, both of which happened here:

- **Scattered corpora.** Validation images accumulated as `input_images/`,
  `cheque_images/` and `pack_images/`, with three near-identical
  annotation schemas and every script hardcoding its own paths. Adding a
  fourth meant editing all of them. They now live under `datasets/<name>/`
  with one schema and one loader (`redactor/datasets.py`).
- **A god module.** `evaluate_redactor.py` reached 782 lines doing seven
  unrelated jobs before it was split.

Both were cheap to fix when caught and would have compounded. A structural
change is safe to make *only* with a verification that behaviour did not
move — for the package split it was byte-identical output images; for the
corpus move it was identical scores on all three corpora. If you cannot
show that, you have done a rewrite, not a refactor.

## What this is

A local evaluation harness for Presidio's image redaction, aimed at Indian
documents. OCR, detection and redaction run on-device. The only network
call is to Claude, and only for *scoring* — never for redaction.

Current result: **95.8% of core PII redacted** (69/72 across 20
documents), 90.9% overall (70/77), vision-scored. That is the **floor** of
a 69-70 band: the images are byte-identical run to run, but the vision
scorer disagrees with itself on 0-1 of 77 items, always on a partially
covered value. Publish the floor. The five `sensitive`-tier items —
diagnoses and medications — go 1/5 to 4/5 with `--medical-ner`, which is
off by default because it pulls in torch.

## Layout

`redactor/` is the package; the top-level `*.py` files are thin CLIs.

- `pipeline.py` — `process_image()` is the per-image flow: sanitize,
  build preprocessed variants, analyse them concurrently with the visual
  detectors, union the boxes, merge stacked blocks, draw, save.
- `recognizers.py` — `build_registry()` is the **single source of truth**
  for which recognizers exist. It was duplicated once between the
  pipeline and the IndiaPII benchmark, and a recognizer added to one was
  silently missing from the other's scores. Don't re-introduce a second
  assembly path.
- `ocr.py`, `reading_order.py`, `variants.py` — OCR adapters, the
  row-major re-sort, and the preprocessing variants.
- `detect.py`, `geometry.py`, `render.py` — visual PII, box geometry, and
  drawing. These are separate on purpose; they change for different
  reasons.
- `hygiene.py`, `runs.py`, `vision.py` — metadata stripping, run folders,
  shared Claude client.
- `vlm.py` — optional vision-model detection against any OpenAI-compatible
  endpoint, unioned as a fourth parallel path. Never substitutes for the
  deterministic layer, and never fails an image: `_vlm_regions_for` returns
  `[]` on any error, so a model being down cannot stop a run. The risky
  part is the **coordinate convention** — fraction, per-mille and pixel all
  occur, and guessing wrong puts every box in the wrong place, which is a
  leak that looks like a redaction. `test_vlm.py` pins that inference.
- `labels.py` — redacts the value *beside* a personal-data label, by
  geometry, whatever shape it has. This exists because shape-first
  detection cannot cover identifiers that have no national format, and
  because every OCR word already carries a box that the text-flattening
  path was throwing away.
- `clinical.py` — the one module that **removes** boxes. Off by default
  (`--protect-clinical`), for documents a clinician or downstream model
  must still be able to read. See the trap below before changing it.

`datasets/` holds every validation corpus — images and annotations
together, one schema, loaded through `redactor.datasets.load(name)`.
**Every corpus is synthetic**, and each one's `_meta` block states its
source and licence; keep that true of anything added. `documents/` and
`cheques/` are committed; `text/` is fetched on demand.

**Indian data sets the numbers; other corpora only cross-check.**
`datasets/ktp/` is Indonesian. It earns its place because the label-to-value
geometry it validates is locale-independent, and because no Indian form
corpus exists that is both annotated and safe. It must **not** set
thresholds, tolerances or defaults — those belong to `datasets/documents/`
and `datasets/cheques/`, which are Indian, even though KTP is the larger
corpus (180 regions against 77 items) and will look tempting. Use it to
confirm a change does not regress, never to decide what the change should
be.

**`datasets/holdout/` may never be used to tune any OCR system.** Not
backend selection, not PSM, not upscale factors, not preprocessing variants,
not thresholds. This is the repository owner's condition on the corpus being
here, it is absolute, and it does not lapse. The line is **scoring versus
choosing**: one run with an already-chosen configuration is the corpus's
whole purpose and works normally; a sweep that picks a parameter from these
images is refused by `redactor.datasets.refuse_if_tuning()`, which
`benchmark_ocr.py` calls before its first configuration.

Do not route around the guard — not by copying the images elsewhere, not by
clearing `held_out` in `_meta`, not by pointing a sweep at a subdirectory.
The reason it is code and not a comment is that this failure leaves no
trace: sweep configurations over a held-out corpus and the resulting number
looks exactly like the measurement it was before — same images, same
annotations, same scorer — so no diff and no score shows that a test set
became a training set. It is not hypothetical. While `test_holdout_guard.py`
was being verified against a deliberately disabled flag, `benchmark_ocr.py`
started redacting the corpus under six Tesseract configurations and had to
be killed; that is how it would happen in practice, as a default `--input`
nobody changed. Add the guard call to any *new* script that chooses a
parameter from a score.

**The holdout scored-count in `benchmarks/history.jsonl` is the number to
watch, not the recall.** Every scoring is recorded, held-out included, and
the report states how many times the corpus has been scored and whether the
current commit has scored it before. Nothing enforces this one: a person
reading the trend and keeping the changes that move it up is hill-climbing
on the test set, and no guard can see that happening. If the count is
climbing, the corpus has become a target regardless of intent. Decide with
`cheques/`, IndiaPII-Bench or maskara; come back here once, afterwards.

Holding it out does **not** make it independent evidence — the owner
generated it, so it shares `documents/`'s ceiling status. What it gives is a
number nothing was fitted to. Evidence for a change still comes from
`cheques/`, IndiaPII-Bench or maskara.

**Do not develop or test against a corpus this project generated.** Two —
`pack/` and `generated/` — were deleted in September 2026 for exactly that
reason: the recognizers and the test data had the same author, so they
agreed with each other and not with reality. `documents/` stays, but it is
familiar material and its 95.8% is a ceiling, not a measurement. Evidence
for a change must come from data nobody here produced: the cheque images,
IndiaPII-Bench, or maskara.

`runs/` and `input_annotations.json` stay gitignored — those describe
whatever a *user* fed the tool, which is not synthetic and not ours.

## Environment

Python 3.12 venv at `venv/` (not 3.13+ — no spaCy/Presidio wheels).
Tesseract and zbar via Homebrew. `en_core_web_lg`, the YuNet face model
and the WeChat QR models are downloaded by `setup.sh`, not pip.
`ANTHROPIC_API_KEY` lives in `.env`, which is gitignored.

## Traps — read before changing detection

**Threshold 0.5 is a trap; the default here is 0.4.** Presidio's context
boost is +0.35 over a 0.1 base pattern, so context-boosted weak matches
land at exactly **0.45**. A real PAN card's number was left visible at 0.5
and redacted at 0.4. Don't "restore" 0.5 for consistency with
kaapi-guardrails — that reintroduces a known leak.

**Aadhaar checksum failures are discarded, not down-scored**, so one OCR
digit error leaves a real Aadhaar fully visible. Hence the OCR-tolerant
fallback, on by default. It deliberately has **no look-around guards** —
guards were tried and dropped real Aadhaars, because OCR flattens the page
and destroys field boundaries. `04_hospital_admission_report.png` carries
a deliberately checksum-invalid Aadhaar as the regression canary.

**Paddle has two landmines**, both of which *raised* detection counts
while *lowering* actual redaction: it detects lines rather than words (so
each word carries its whole line box), and `use_doc_orientation_classify`
/ `use_doc_unwarping` must stay **off**, since it otherwise reports boxes
in a rectified space ~40px from the image being redacted.

**Locate codes with `detect()`, never `detectAndDecode()`.** Decode-gated
APIs return no box for a code they cannot read — exactly the codes that
most need covering. This shipped once and was caught only because a
barcode count stayed at 0.

**Only published formats get a recognizer.** Seven were removed in
September 2026 — patient ID, PNR, policy number, medical registration,
land record, property registration, bank account. Every one encoded a
*shape* that this project invented while writing the test data it was then
scored against, and four never fired once across 67 pages. The bar now is:
**cite the specification**. `IN_IFSC` clears it (RBI, 11 chars, mandatory
`0` at position five); `IN_DRIVING_LICENCE` only half clears it (a
convention with sources disagreeing on RTO-code length) and is kept on
notice. Anything else is a label problem, not a pattern one — see
`labels.py`.

**Reading order is a detection lever, not cosmetics.** Presidio flattens
the OCR word list into one string, so row grouping decides whether
`4587 6321 9876` is even *adjacent* — and a 12-digit Aadhaar that is not
adjacent does not match, at any threshold. Row assignment therefore takes
the **nearest** row measured against a running mean, not the first row
within a seed word's band: a single high, short OCR noise token was able
to steal the last digit group from a tilted line and silently disable
`IN_AADHAAR` for two commits. `test_labels.py` pins the case with the real
coordinates. Re-score `documents/` **and** `cheques/` after touching this
file; upscale factor changes what Tesseract emits, so a change that looks
inert at 2x can break at 3x.

**Entity counts are a bad metric.** Both misses and false positives move
them. Two Paddle bugs looked like improvements by that measure. Score
leakage instead.

**A number changed in the docs without a `DECISIONS.md` entry is a number
with no evidence.** The clinical withdrawal count went 12 to 5 in README
and VALIDATION in the commit that fixed reading order, with no entry and no
mention in the commit message, so the decision log asserted 12 while the
code produced 5 for a day. The entry goes in the same commit as the figure.

**`vision_score.py` overwrites `vision_verdicts.json` with whatever it
scored this pass.** An API error mid-run yields a *shorter* file, not a
partial one, and `score_run.py` then quietly falls back to OCR verdicts for
the missing images. Check the item count before trusting a score.

**`--protect-clinical` removes boxes, which nothing else here does.** Two
invariants hold it safe and both are easy to break by accident:
`SUPPRESSIBLE_TYPES` in `redactor/clinical.py` is the whole set of box
types that can ever be withdrawn, and adding an identifier type to it
would make a clinical sentence a place to hide an Aadhaar; and suppression
runs **before** block merging, because merging first fuses a drug name
into a neighbouring real box and makes it unwithdrawable. `test_clinical.py`
pins both. Any failure to load leaves `clinical_regions` empty, which
withdraws nothing — the safe direction, and deliberately so.

**`MIN_SCORE = 0.5` in `clinical.py` is doing real work, not tidying.**
Below it the clinical model tags form vocabulary — `PAN`, `Aadhaar`,
`Passport` — as `DIAGNOSTIC_PROCEDURE` at 0.31-0.38. Lowering it
re-introduces 7 false-positive withdrawals on `documents/` alone.

**Evidence must come from data this project did not produce.** The
image-model generator, its value layer and the realism comparison tool
were all deleted in September 2026 along with the corpora they made. They
worked; the problem was that nothing they produced could count as
evidence, because the same hand wrote the generator, the recognizers and
the ground truth. If a change needs validating, it needs `datasets/cheques/`,
IndiaPII-Bench or maskara — and if none of those covers it, say so rather
than reaching for a corpus you can generate.

## Measurement — the thing this project keeps getting wrong

`score_run.py` asks whether each known PII item is still *legible* in the
output, not whether a box overlapped it. An item is `leaked` only when
readable in the output, `redacted` only when readable before and not
after, `unverifiable` otherwise.

**An OCR-based scorer is blind exactly where redaction fails.** Use
`vision_score.py`; it has found leaks that both OCR and a careful manual
pass missed. `annotate_inputs.py` audits the label set — it reports rather
than rewrites, because what counts as PII is a policy question for a
person, and human-owned labels stay independent of the model that grades
the output.

Rejected after testing, with evidence in `DECISIONS.md`: geometric box
matching instead of legibility (a box can be 85% covered and still leak),
per-region coverage from vision boxes (they are off by about a text row),
and a YOLO layout model (`ultralytics` is AGPL-3.0, the only copyleft
dependency this project would have).

## Conventions

- **Never abort the batch.** Every per-image failure is caught, logged
  with filename and stage, and skipped. This has repeatedly turned a
  crash into a clean diagnostic.
- **Verify before claiming.** Run it, read the output image, check the
  score. Six corrections to the headline all came from asserting ahead of
  the evidence.
- **Don't ship a metric that lies.** A confidently wrong number is worse
  than no number; per-region coverage was built, measured, and removed for
  exactly this reason.
- Console output uses `rich` throughout — match that style over `print()`.
- `test_labels.py` pins the label geometry on hand-built OCR dicts. Every
  case in it was written from a bug it caught, not from imagination — twice
  the same mistake, applying a positional limit to every word of a value
  instead of only to where the value starts, which silently truncated
  multi-word values. Run it after touching `labels.py`.
- `test_clinical.py` pins the suppression rule, not the clinical model. A
  test asserting the model scores `Metformin` at 0.83 would pin a model
  version; what is pinned instead is what the rule will and will not
  withdraw. Run it after touching `clinical.py`.
- `test_metadata_stripping.py` guards one thing: that redacted output carries no EXIF, GPS or embedded thumbnail.
  It was verified to fail when the protection is removed. Validation is
  otherwise by running the pipeline and scoring it.
- Stage files explicitly rather than `git add -A`; a broad add committed a
  `.DS_Store` once.

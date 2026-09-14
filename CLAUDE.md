# CLAUDE.md

Guidance for Claude Code when working in this repo.

## What this is

A local evaluation harness for Presidio's image redaction pipeline
(Tesseract OCR + Presidio AnalyzerEngine/spaCy + Presidio
ImageRedactorEngine). Entirely local, no cloud calls. Design spec:
`docs/superpowers/specs/2026-09-14-presidio-image-redactor-eval-design.md`.

## Layout

- `evaluate_redactor.py` — main CLI. `process_image()` is the
  per-image pipeline (open → analyze → redact → save), `main()` wires
  up argparse, logging, the progress bar, and the summary/report.
- `ocr_backends.py` — `build_ocr()` returns a Presidio `OCR` subclass.
  Paddle returns *line* boxes, so `_split_line_into_words()` divides
  them across words by character count; without that, one PII word
  blacks out its whole line.
- `visual_redaction.py` — faces (Haar), QR (`cv2.QRCodeDetector`) and
  1-D barcodes (`cv2.barcode.BarcodeDetector`). On by default;
  `--no-visual-pii` disables. **Always locate with `detect()`, never
  with `detectAndDecode()`** — the latter returns no boxes for codes it
  cannot read, which silently skips exactly the unreadable codes that
  most need blacking out. This bug was actually shipped once and caught
  only because the water-bill barcode count stayed 0. pyzbar (`--pyzbar`)
  and WeChat (`--wechat-qr`) are opt-in *supplements*, unioned with the
  stock detector, never substitutes — WeChat was measured at 0 codes vs
  the stock detector's 4 for exactly the decode-gating reason above.
  `PAD_RATIO` pads faces 30% because Haar boxes clip chin/hair.

**Before changing any default, read "Why the defaults are what they are"
in README.md.** Every row there records a measured result, several of
them counterintuitive (0.4 not 0.5; tesseract not paddle; no regex
guards; WeChat rejected). Changing one without re-running the sample set
is how the PII leaks come back.
- `runs/<name>/` — each run writes `config.json` (inputs),
  `summary.json` (config + results), `run.log`, `images/`. Gitignored:
  may contain real PII.
- `generate_test_images.py` — Pillow-based synthetic document
  generator. `DOCUMENTS` is a list of dicts fed to `render_document()`;
  add new synthetic test docs by appending to that list, not by
  writing new rendering code.
- `setup.sh` — idempotent one-time setup (brew installs, venv, pip
  install, spaCy model download). Re-running it is safe.
- `input_images/`, `output_images/` — git-ignored (may hold real PII
  once a user drops in their own images). Never commit files from
  these folders, even to "add sample output" — treat as untrusted/
  sensitive data always.

## Environment

- Python 3.12 venv at `venv/` (not 3.14 — spaCy/Presidio didn't have
  3.14 wheels as of 2026-09). Activate with `source venv/bin/activate`.
- Tesseract binary installed via Homebrew, not pip.
- spaCy model `en_core_web_lg` downloaded separately via
  `python -m spacy download en_core_web_lg` (large, ~400MB — not a pip
  dependency in requirements.txt).

## Indian entities — read before changing detection

Presidio ships India recognizers but registers **none** by default;
`build_engines()` adds all six (`INDIA_RECOGNIZER_NAMES`). Key facts,
all verified empirically — see README "Findings from evaluation" for
detail:

- Aadhaar/PAN/Voter are **regex + checksum**, not NER. Swapping the
  spaCy model does nothing for them. Don't accept "use a better NER
  model for Aadhaar" as a premise. `en_core_web_lg` scored 19/20 on
  Indian names and matches kaapi-guardrails' production validator —
  keep it unless there's evidence-backed reason to change.
- `InAadhaarRecognizer` drops (not down-scores) checksum failures, so
  OCR digit errors silently un-redact real Aadhaars. Hence the
  `build_aadhaar_ocr_fallback_recognizer()` fallback, on by default,
  disabled with `--strict-aadhaar`.
- That fallback intentionally has **no look-around guards**. Guards
  were tried and broke real detections, because OCR flattens the page
  and destroys field boundaries. Don't "tighten" the regex without
  re-running the test set — specifically
  `04_hospital_admission_report.png`, whose Aadhaar is deliberately
  checksum-invalid and is the regression canary for this.
- Test-image Aadhaar numbers must be Verhoeff-valid (except 04's
  deliberate one). Generate a valid one by brute-forcing the last
  digit against `InAadhaarRecognizer().validate_result()`.

## Threshold 0.5 is a trap — default here is 0.4

Presidio's context boost is +0.35 and several India recognizers use a
0.1 base pattern, so context-boosted weak matches land at exactly
**0.45** — just under the conventional 0.5. Verified: a real PAN card's
number was left visible at 0.5 and redacted at 0.4; same for a voter ID.

`--threshold` therefore defaults to **0.4**, a deliberate divergence
from kaapi-guardrails' documented 0.5. Don't "restore" it to 0.5 for
consistency — that reintroduces a known PII leak. Pass 0.5 explicitly
only to reproduce that validator's current behaviour for comparison.

## Upscaling

`--upscale auto` scales narrow images toward 600px wide for the OCR pass
only; the saved image is resized back to its original dimensions. This
is load-bearing, not a nicety — a real job-application photo went from
0 detections at native size to 7 at 2x. It also *raises* precision by
cutting OCR-garbage false-positive PERSON hits. Don't disable it as a
"simplification". Note entity **counts** are a poor quality metric here:
both misses and false positives move them, so inspect entity *types* and
the output images.

## Aligning with kaapi-guardrails

Sibling project `ProjectTech4DevAI/kaapi-guardrails` has a
`pii_remover` validator on the same Presidio + `en_core_web_lg` stack.
`--threshold` / `--entities` mirror its `threshold` / `entity_types`
config deliberately — keep them compatible so this harness can
evaluate that validator's real settings.

## Conventions

- Every per-image failure must be caught, logged with filename +
  stage, and must not abort the batch — this was an explicit
  requirement, not an accident. Preserve that behavior in any change
  to `process_image()`.
- Console UX uses `rich` throughout (progress bars, colorized
  logging, summary tables/panels) — keep new CLI output consistent
  with that style rather than plain `print()`.
- No pytest suite by design (see spec's "Out of Scope") — validation
  is done by running `generate_test_images.py` +
  `evaluate_redactor.py` and checking `redaction_report.json` /
  output images. If this becomes a longer-lived tool, revisit that
  decision rather than silently adding ad hoc tests.

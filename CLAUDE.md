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

## Known limitation

Presidio's default recognizers don't cover Aadhaar/PAN number formats
(they're US/UK-pattern-based) — see README's "Known limitation"
section before extending this. If asked to close that gap, the fix is
custom `PatternRecognizer`s registered on the `AnalyzerEngine` inside
`build_engines()` in `evaluate_redactor.py`, not a new pipeline stage.

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

#!/usr/bin/env python3
"""Generate photoreal synthetic Indian documents with an OpenAI image model,
then build ground truth by reading back what was *actually* rendered.

Why this exists alongside the two Pillow generators. `generate_test_images.py`
and the pack generator draw flat label/value pages: crisp text, no glare, no
perspective. Real documents arrive photographed, and that is where this
redactor is weakest — every one of the five known leaks is on such an image.
An image model produces that difficulty on demand.

**The catch, and the whole design.** An image model will not render the
values you asked for faithfully — it drops characters and invents digits —
and it cannot tell you where on the page it put them. So ground truth
cannot be derived from the prompt. This project has already deleted one
metric that was built on assumed ground truth.

So: values first, verify after.

1. `redactor.synth` draws the field values. These are what we *asked* for.
2. The image model renders a photographed-looking document containing them.
3. Claude reads the result back and reports, for each value, whether it is
   present and **what the page actually says**.
4. The annotation records the rendered text, not the requested text. A
   mangled `4521 8734 9O15` is the truth for that image, and a fair OCR
   target. Values that did not survive at all are dropped with a note.

The verifier is deliberately a different vendor from the generator: a model
grading its own output can confirm a value it hallucinated.

No bounding boxes. Vision-derived boxes were measured here and found to sit
about a text row off, which is why the coverage metric was removed. This
corpus scores by legibility, like `documents/`.

Usage:
    python generate_openai_documents.py --count 50
    python generate_openai_documents.py --count 8 --dry-run   # no spend
    python generate_openai_documents.py --count 50 --no-verify
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from redactor import datasets, synth, vision

CORPUS = "generated"
DEFAULT_SIZE = "1024x1536"

# Pinned on purpose. A corpus whose generator silently upgrades between
# runs is a corpus whose difficulty silently changes, and the scores across
# it stop being comparable. `--model auto` picks the newest available;
# whatever is resolved is recorded in the corpus `_meta`.
DEFAULT_IMAGE_MODEL = "gpt-image-2"

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
)
log = logging.getLogger("generate_openai")

# Indicative only — the API is the authority on what a call costs. Used to
# show a total before spending anything, never to bill against.
COST_HINT = {"low": 0.02, "medium": 0.07, "high": 0.19}


# --- OpenAI -----------------------------------------------------------------

def build_openai_client():
    vision.load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Put it in .env as:\n"
            "  OPENAI_API_KEY=sk-...\n"
            "(.env is gitignored.)"
        )
    try:
        import openai
    except ImportError as exc:
        raise RuntimeError("pip install openai") from exc
    return openai.OpenAI()


def resolve_model(client, requested: str | None) -> str:
    """Check the requested model exists, or pick the newest for `auto`.

    Model names move faster than this file does, so the list comes from the
    API rather than a constant here: if the caller names a model the key
    cannot see, say what it can.
    """
    if requested == "auto":
        requested = None
    try:
        available = sorted(m.id for m in client.models.list() if "image" in m.id)
    except Exception as exc:  # network, auth, an API that changed shape
        if requested:
            log.warning("Could not list models (%s) — trying %r anyway.", exc, requested)
            return requested
        raise RuntimeError(f"Could not list models to pick one: {exc}") from exc

    if requested:
        if requested in available:
            return requested
        raise RuntimeError(
            f"Model {requested!r} is not available to this key.\n"
            f"Image models it can see: {', '.join(available) or 'none'}"
        )

    def version(name: str) -> tuple:
        # Highest gpt-image-N.N wins; a full model beats a -mini; an
        # undated id beats its dated snapshot, which is the same model.
        match = re.search(r"gpt-image-(\d+(?:\.\d+)*)", name)
        parts = tuple(int(p) for p in match.group(1).split(".")) if match else (-1,)
        return (parts, 0 if "mini" in name else 1, 0 if re.search(r"-\d{4}-", name) else 1)

    ranked = sorted((m for m in available if m.startswith("gpt-image")),
                    key=version, reverse=True)
    if not ranked:
        raise RuntimeError(
            f"No gpt-image model available to this key. Saw: {', '.join(available)}"
        )
    return ranked[0]


PROMPT_TEMPLATE = """A photograph of a single-page Indian {doc_label}, \
shot from slightly above on a desk. The whole page is in frame.

Render this document with exactly these printed fields, spelled exactly \
as given:

{fields}

Layout: a printed government/institutional form or card — header band with \
the issuing body's name, then the fields as label-and-value rows in a clean \
sans-serif face, ruled lines or a light form grid, a small official-looking \
seal or emblem. {portrait}{signature}

Make it look photographed rather than scanned: slight perspective, a soft \
shadow across one corner, mild uneven lighting, faint paper texture, very \
slight blur away from the centre. Keep every value legible to a human \
reader. No watermark, no "sample" or "specimen" stamp across the text.

The document is fictitious and the details are invented."""

PORTRAIT_NOTE = (
    "In the portrait area, a plain grey silhouette placeholder where a "
    "photo would go — no real or generated human face. "
)
SIGNATURE_NOTE = "A handwritten ink signature above a 'Signature' line. "

DOC_LABELS = {
    "aadhaar": "Aadhaar-style national identity card",
    "pan": "PAN (income tax) card",
    "driving_license": "driving licence card",
    "bank_statement": "bank account statement",
    "medical_report": "hospital outpatient medical report",
    "land_registration": "sub-registrar land registration extract",
    "police_report": "police First Information Report",
    "application_form": "government scheme application form",
}


def build_prompt(doc: synth.Document, faces: str) -> str:
    fields = "\n".join(f"  {f.label}: {f.value}" for f in doc.fields)
    portrait = ""
    if doc.has_portrait:
        portrait = (
            PORTRAIT_NOTE if faces == "placeholder"
            else "In the portrait area, a passport-style photo of a person. "
        )
    return PROMPT_TEMPLATE.format(
        doc_label=DOC_LABELS[doc.doc_type],
        fields=fields,
        portrait=portrait,
        signature=SIGNATURE_NOTE,
    )


def save_image(raw: bytes, path: Path, image_format: str) -> Path:
    """Write the model's bytes, optionally re-encoding to JPEG.

    A photoreal 1024x1536 PNG is ~2.4MB; the same page at JPEG q95 is a
    fraction of that, and a corpus of 50 has to live in the repo to be
    worth anything. Lossy re-encoding is safe *here* and nowhere else in
    this project: nothing has been measured on these pixels yet, so the
    stored file simply is the corpus. It is also what the tool meets in
    practice — a photographed document arrives as a JPEG.
    """
    if image_format == "png":
        path.write_bytes(raw)
        return path

    import io

    from PIL import Image

    jpeg_path = path.with_suffix(".jpg")
    Image.open(io.BytesIO(raw)).convert("RGB").save(
        jpeg_path, format="JPEG", quality=95, subsampling=0, optimize=True
    )
    return jpeg_path


def generate_image(client, model: str, prompt: str, size: str, quality: str) -> bytes:
    kwargs = {"model": model, "prompt": prompt, "size": size, "n": 1}
    if quality:
        kwargs["quality"] = quality
    result = client.images.generate(**kwargs)
    datum = result.data[0]
    if getattr(datum, "b64_json", None):
        return base64.b64decode(datum.b64_json)
    # Some models return a URL instead of inline bytes.
    import urllib.request

    with urllib.request.urlopen(datum.url) as response:
        return response.read()


# --- verification ------------------------------------------------------------

VERIFY_PROMPT = """This is a synthetic document image generated for testing \
a PII redaction tool. Every detail in it is fabricated.

I asked the image generator to print the values listed below, each with a \
KEY and the label it should appear under. Image models render text \
unreliably, so I need to know what the page *actually* says.

For each requested value, report it back under its KEY, exactly as given:

- "exact"   - the page shows this value character for character
- "altered" - the page shows something recognisably this field, but the \
text differs (a dropped digit, a changed letter, different spacing). Put \
what the page actually reads in `rendered`.
- "missing" - this field does not appear on the page at all

Transcribe `rendered` exactly as printed, including any mangling. Do not \
correct it toward what I asked for — the mangled text is the answer I need. \
Read only what is visible; if a value is too blurred to read, call it \
"missing".

Also count what visual features the page shows:

- `face`: **photographic human faces only.** A grey silhouette, an outline, \
or an empty photo box is NOT a face — count 0. This matters: a face \
detector cannot find a silhouette, so counting one here would record a \
failure that no tool could ever pass.
- `qr_code`, `barcode`: machine-readable codes, however small or decorative
- `signature`: a handwritten signature

Requested values:
{fields}"""

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["exact", "altered", "missing"],
                    },
                    "rendered": {"type": "string"},
                },
                "required": ["key", "status", "rendered"],
                "additionalProperties": False,
            },
        },
        "visual": {
            "type": "object",
            "properties": {
                "face": {"type": "integer"},
                "qr_code": {"type": "integer"},
                "barcode": {"type": "integer"},
                "signature": {"type": "integer"},
            },
            "required": ["face", "qr_code", "barcode", "signature"],
            "additionalProperties": False,
        },
    },
    "required": ["fields", "visual"],
    "additionalProperties": False,
}


def verify_image(client, model: str, path: Path, doc: synth.Document) -> dict:
    listed = "\n".join(f"  {f.category} (printed as “{f.label}”): {f.value}"
                       for f in doc.fields)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": VERIFY_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    vision.encode_image(path),
                    {"type": "text", "text": VERIFY_PROMPT.format(fields=listed)},
                ],
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Refused: {getattr(response, 'stop_details', None)}")
    return json.loads(next(b.text for b in response.content if b.type == "text"))


def document_from_entry(name: str, entry: dict) -> synth.Document:
    """Rebuild a Document from an existing annotation, for re-verification.

    Images cost money and verification is the step that fails, so a failed
    or skipped read-back must be repeatable without paying to redraw the
    page. `requested` holds the original value where the renderer altered
    it; that is what the verifier should be asked about.
    """
    doc_type = name.split("_", 1)[1].rsplit(".", 1)[0]
    doc = synth.Document(doc_type, "",
                         has_portrait=doc_type in {"aadhaar", "pan", "driving_license"})
    for item in entry.get("pii", []):
        doc.add(FIELD_LABELS.get(item["field"], item["field"]),
                item.get("requested", item["text"]), item["field"])
    return doc


# category -> the label the generator printed on the page. Only used when
# rebuilding a Document from an annotation, where the label is not stored.
FIELD_LABELS = {
    "PERSON_NAME": "Name",
    "FATHER_OR_SPOUSE_NAME": "Father's Name",
    "DOCTOR_NAME": "Attending Doctor",
    "DOB": "Date of Birth",
    "ADDRESS": "Address",
    "PHONE_NUMBER": "Phone",
    "EMAIL": "Email",
    "AADHAAR_NUMBER": "Aadhaar Number",
    "PAN_NUMBER": "PAN",
    "BANK_ACCOUNT_NUMBER": "Account Number",
    "IFSC_CODE": "IFSC Code",
    "DRIVING_LICENSE_NUMBER": "DL Number",
    "MEDICAL_RECORD_NUMBER": "Medical Record No.",
    "LAND_REGISTRATION_NUMBER": "Registration No.",
    "SURVEY_NUMBER": "Survey Number",
    "FIR_NUMBER": "FIR Number",
    "DIAGNOSIS": "Diagnosis",
}


def annotate(doc: synth.Document, verdict: dict | None) -> dict:
    """Build the corpus entry. Without a verdict, record what we asked for."""
    if verdict is None:
        pii = [
            {
                "field": f.category,
                "expected_type": synth.PII_CATEGORIES[f.category][0],
                "tier": synth.PII_CATEGORIES[f.category][1],
                "text": f.value,
            }
            for f in doc.pii()
        ]
        return {
            "pii": pii,
            "visual": {"face": 0, "qr_code": 0, "barcode": 0},
            "notes": f"{doc.doc_type}; UNVERIFIED — rendered text not checked "
                     f"against the request, values may not match the page",
        }

    by_key = {f["key"]: f for f in verdict.get("fields", [])}
    pii, dropped, altered = [], [], 0
    for f in doc.pii():
        seen = by_key.get(f.category)
        status = seen["status"] if seen else "missing"
        if status == "missing":
            dropped.append(f.category)
            continue
        text = f.value if status == "exact" else (seen["rendered"] or "").strip()
        if not text:
            dropped.append(f.category)
            continue
        altered += status == "altered"
        entity, tier = synth.PII_CATEGORIES[f.category]
        item = {
            "field": f.category,
            "expected_type": entity,
            "tier": tier,
            "text": text,
        }
        if status == "altered":
            item["requested"] = f.value
        pii.append(item)

    seen_visual = verdict.get("visual", {})
    notes = [doc.doc_type]
    if altered:
        notes.append(f"{altered} value(s) rendered differently from the request")
    if dropped:
        notes.append(f"not rendered: {', '.join(dropped)}")
    if seen_visual.get("signature"):
        notes.append("signature present")
    return {
        "pii": pii,
        "visual": {k: int(seen_visual.get(k, 0))
                   for k in ("face", "qr_code", "barcode")},
        "notes": "; ".join(notes),
    }


# --- main --------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--model", default=DEFAULT_IMAGE_MODEL,
                        help="OpenAI image model, or 'auto' for the newest "
                             "the key can see (default: %(default)s)")
    parser.add_argument("--size", default=DEFAULT_SIZE)
    parser.add_argument("--quality", default="medium",
                        choices=["low", "medium", "high"])
    parser.add_argument("--format", default="jpeg", choices=["jpeg", "png"],
                        help="stored image format. JPEG q95 by default: a "
                             "photoreal PNG is ~2.4MB, the corpus has to fit "
                             "in the repo, and real photographed documents "
                             "arrive as JPEG anyway (default: %(default)s)")
    parser.add_argument("--faces", default="placeholder",
                        choices=["placeholder", "generated"],
                        help="portrait area: grey silhouette, or a generated face")
    parser.add_argument("--types", nargs="*", default=None,
                        choices=list(synth.DOC_TYPES),
                        help="restrict to these document types")
    parser.add_argument("--corpus", default=CORPUS)
    parser.add_argument("--verify-model", default=vision.DEFAULT_MODEL)
    parser.add_argument("--no-verify", action="store_true",
                        help="skip read-back; annotations record the REQUESTED text")
    parser.add_argument("--verify-existing", action="store_true",
                        help="read back images already on disk; generates nothing")
    parser.add_argument("--force", action="store_true",
                        help="with --verify-existing, re-verify every entry, "
                             "not only the ones marked UNVERIFIED")
    parser.add_argument("--dry-run", action="store_true",
                        help="print one prompt and the cost estimate, spend nothing")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--yes", action="store_true", help="skip the cost prompt")
    args = parser.parse_args()

    if args.seed is not None:
        import random

        random.seed(args.seed)

    if args.verify_existing:
        verify_existing(args)
        return

    console.rule(f"[bold blue]Generating {args.count} synthetic documents")
    docs = synth.round_robin(args.count, args.types)

    if args.dry_run:
        console.print(build_prompt(docs[0], args.faces))
        console.rule()
        console.print(
            f"[yellow]Dry run.[/yellow] {args.count} images at {args.quality} "
            f"quality ≈ ${args.count * COST_HINT[args.quality]:.2f} to generate"
            + ("" if args.no_verify else ", plus one Claude vision call each.")
        )
        return

    try:
        client = build_openai_client()
        model = resolve_model(client, args.model)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    verifier = None if args.no_verify else vision.build_client()

    estimate = args.count * COST_HINT[args.quality]
    console.print(
        f"Model: [bold]{model}[/bold]  size {args.size}  quality {args.quality}\n"
        f"Estimated generation cost: [bold]~${estimate:.2f}[/bold] "
        f"for {args.count} images"
        + ("" if args.no_verify else f", plus {args.count} Claude vision calls")
    )
    if not args.yes:
        if not console.input("Proceed? [y/N] ").strip().lower().startswith("y"):
            console.print("[yellow]Nothing generated.[/yellow]")
            return

    base = datasets.ROOT / args.corpus
    images = base / "images"
    images.mkdir(parents=True, exist_ok=True)

    existing = {}
    ann_path = base / "annotations.json"
    if ann_path.exists():
        existing = {k: v for k, v in json.loads(ann_path.read_text()).items()
                    if k != "_meta"}

    annotations = dict(existing)
    failures: list[tuple[str, str]] = []
    unverified = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Generating", total=len(docs))
        for index, doc in enumerate(docs, start=1):
            stem = f"{index:02d}_{doc.doc_type}"
            name = f"{stem}.{'png' if args.format == 'png' else 'jpg'}"
            path = images / f"{stem}.png"
            try:
                # Resumable: never pay twice for the same image. Check both
                # extensions, so a corpus started as PNG is not redrawn.
                done = next((n for n in (f"{stem}.png", f"{stem}.jpg")
                             if (images / n).exists() and n in annotations), None)
                if done:
                    continue  # `finally` advances the bar; doing it here too
                              # counted skipped images twice (52/50)

                progress.update(task, description=f"Generating {doc.doc_type}")
                raw = generate_image(
                    client, model, build_prompt(doc, args.faces),
                    args.size, args.quality,
                )
                path = save_image(raw, path, args.format)
                name = path.name

                verdict = None
                if verifier is not None:
                    progress.update(task, description=f"Verifying {doc.doc_type}")
                    try:
                        verdict = verify_image(verifier, args.verify_model, path, doc)
                    except Exception as exc:
                        # The image is real and paid for; keep it, flag the entry.
                        unverified += 1
                        log.warning("Verification failed for %s: %s", name, exc)

                annotations[name] = annotate(doc, verdict)
            except Exception as exc:
                failures.append((name, str(exc)))
                log.exception("Failed on %s", name)
            finally:
                progress.advance(task)
                # Write after every image: a crash at image 47 keeps 46.
                datasets.save(args.corpus, annotations, corpus_meta(model, args))

    report(annotations, failures, unverified, base, args)


def verify_existing(args) -> None:
    """Read back images already on disk. Costs vision calls, not image calls."""
    base = datasets.ROOT / args.corpus
    ann_path = base / "annotations.json"
    if not ann_path.exists():
        console.print(f"[red]No corpus at {base}[/red]")
        raise SystemExit(1)

    raw = json.loads(ann_path.read_text())
    meta = raw.pop("_meta", {})
    targets = [
        (name, entry) for name, entry in raw.items()
        if (base / "images" / name).exists()
        and (args.force or "UNVERIFIED" in entry.get("notes", ""))
    ]
    if not targets:
        console.print("[green]Nothing to verify — every entry is already "
                      "read back from its image.[/green]")
        return

    console.rule(f"[bold blue]Verifying {len(targets)} existing images")
    client = vision.build_client()
    failures = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Verifying", total=len(targets))
        for name, entry in targets:
            try:
                doc = document_from_entry(name, entry)
                verdict = verify_image(client, args.verify_model,
                                       base / "images" / name, doc)
                raw[name] = annotate(doc, verdict)
            except Exception as exc:
                failures.append((name, str(exc)))
                log.exception("Verification failed for %s", name)
            finally:
                progress.advance(task)
                datasets.save(args.corpus, raw, meta)

    meta["verified_by"] = args.verify_model
    datasets.save(args.corpus, raw, meta)
    report(raw, failures, 0, base, args)


def corpus_meta(model: str, args) -> dict:
    return {
        "description": (
            "Photoreal synthetic Indian documents across 8 types, generated by "
            "an OpenAI image model from values drawn by redactor/synth.py."
        ),
        "source": f"generate_openai_documents.py — {model}, {args.size}, {args.quality}",
        "licence": "fully synthetic; no real person, document, account or property",
        "annotation": (
            "text (legibility scoring). The text recorded is what the model "
            "ACTUALLY rendered, read back by Claude — not what was requested; "
            "where the two differ the request is kept under `requested`. No "
            "boxes: vision-derived boxes were measured here at about a text "
            "row off and the metric built on them was removed."
        ),
        "verified_by": "skipped (--no-verify)" if args.no_verify else args.verify_model,
        "faces": args.faces,
    }


def report(annotations, failures, unverified, base, args) -> None:
    table = Table(title="Generated corpus")
    table.add_column("document type", style="cyan")
    table.add_column("images", justify="right")
    table.add_column("PII items", justify="right")
    table.add_column("altered by renderer", justify="right")

    per_type: dict[str, list[int]] = {}
    for name, entry in annotations.items():
        doc_type = name.split("_", 1)[1].rsplit(".", 1)[0]
        row = per_type.setdefault(doc_type, [0, 0, 0])
        row[0] += 1
        row[1] += len(entry["pii"])
        row[2] += sum("requested" in item for item in entry["pii"])
    for doc_type, (n, items, altered) in sorted(per_type.items()):
        table.add_row(doc_type, str(n), str(items), str(altered))
    console.print(table)

    total_items = sum(len(e["pii"]) for e in annotations.values())
    console.print(
        f"\n[green]{len(annotations)} images, {total_items} PII items[/green] "
        f"-> {base}/"
    )
    if unverified:
        console.print(
            f"[yellow]{unverified} image(s) could not be verified — their "
            f"annotations record the requested text and may not match the "
            f"page.[/yellow]"
        )
    if failures:
        console.print(f"[red]{len(failures)} failed:[/red]")
        for name, error in failures:
            console.print(f"  {name}: {error}")
    console.print(
        f"\nNext: [bold]python evaluate_redactor.py --input {base}/images "
        f"--run-name {args.corpus}[/bold]"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted — images already written are kept.[/yellow]")
        sys.exit(130)

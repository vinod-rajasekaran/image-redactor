#!/usr/bin/env python3
"""Annotate the *input* images with Claude vision, and audit ground truth.

Two jobs, neither of which replaces `score_run.py`.

**Auditing ground truth.** The label set has been the largest single
source of error in this project — it swung 96 -> 130 -> 77 items across
three revisions, and each swing moved the headline recall by roughly ten
points. This asks Claude what personal data is on each *input* page and
diffs that against `ground_truth.json`, surfacing anything never labelled.
It deliberately **reports** rather than rewrites: what counts as PII is a
policy question, and the answer belongs to a person. Keeping the labels
human-owned also keeps them independent of the model that grades the
output — a scorer sharing the tool's blind spots cannot find the tool's
failures, and that applies to the labels too.

**What this deliberately does NOT do: per-region coverage.** The obvious
next step — measure what fraction of each annotated box the redactor
actually covered, and flag anything under 100% as a likely leak — was
built and then removed, because the boxes are not accurate enough to
support it. Rendered over the source image, the model's boxes are
inconsistently off by about one text row: on the sample Aadhaar card the
`person_name` box sat on the date of birth and the `date_of_birth` box
sat on "Male", while three others were correct. Coverage computed from
those boxes reported 0% for a field that is plainly blacked out.

Vision models are reliable about *what* is on a page and unreliable about
precisely *where*. A metric that produces confident wrong numbers is worse
than no metric — that has been this project's most expensive lesson — so
the box coordinates are recorded for human inspection and nothing is
computed from them.

Usage:
    python annotate_inputs.py           # annotate, then audit the labels
    python annotate_inputs.py --reuse   # re-audit without calling the API
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from redactor.vision import DEFAULT_MODEL, build_client, encode_image

console = Console()
OUTPUT = Path("input_annotations.json")

# Boxes come back in a 0-1000 normalised frame so the model never has to
# know the pixel dimensions of the image it is looking at.
BOX_SCALE = 1000

PROMPT = """List every piece of personal data on this document that identifies a
specific person.

Include: names (of anyone — the subject, a parent, a doctor), identification
numbers (Aadhaar, PAN, voter ID, passport, driving licence, patient ID, account
number, PNR, policy number), phone numbers, email addresses, postal addresses,
dates of birth, photographs of a person, and QR codes or barcodes.

Exclude: monetary amounts and balances, transaction descriptions, institution
names and their addresses, job titles, gender on its own, standalone ages, and
dates that are not a date of birth. These identify nobody.

For each item give:
- text: the exact text as printed, or "PHOTO" / "QR_CODE" / "BARCODE"
- kind: a short lower_snake_case label, e.g. person_name, aadhaar_number
- box: [x0, y0, x1, y1] in 0-1000 normalised coordinates, tight around the value

A value wrapped across lines is ONE item with a box covering all its lines."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string"},
                    # No minItems/maxItems: structured outputs reject any
                    # minItems above 1. Length is checked in code instead.
                    "box": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["text", "kind", "box"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def annotate_image(client, model: str, path: Path) -> list[dict]:
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [encode_image(path), {"type": "text", "text": PROMPT}],
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Refused: {getattr(response, 'stop_details', None)}")
    text = next(b.text for b in response.content if b.type == "text")
    return [i for i in json.loads(text)["items"] if len(i.get("box", [])) == 4]


def to_pixels(box: list[float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    w, h = size
    x0, y0, x1, y1 = box
    return (
        max(0, min(int(x0 / BOX_SCALE * w), w)),
        max(0, min(int(y0 / BOX_SCALE * h), h)),
        max(0, min(int(x1 / BOX_SCALE * w), w)),
        max(0, min(int(y1 / BOX_SCALE * h), h)),
    )


def similar(a: str, b: str) -> bool:
    """Loose text match, so punctuation and case differences don't split items."""
    norm = lambda s: "".join(c for c in s.lower() if c.isalnum())
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="input_images")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Reuse input_annotations.json instead of calling the API again",
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    from redactor import datasets

    corpus = datasets.load(os.environ.get("REDACTOR_CORPUS", "documents"))
    truth = corpus.annotations
    names = sorted(p.name for p in input_dir.glob("*.png"))
    if args.limit:
        names = names[: args.limit]

    if args.reuse and OUTPUT.exists():
        annotations = json.loads(OUTPUT.read_text())
        console.print(f"[dim]Reusing {OUTPUT}[/dim]")
    else:
        client = build_client()
        annotations = {}
        for name in names:
            try:
                annotations[name] = annotate_image(
                    client, args.model, input_dir / name
                )
            except Exception as exc:
                console.print(f"[red]{name}: {exc}[/red]")
                continue
            console.print(f"{name:34s} {len(annotations[name])} items")
        if not annotations:
            console.print("[red]Nothing was annotated — not writing a file.[/red]")
            sys.exit(1)
        OUTPUT.write_text(json.dumps(annotations, indent=2, ensure_ascii=False))
        console.print(f"[green]Written to[/green] {OUTPUT}\n")

    # ---- audit: what vision found that ground truth does not list ----
    audit = Table(title="Ground-truth audit — found by vision, not in ground_truth.json")
    audit.add_column("image", style="cyan")
    audit.add_column("kind")
    audit.add_column("text")
    unlabelled = 0
    for name in names:
        labelled = [p["text"] for p in truth.get(name, {}).get("pii", [])]
        for item in annotations.get(name, []):
            if item["text"] in ("PHOTO", "QR_CODE", "BARCODE"):
                continue  # tracked separately as visual regions
            if not any(similar(item["text"], t) for t in labelled):
                audit.add_row(name, item["kind"], item["text"][:46])
                unlabelled += 1
    console.print(audit)

    missing = Table(title="In ground_truth.json, not found by vision")
    missing.add_column("image", style="cyan")
    missing.add_column("text")
    unseen = 0
    for name in names:
        found = [i["text"] for i in annotations.get(name, [])]
        for p in truth.get(name, {}).get("pii", []):
            if not any(similar(p["text"], f) for f in found):
                missing.add_row(name, p["text"][:46])
                unseen += 1
    console.print(missing)
    console.print(
        f"[yellow]{unlabelled} unlabelled[/yellow] · [yellow]{unseen} unseen[/yellow] — "
        "both are prompts for a human decision, not errors"
    )


if __name__ == "__main__":
    main()

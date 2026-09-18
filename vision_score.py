#!/usr/bin/env python3
"""Score a run's redacted images with Claude vision instead of OCR.

The OCR scorer can only see what its OCR sees, and on exactly the
low-contrast photographs where redaction fails it reads almost nothing.
It has been wrong in both directions because of that: reporting plainly
visible PII as "unverifiable", and reporting it as "redacted". On one
laptop-screen form it recovered the words "personal" and "details" from a
page whose address is legible at a glance.

This asks Claude to look at each redacted output image and say, for every
PII value the ground truth says is on that page, whether it is still
readable. Output goes to `runs/<run>/vision_verdicts.json`, which
`score_run.py` picks up automatically and prefers over its own verdicts.

Setup:
    echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env
    pip install anthropic

Usage:
    python vision_score.py runs/<run-name> [--model claude-opus-5]

Costs real money — one vision request per image with PII in it.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import os
import sys
from pathlib import Path

from rich.console import Console

from redactor.vision import DEFAULT_MODEL, build_client, encode_image

console = Console()

PROMPT = """You are auditing a redacted document image for a privacy tool.

The unredacted original contained the personal data values listed below.
Redaction boxes (solid, blurred or pixelated) should have made them
unreadable.

For each value, decide whether it is STILL READABLE in this image:

- "leaked"   - you can read the value, or enough of it to recover the
               whole. A legible given name counts as leaked.
- "redacted" - it is covered, blurred, pixelated, or only a fragment too
               short to identify anyone remains (a postcode tail, the last
               letters of a surname).

Judge only what you can actually see in this image. Do not assume a value
is redacted because it ought to be, and do not guess at text hidden under
a box. If a value is genuinely ambiguous, answer "leaked" — under-reporting
a leak is the more dangerous error in a privacy audit.

Values to check:
{items}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["leaked", "redacted"]},
                    "note": {"type": "string"},
                },
                "required": ["value", "verdict", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def score_image(client, model: str, image_path: Path, items: list[str]) -> dict:
    listed = "\n".join(f"- {v}" for v in items)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    encode_image(image_path),
                    {"type": "text", "text": PROMPT.format(items=listed)},
                ],
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Refused: {getattr(response, 'stop_details', None)}")

    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


# --- visual PII ---------------------------------------------------------------

VISUAL_PROMPT = """This is a REDACTED document image. Report only what is still
visible in it.

Answer three questions about what survives redaction:

- **face**: is a person's face still visible — enough to recognise them?
  A photograph fully covered by a box is not visible.
- **qr_code**: is a QR code still intact — the finder squares and the data
  area unobscured, so a phone could plausibly scan it? A QR encodes what is
  printed beside it and sometimes more: an Aadhaar QR carries the holder's
  name, date of birth and address, so an intact code beside a blacked-out
  number is not a redaction.
- **barcode**: is a 1-D barcode still intact — bars unobscured across their
  full width?

Count only codes and faces that are part of the document. Report the number
still intact, which may be zero. Judge what you can see, not what ought to be
there; if a code is partly covered but the data area looks readable, count it.
"""

VISUAL_SCHEMA = {
    "type": "object",
    "properties": {
        "face": {"type": "integer"},
        "qr_code": {"type": "integer"},
        "barcode": {"type": "integer"},
        "note": {"type": "string"},
    },
    "required": ["face", "qr_code", "barcode", "note"],
    "additionalProperties": False,
}


def score_visual(client, model: str, image_path: Path) -> dict:
    """How many faces, QR codes and barcodes survive in the redacted output.

    Asked as *legibility*, not as a detection count, for the same reason the
    text scoring is: what matters is whether the thing is still usable to
    someone holding the output, not whether a detector fired. A QR covered by
    a box that leaves its data area readable is a leak; one the detector never
    found but another box happened to cover is not.
    """
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": VISUAL_SCHEMA}},
        messages=[{"role": "user", "content": [
            encode_image(image_path),
            {"type": "text", "text": VISUAL_PROMPT},
        ]}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Refused: {getattr(response, 'stop_details', None)}")
    return json.loads(next(b.text for b in response.content if b.type == "text"))


def merge_verdicts(path: Path, fresh: dict, images_dir: Path) -> dict:
    """Merge this pass into whatever is already on disk.

    This file used to be overwritten with exactly what the current pass
    scored, which made two ordinary situations silently destructive:
    `--limit 3` replaced a twenty-image file with three, and an API error
    part-way through produced a *shorter* file rather than a partial one.
    `score_run.py` then fell back to OCR verdicts for the missing pages and
    reported a whole-corpus number built mostly from the weaker scorer.

    Merging fixes both. Pages scored this pass win; pages scored earlier
    survive. Entries whose image is no longer in the run are dropped, so a
    corpus change cannot leave stale verdicts behind, and the count is
    reported either way — a file that shrinks should say so out loud.
    """
    try:
        existing = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        existing = {}

    def pages(d):
        return {k: v for k, v in d.items() if not k.startswith("_")}

    before = pages(existing)
    kept = {k: v for k, v in before.items() if (images_dir / k).exists()}
    stale = len(before) - len(kept)

    out = {"_note": fresh.get("_note", existing.get("_note", ""))}
    out.update(kept)
    out.update(pages(fresh))

    visual = dict(existing.get("_visual") or {})
    visual = {k: v for k, v in visual.items() if (images_dir / k).exists()}
    visual.update(fresh.get("_visual") or {})
    if visual:
        out["_visual"] = visual

    added = len(pages(out)) - len(kept)
    carried = len(kept) - len(pages(fresh) .keys() & kept.keys())
    if carried > 0:
        console.print(
            f"[cyan]merged: {len(pages(fresh))} page(s) scored now, "
            f"{carried} carried over from the previous file"
            + (f", {stale} dropped (image no longer in the run)" if stale else "")
            + "[/cyan]"
        )
    if len(pages(out)) < len(before):
        console.print(
            f"[yellow]the verdict file now holds {len(pages(out))} page(s), "
            f"down from {len(before)} — check that is intended[/yellow]"
        )
    return out

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--limit", type=int, default=None, help="Only score the first N images"
    )
    parser.add_argument(
        "--no-visual", action="store_true",
        help="Skip the face/QR/barcode pass. Halves the cost and leaves the "
             "visual layer unmeasured, which is how it went unmeasured until now.",
    )
    args = parser.parse_args()

    try:
        client = build_client()
    except (RuntimeError, ImportError) as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)

    run_dir = Path(args.run_dir)
    images_dir = run_dir / "images"
    from redactor import datasets

    corpus = datasets.load(os.environ.get("REDACTOR_CORPUS", "documents"))
    try:
        datasets.check_run_matches(corpus, images_dir, script="vision_score.py")
    except datasets.CorpusMismatchError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(2)
    truth = corpus.annotations

    verdicts: dict[str, dict[str, str]] = {
        "_note": (
            f"Generated by vision_score.py using {args.model}. Each redacted "
            "output image was shown to the model alongside the values the "
            "ground truth says were on that page."
        )
    }
    totals = {"leaked": 0, "redacted": 0}

    # A page with only a QR and no text PII still needs looking at, and a page
    # with no annotation at all is how an un-annotated code stays invisible.
    names = [n for n in sorted(truth) if truth[n]["pii"] and (images_dir / n).exists()]
    visual_names = [n for n in sorted(truth) if (images_dir / n).exists()]
    if args.limit:
        names = names[: args.limit]
        visual_names = visual_names[: args.limit]

    for name in names:
        items = [p["text"] for p in truth[name]["pii"]]
        try:
            result = score_image(client, args.model, images_dir / name, items)
        except Exception as exc:
            console.print(f"[red]{name}: {exc}[/red]")
            continue

        page: dict[str, str] = {}
        for entry in result.get("verdicts", []):
            # Only trust verdicts for values we actually asked about.
            if entry["value"] in items:
                page[entry["value"]] = entry["verdict"]
                totals[entry["verdict"]] += 1
        verdicts[name] = page

        leaked = [v for v, k in page.items() if k == "leaked"]
        colour = "red" if leaked else "green"
        console.print(
            f"[{colour}]{name:34s} {len(leaked)} leaked of {len(page)}[/{colour}]"
            + (f"  {leaked}" if leaked else "")
        )

    if not args.no_visual:
        console.print("\n[bold]visual PII — what survives redaction[/bold]")
        visual: dict[str, dict] = {}
        for name in visual_names:
            try:
                seen = score_visual(client, args.model, images_dir / name)
            except Exception as exc:
                console.print(f"[red]{name}: {exc}[/red]")
                continue
            want = truth[name].get("visual") or {}
            kinds = ("face", "qr_code", "barcode")
            surviving = {k: int(seen.get(k, 0)) for k in kinds}
            visual[name] = {
                "annotated": {k: int(want.get(k, 0)) for k in kinds},
                "surviving": surviving,
                "note": seen.get("note", ""),
            }
            bad = [f"{k} {surviving[k]}" for k in kinds if surviving[k]]
            unannotated = [
                k for k in kinds if surviving[k] and not int(want.get(k, 0))
            ]
            if bad:
                flag = "  [yellow](not annotated: " + ", ".join(unannotated) + ")[/yellow]" \
                    if unannotated else ""
                console.print(f"[red]{name:34s} still visible: {', '.join(bad)}[/red]{flag}")
        verdicts["_visual"] = visual

    out = run_dir / "vision_verdicts.json"
    merged = merge_verdicts(out, verdicts, images_dir)
    out.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
    console.print(
        f"\n[bold]{totals['redacted']} redacted, {totals['leaked']} leaked[/bold]"
    )
    console.print(f"[green]Written to[/green] {out}")
    console.print("Now re-run: [bold]python score_run.py " + str(run_dir) + "[/bold]")


if __name__ == "__main__":
    main()

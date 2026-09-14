#!/usr/bin/env python3
"""Render a visual failure report for a scored run.

Writes `runs/<run>/scored/`, one image per input, with every piece of PII
that survived redaction outlined in place. Reading a leakage table tells
you six LOCATION items leaked; seeing the addresses still legible on the
page tells you how bad that is.

Two failure modes are drawn differently, because they need different
fixes:

    red    — confirmed leak: readable in the redacted output.
    orange — unverifiable: the scorer's OCR cannot read it in either
             image, so there is no evidence it was redacted *or* that it
             leaked. Check these by eye.

Unverifiable items cannot be boxed — there is no OCR box to draw — so
they are listed in a banner beneath the image instead.

Usage:
    python annotate_leaks.py runs/<run-name>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytesseract
from PIL import Image, ImageDraw, ImageFont
from rich.console import Console

from score_run import TOKEN_MATCH_RATIO, is_present, normalize, ocr_tokens, tokens

console = Console()

OCR_SCALE = 2  # must match score_run.ocr_tokens, so verdicts agree
LEAKED_COLOUR = (220, 30, 30)
UNVERIFIABLE_COLOUR = (235, 140, 0)
BANNER_BG = (24, 24, 28)
BANNER_FG = (235, 235, 235)

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _font(size: int):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def word_boxes(image: Image.Image) -> list[tuple[str, int, int, int, int]]:
    """OCR the image and return (text, left, top, width, height) per word.

    Runs at the same upscale the scorer uses, then maps coordinates back
    so boxes land on the original image.
    """
    scaled = image.resize(
        (image.width * OCR_SCALE, image.height * OCR_SCALE), Image.LANCZOS
    )
    data = pytesseract.image_to_data(scaled, output_type=pytesseract.Output.DICT)
    out = []
    for i, text in enumerate(data["text"]):
        if not str(text).strip():
            continue
        out.append(
            (
                normalize(str(text)),
                data["left"][i] // OCR_SCALE,
                data["top"][i] // OCR_SCALE,
                data["width"][i] // OCR_SCALE,
                data["height"][i] // OCR_SCALE,
            )
        )
    return out


def locate(item_text: str, boxes) -> list[tuple[int, int, int, int]]:
    """Find on-page regions matching a PII string, grouped into rows."""
    wanted = set(tokens(item_text))
    if not wanted:
        return []
    hits = [b for b in boxes if b[0] in wanted]
    if not hits:
        return []

    # Group hits into rows so a two-line address yields two boxes rather
    # than one rectangle swallowing everything between them.
    rows: list[list] = []
    for box in sorted(hits, key=lambda b: (b[2], b[1])):
        for row in rows:
            ref = row[0]
            if abs((box[2] + box[4] / 2) - (ref[2] + ref[4] / 2)) <= max(ref[4], 1):
                row.append(box)
                break
        else:
            rows.append([box])

    regions = []
    for row in rows:
        left = min(b[1] for b in row)
        top = min(b[2] for b in row)
        right = max(b[1] + b[3] for b in row)
        bottom = max(b[2] + b[4] for b in row)
        regions.append((left, top, right, bottom))
    return regions


def annotate(
    out_image: Path, items: list[dict], boxes, verdicts: dict
) -> Image.Image:
    base = Image.open(out_image).convert("RGB")
    draw = ImageDraw.Draw(base)
    label_font = _font(max(11, base.width // 55))

    unlocated = []
    for item in items:
        colour = (
            LEAKED_COLOUR
            if verdicts[item["text"]] == "leaked"
            else UNVERIFIABLE_COLOUR
        )
        regions = locate(item["text"], boxes)
        if not regions:
            unlocated.append(item)
            continue
        for left, top, right, bottom in regions:
            draw.rectangle(
                [left - 3, top - 3, right + 3, bottom + 3], outline=colour, width=3
            )
        left, top, right, bottom = regions[0]
        label = item["expected_type"] or "no recognizer"
        draw.text((left - 3, max(0, top - 16)), label, font=label_font, fill=colour)

    return _add_banner(base, items, unlocated, verdicts)


def _add_banner(base, items, unlocated, verdicts):
    font = _font(max(11, base.width // 60))
    lines = [f"{len(items)} PII item(s) not confirmed redacted"]
    for item in unlocated:
        why = (
            "unverifiable — OCR cannot read it either way"
            if verdicts[item["text"]] == "unverifiable"
            else "not located"
        )
        lines.append(f"  • {item['text'][:52]}  [{why}]")
    if not items:
        lines = ["All known PII confirmed redacted"]

    # Trim each line to the image width so nothing runs off the edge.
    max_width = base.width - 16
    fitted = []
    for line in lines:
        if font.getlength(line) <= max_width:
            fitted.append(line)
            continue
        trimmed = line
        while trimmed and font.getlength(trimmed + "…") > max_width:
            trimmed = trimmed[:-1]
        fitted.append(trimmed + "…")
    lines = fitted

    line_h = font.size + 6
    banner_h = line_h * len(lines) + 14
    canvas = Image.new("RGB", (base.width, base.height + banner_h), BANNER_BG)
    canvas.paste(base, (0, 0))
    draw = ImageDraw.Draw(canvas)
    for i, line in enumerate(lines):
        colour = UNVERIFIABLE_COLOUR if line.startswith("  •") else BANNER_FG
        draw.text((8, base.height + 7 + i * line_h), line, font=font, fill=colour)
    return canvas


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    summary = json.loads((run_dir / "summary.json").read_text())
    truth = json.loads(Path("ground_truth.json").read_text())
    input_dir = Path(summary["config"]["input_dir"])
    images_dir = run_dir / "images"
    scored_dir = run_dir / "scored"
    scored_dir.mkdir(parents=True, exist_ok=True)

    total_visible = 0
    for name, entry in sorted(truth.items()):
        src, out = input_dir / name, images_dir / name
        if not src.exists() or not out.exists():
            continue

        before, after = ocr_tokens(src), ocr_tokens(out)
        verdicts, still_visible = {}, []
        for item in entry["pii"]:
            if is_present(item["text"], after):
                verdicts[item["text"]] = "leaked"
                still_visible.append(item)
            elif is_present(item["text"], before):
                verdicts[item["text"]] = "redacted"
            else:
                verdicts[item["text"]] = "unverifiable"
                still_visible.append(item)

        boxes = word_boxes(Image.open(out).convert("RGB")) if still_visible else []
        annotate(out, still_visible, boxes, verdicts).save(scored_dir / name)
        total_visible += len(still_visible)
        flag = "[red]" if still_visible else "[green]"
        console.print(
            f"{flag}{name:34s} {len(still_visible)} unresolved[/]"
        )

    console.print(
        f"\n[bold]{total_visible} PII items still visible[/bold] across "
        f"{len(truth)} images"
    )
    console.print(f"[green]Annotated images written to[/green] {scored_dir}")


if __name__ == "__main__":
    main()

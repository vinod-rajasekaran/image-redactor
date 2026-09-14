#!/usr/bin/env python3
"""Score a run against ground_truth.json by measuring what survived redaction.

Rather than trusting detection counts, this reads the *output* image back
with OCR and asks, for each known PII item: was it legible before, and is
it still legible now?

    redacted        — legible in the input, gone from the output
    leaked          — legible in the input and still legible in the output
    leaked_ocr_miss — OCR never read it, so nothing was drawn over it

**Both leak buckets are visible PII.** An earlier version of this script
reported recall over "legible" items only, excluding `leaked_ocr_miss` on
the reasoning that an OCR failure should not be blamed on Presidio. That
was wrong, and it flattered the numbers badly: a whole laptop-screen form
with an unredacted name, email, phone and address scored as zero misses,
because Tesseract could not read any of it.

Which component failed is an internal detail. If the PII is still on the
page, it leaked. Headline recall is therefore over *all* known PII, with
the split kept only as a diagnostic for where to spend effort.

Usage:
    python score_run.py runs/<run-name>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytesseract
from PIL import Image
from rich.console import Console
from rich.table import Table

console = Console()

# A PII item counts as present when this fraction of its tokens appear in the
# OCR text. Exact matching is useless here — OCR routinely mangles a
# character or two, and a redaction that removes most of a value has done
# its job.
TOKEN_MATCH_RATIO = 0.6


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t]


def is_present(needle: str, haystack_tokens: set[str]) -> bool:
    needle_tokens = tokens(needle)
    if not needle_tokens:
        return False
    hits = sum(1 for t in needle_tokens if t in haystack_tokens)
    return (hits / len(needle_tokens)) >= TOKEN_MATCH_RATIO


def ocr_tokens(path: Path, upscale: int = 2) -> set[str]:
    image = Image.open(path)
    if upscale > 1:
        image = image.resize(
            (image.width * upscale, image.height * upscale), Image.LANCZOS
        )
    return set(tokens(pytesseract.image_to_string(image)))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        console.print(f"[red]No summary.json in {run_dir}[/red]")
        sys.exit(1)

    summary = json.loads(summary_path.read_text())
    truth = json.loads(Path("ground_truth.json").read_text())
    input_dir = Path(summary["config"]["input_dir"])
    images_dir = run_dir / "images"

    rows = []
    totals = {"redacted": 0, "leaked": 0, "leaked_ocr_miss": 0}
    per_type: dict[str, dict[str, int]] = {}

    for name, entry in sorted(truth.items()):
        src, out = input_dir / name, images_dir / name
        if not src.exists() or not out.exists():
            continue
        before, after = ocr_tokens(src), ocr_tokens(out)

        counts = {"redacted": 0, "leaked": 0, "leaked_ocr_miss": 0}
        for item in entry["pii"]:
            if not is_present(item["text"], before):
                verdict = "leaked_ocr_miss"
            elif is_present(item["text"], after):
                verdict = "leaked"
            else:
                verdict = "redacted"
            counts[verdict] += 1
            totals[verdict] += 1
            key = item["expected_type"] or "(no recognizer)"
            per_type.setdefault(
                key, {"redacted": 0, "leaked": 0, "leaked_ocr_miss": 0}
            )
            per_type[key][verdict] += 1
        rows.append((name, entry["source"], counts))

    table = Table(title=f"Leakage by image — {summary['config']['run_name']}")
    table.add_column("image", style="cyan")
    table.add_column("src")
    table.add_column("redacted", justify="right", style="green")
    table.add_column("leaked", justify="right", style="red")
    table.add_column("leaked (ocr miss)", justify="right", style="yellow")
    for name, source, c in rows:
        table.add_row(
            name, source, str(c["redacted"]), str(c["leaked"]),
            str(c["leaked_ocr_miss"])
        )
    console.print(table)

    ttable = Table(title="Leakage by expected entity type")
    ttable.add_column("expected type", style="cyan")
    ttable.add_column("redacted", justify="right", style="green")
    ttable.add_column("leaked", justify="right", style="red")
    ttable.add_column("leaked (ocr miss)", justify="right", style="yellow")
    for key, c in sorted(
        per_type.items(), key=lambda kv: -(kv[1]["leaked"] + kv[1]["leaked_ocr_miss"])
    ):
        ttable.add_row(
            key, str(c["redacted"]), str(c["leaked"]), str(c["leaked_ocr_miss"])
        )
    console.print(ttable)

    total = sum(totals.values())
    visible = totals["leaked"] + totals["leaked_ocr_miss"]
    recall = (totals["redacted"] / total * 100) if total else 0.0
    console.print(
        f"\n[bold]Redaction recall over all known PII: {recall:.1f}%[/bold] "
        f"({totals['redacted']}/{total})\n"
        f"[red]{visible} items still visible[/red] — "
        f"{totals['leaked']} detected-but-missed, "
        f"{totals['leaked_ocr_miss']} never read by OCR"
    )

    score_path = run_dir / "score.json"
    score_path.write_text(
        json.dumps(
            {
                "run_name": summary["config"]["run_name"],
                "config": summary["config"],
                "totals": totals,
                "recall_overall_pct": round(recall, 1),
                "items_still_visible": visible,
                "by_type": per_type,
                "by_image": {n: c for n, _s, c in rows},
            },
            indent=2,
        )
    )
    console.print(f"[green]Scores written to[/green] {score_path}")


if __name__ == "__main__":
    main()

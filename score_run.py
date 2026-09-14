#!/usr/bin/env python3
"""Score a run against ground_truth.json by measuring what survived redaction.

Rather than trusting detection counts, this reads the *output* image back
with OCR and asks, for each known PII item: was it legible before, and is
it still legible now?

    leaked        — legible in the input and still legible in the output
    redacted      — legible in the input, gone from the output
    not_legible   — OCR could not read it even in the input, so text
                    redaction never had a chance (an OCR problem, not a
                    Presidio one)

That last bucket matters: counting it as a success would flatter the tool,
and counting it as a miss would blame the wrong component.

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
    totals = {"leaked": 0, "redacted": 0, "not_legible": 0}
    per_type: dict[str, dict[str, int]] = {}

    for name, entry in sorted(truth.items()):
        src, out = input_dir / name, images_dir / name
        if not src.exists() or not out.exists():
            continue
        before, after = ocr_tokens(src), ocr_tokens(out)

        counts = {"leaked": 0, "redacted": 0, "not_legible": 0}
        for item in entry["pii"]:
            if not is_present(item["text"], before):
                verdict = "not_legible"
            elif is_present(item["text"], after):
                verdict = "leaked"
            else:
                verdict = "redacted"
            counts[verdict] += 1
            totals[verdict] += 1
            key = item["expected_type"] or "(no recognizer)"
            per_type.setdefault(key, {"leaked": 0, "redacted": 0, "not_legible": 0})
            per_type[key][verdict] += 1
        rows.append((name, entry["source"], counts))

    table = Table(title=f"Leakage by image — {summary['config']['run_name']}")
    table.add_column("image", style="cyan")
    table.add_column("src")
    table.add_column("redacted", justify="right", style="green")
    table.add_column("leaked", justify="right", style="red")
    table.add_column("not legible", justify="right", style="yellow")
    for name, source, c in rows:
        table.add_row(
            name, source, str(c["redacted"]), str(c["leaked"]), str(c["not_legible"])
        )
    console.print(table)

    ttable = Table(title="Leakage by expected entity type")
    ttable.add_column("expected type", style="cyan")
    ttable.add_column("redacted", justify="right", style="green")
    ttable.add_column("leaked", justify="right", style="red")
    ttable.add_column("not legible", justify="right", style="yellow")
    for key, c in sorted(per_type.items(), key=lambda kv: -kv[1]["leaked"]):
        ttable.add_row(key, str(c["redacted"]), str(c["leaked"]), str(c["not_legible"]))
    console.print(ttable)

    legible = totals["redacted"] + totals["leaked"]
    recall = (totals["redacted"] / legible * 100) if legible else 0.0
    console.print(
        f"\n[bold]Redaction recall on legible PII: {recall:.1f}%[/bold] "
        f"({totals['redacted']}/{legible})   "
        f"[red]leaked {totals['leaked']}[/red]   "
        f"[yellow]not legible to OCR {totals['not_legible']}[/yellow]"
    )

    score_path = run_dir / "score.json"
    score_path.write_text(
        json.dumps(
            {
                "run_name": summary["config"]["run_name"],
                "config": summary["config"],
                "totals": totals,
                "recall_on_legible_pct": round(recall, 1),
                "by_type": per_type,
                "by_image": {n: c for n, _s, c in rows},
            },
            indent=2,
        )
    )
    console.print(f"[green]Scores written to[/green] {score_path}")


if __name__ == "__main__":
    main()

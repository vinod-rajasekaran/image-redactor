#!/usr/bin/env python3
"""Score a run against ground_truth.json by measuring what survived redaction.

Rather than trusting detection counts, this reads the *output* image back
with OCR and asks, for each known PII item: was it legible before, and is
it still legible now?

    leaked       — still readable in the output. Confirmed failure.
    redacted     — readable in the input, gone from the output. Confirmed
                   success.
    unverifiable — the scorer's OCR cannot read it in either image, so
                   there is no evidence either way.

This script has had this wrong in both directions, which is why the third
bucket exists.

It first reported recall over "legible" items only, silently excluding
everything its OCR could not read. That flattered the result: a
laptop-screen form with an unredacted name, email, phone and address
scored as zero misses because Tesseract read none of it.

Counting those as leaks instead over-corrected. When the redaction run
uses a stronger engine than the scorer, PII that engine correctly
redacted gets called a leak — a job-application email, verified by eye as
fully blacked out, was reported as still visible purely because the
scorer's Tesseract could not read it in the input.

Neither claim was supportable, so results are now reported as a range:
a confirmed floor, and a ceiling that assumes every unverifiable item was
redacted. Narrow the gap by scoring with a stronger reader
(`--scorer-ocr paddle`), since the real question is whether *anyone* can
read the PII, not whether Tesseract can.

Usage:
    python score_run.py runs/<run-name> [--scorer-ocr paddle]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

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


_SCORER_OCR = None


def set_scorer_ocr(backend: str = "tesseract") -> None:
    """Choose the reader used for scoring.

    The question a scorer answers is whether *anyone* can still read the
    PII, so it should use the strongest reader available — not necessarily
    the one the redaction run used. A weak scorer inflates the
    unverifiable bucket and can report a correctly redacted value as
    unproven.
    """
    global _SCORER_OCR
    from ocr_backends import build_ocr

    _SCORER_OCR = build_ocr(backend, psm=4 if backend == "tesseract" else None)


def ocr_tokens(path: Path, upscale: int = 2) -> set[str]:
    if _SCORER_OCR is None:
        set_scorer_ocr()
    image = Image.open(path)
    if upscale > 1:
        image = image.resize(
            (image.width * upscale, image.height * upscale), Image.LANCZOS
        )
    result = _SCORER_OCR.perform_ocr(image)
    return set(tokens(" ".join(str(t) for t in result["text"])))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    backend = "tesseract"
    if "--scorer-ocr" in sys.argv:
        backend = sys.argv[sys.argv.index("--scorer-ocr") + 1]
    set_scorer_ocr(backend)
    console.print(f"[dim]scoring with OCR backend: {backend}[/dim]")

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
    totals = {"redacted": 0, "leaked": 0, "unverifiable": 0}
    per_type: dict[str, dict[str, int]] = {}
    per_tier: dict[str, dict[str, int]] = {}

    for name, entry in sorted(truth.items()):
        src, out = input_dir / name, images_dir / name
        if not src.exists() or not out.exists():
            continue
        before, after = ocr_tokens(src), ocr_tokens(out)

        counts = {"redacted": 0, "leaked": 0, "unverifiable": 0}
        for item in entry["pii"]:
            if is_present(item["text"], after):
                verdict = "leaked"          # readable in the output: certain
            elif is_present(item["text"], before):
                verdict = "redacted"        # was readable, now is not
            else:
                verdict = "unverifiable"    # never readable to this scorer
            counts[verdict] += 1
            totals[verdict] += 1
            key = item["expected_type"] or "(no recognizer)"
            per_type.setdefault(
                key, {"redacted": 0, "leaked": 0, "unverifiable": 0}
            )
            per_type[key][verdict] += 1
            cat = item.get("tier", "core")
            per_tier.setdefault(
                cat, {"redacted": 0, "leaked": 0, "unverifiable": 0}
            )
            per_tier[cat][verdict] += 1
        rows.append((name, entry["source"], counts))

    table = Table(title=f"Leakage by image — {summary['config']['run_name']}")
    table.add_column("image", style="cyan")
    table.add_column("src")
    table.add_column("redacted", justify="right", style="green")
    table.add_column("leaked", justify="right", style="red")
    table.add_column("unverifiable", justify="right", style="yellow")
    for name, source, c in rows:
        table.add_row(
            name, source, str(c["redacted"]), str(c["leaked"]),
            str(c["unverifiable"])
        )
    console.print(table)

    ttable = Table(title="Leakage by expected entity type")
    ttable.add_column("expected type", style="cyan")
    ttable.add_column("redacted", justify="right", style="green")
    ttable.add_column("leaked", justify="right", style="red")
    ttable.add_column("unverifiable", justify="right", style="yellow")
    for key, c in sorted(
        per_type.items(), key=lambda kv: -(kv[1]["leaked"] + kv[1]["unverifiable"])
    ):
        ttable.add_row(
            key, str(c["redacted"]), str(c["leaked"]), str(c["unverifiable"])
        )
    console.print(ttable)

    ctable = Table(title="By PII tier")
    ctable.add_column("tier", style="cyan")
    ctable.add_column("redacted", justify="right", style="green")
    ctable.add_column("leaked", justify="right", style="red")
    ctable.add_column("unverifiable", justify="right", style="yellow")
    ctable.add_column("floor %", justify="right")
    for cat, c in sorted(per_tier.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(c.values())
        ctable.add_row(
            cat, str(c["redacted"]), str(c["leaked"]), str(c["unverifiable"]),
            f"{c['redacted'] / n * 100:.0f}" if n else "-",
        )
    console.print(ctable)

    total = sum(totals.values())
    floor = (totals["redacted"] / total * 100) if total else 0.0
    ceiling = (
        ((totals["redacted"] + totals["unverifiable"]) / total * 100)
        if total
        else 0.0
    )
    console.print(
        f"\n[bold]Redaction recall: {floor:.1f}% – {ceiling:.1f}%[/bold] "
        f"of {total} known PII items\n"
        f"[green]{totals['redacted']} confirmed redacted[/green]   "
        f"[red]{totals['leaked']} confirmed still visible[/red]   "
        f"[yellow]{totals['unverifiable']} unverifiable[/yellow] "
        f"(scorer OCR could not read them either way)"
    )

    score_path = run_dir / "score.json"
    score_path.write_text(
        json.dumps(
            {
                "run_name": summary["config"]["run_name"],
                "config": summary["config"],
                "totals": totals,
                "recall_floor_pct": round(floor, 1),
                "recall_ceiling_pct": round(ceiling, 1),
                "confirmed_visible": totals["leaked"],
                "by_type": per_type,
                "by_tier": per_tier,
                "by_image": {n: c for n, _s, c in rows},
            },
            indent=2,
        )
    )
    console.print(f"[green]Scores written to[/green] {score_path}")


if __name__ == "__main__":
    main()

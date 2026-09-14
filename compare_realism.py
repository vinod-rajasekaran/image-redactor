#!/usr/bin/env python3
"""Compare realism settings on two axes that pull against each other.

Making a synthetic corpus more realistic makes it harder, which is the
point — but only up to the moment the ground truth stops being
establishable. A value the verifier cannot read on the page cannot be
scored, and a corpus of unscoreable items measures nothing.

So each setting gets two numbers:

- **read-back rate** — of the values asked for, how many the verifier
  could actually find and transcribe. This is the ceiling on usable
  ground truth, and it must stay high.
- **redaction score** — of the items that *were* established, how many
  the redactor covered. This is the difficulty we are trying to raise.

The setting to pick is the hardest one whose read-back has not yet
started to fall. Push past that and the corpus is not harder, only
blinder.

Usage:
    python compare_realism.py generated probe_authentic probe_field
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from redactor import datasets, synth

console = Console()


def expected_items(corpus) -> int:
    """How many PII values were asked for across this corpus's documents.

    Drawn from the same templates the generator used, so the count is the
    template's, not the rendered page's — which is exactly the denominator
    the read-back rate needs.
    """
    total = 0
    for filename in corpus.annotations:
        doc_type = filename.split("_", 1)[1].rsplit(".", 1)[0]
        total += len(synth.draw(doc_type).pii())
    return total


def read_back(corpus) -> tuple[int, int, int]:
    """(established, expected, altered) for one corpus."""
    established = sum(len(e["pii"]) for e in corpus.annotations.values())
    altered = sum(
        "requested" in item
        for entry in corpus.annotations.values()
        for item in entry["pii"]
    )
    return established, expected_items(corpus), altered


def redaction(corpus, run_dir: Path) -> tuple[int, int] | None:
    """(redacted, scored) from a vision-scored run, if one exists."""
    verdicts_path = run_dir / "vision_verdicts.json"
    if not verdicts_path.exists():
        return None
    verdicts = json.loads(verdicts_path.read_text())
    redacted = scored = 0
    for filename, entry in corpus.annotations.items():
        seen = verdicts.get(filename, {})
        for item in entry["pii"]:
            verdict = seen.get(item["text"])
            if verdict is None:
                continue
            scored += 1
            redacted += verdict == "redacted"
    return redacted, scored


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpora", nargs="+")
    parser.add_argument("--runs-dir", default="runs")
    args = parser.parse_args()

    table = Table(title="Realism settings — difficulty against usability")
    table.add_column("corpus", style="cyan")
    table.add_column("realism")
    table.add_column("imgs", justify="right")
    table.add_column("read-back", justify="right", style="bold")
    table.add_column("altered", justify="right")
    table.add_column("redacted", justify="right", style="bold")

    for name in args.corpora:
        try:
            corpus = datasets.load(name)
        except FileNotFoundError:
            console.print(f"[yellow]skipping {name}: not found[/yellow]")
            continue
        established, expected, altered = read_back(corpus)
        rate = established / expected * 100 if expected else 0.0
        style = "green" if rate >= 98 else "yellow" if rate >= 90 else "red"

        scores = redaction(corpus, Path(args.runs_dir) / name)
        if scores is None:
            redacted_cell = "[dim]not scored[/dim]"
        else:
            redacted, scored = scores
            redacted_cell = (
                f"{redacted / scored * 100:.0f}% ({redacted}/{scored})"
                if scored else "[dim]0 scored[/dim]"
            )

        table.add_row(
            name,
            corpus.meta.get("realism", "—"),
            str(len(corpus)),
            f"[{style}]{rate:.0f}% ({established}/{expected})[/{style}]",
            str(altered),
            redacted_cell,
        )

    console.print(table)
    console.print(
        "\n[bold]Read the table this way:[/bold] read-back is a ceiling, not a "
        "score — it is how much ground truth could be established at all. "
        "Take the hardest setting whose read-back is still ~100%; a lower "
        "redaction score under a falling read-back means the corpus went "
        "blind, not that the redactor got worse."
    )


if __name__ == "__main__":
    main()

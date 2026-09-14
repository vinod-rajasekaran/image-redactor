#!/usr/bin/env python3
"""Evaluate the recognizer stack against maskara-indian-pii-200k (MIT).

A second, independent text benchmark alongside IndiaPII-Bench. Two things
make it worth having separately:

- an **`ocr` domain** of deliberately OCR-corrupted text, which tests the
  exact failure the Aadhaar fallback exists for
- **hard negatives**, and a `real_world_eval` split that is not
  template-generated

Being text, it isolates detection from OCR entirely: a miss here is a
recognizer gap and nothing else.

Dataset: https://huggingface.co/datasets/somukandula/maskara-indian-pii-200k
Licence: MIT. Download the split into benchmarks/:

    curl -sL -o benchmarks/maskara_real_world_eval.parquet \\
      https://huggingface.co/datasets/somukandula/maskara-indian-pii-200k/resolve/main/data/real_world_eval-00000-of-00001.parquet

Usage:
    python benchmark_maskara.py [--limit N]
"""
from __future__ import annotations

import argparse
import collections
import logging
from pathlib import Path

from redactor import datasets
from rich.console import Console
from rich.table import Table

console = Console()
DATASET = datasets.ROOT / "text" / "maskara_real_world_eval.parquet"

# Their label -> the Presidio entity types we accept as a hit. An empty
# set means we have no recognizer for it and never claimed to.
LABEL_TO_OURS = {
    "AADHAAR": {"IN_AADHAAR"},
    "PAN_CARD": {"IN_PAN"},
    "PHONE": {"PHONE_NUMBER"},
    "EMAIL": {"EMAIL_ADDRESS"},
    "PERSON_NAME": {"PERSON"},
    "ADDRESS": {"LOCATION"},
    "VEHICLE_REG": {"IN_VEHICLE_REGISTRATION"},
    "DRIVER_LICENSE": {"IN_DRIVING_LICENCE"},
    "DATE_OF_BIRTH": {"DATE_TIME"},
    "IP_ADDRESS": {"IP_ADDRESS"},
    "UPI_ID": set(),
    "USERNAME": set(),
    "API_KEY": set(),
    "PASSWORD": set(),
    "SSN": set(),
    "CREDIT_CARD": {"CREDIT_CARD"},
    "PASSPORT": {"IN_PASSPORT", "US_PASSPORT"},
}


def overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--threshold", type=float, default=0.4)
    args = parser.parse_args()

    if not DATASET.exists():
        console.print(f"[red]Missing {DATASET}[/red] — see the docstring.")
        raise SystemExit(1)

    import pyarrow.parquet as pq
    from presidio_analyzer import AnalyzerEngine

    from redactor.recognizers import build_registry

    logging.basicConfig(level=logging.CRITICAL)
    analyzer = AnalyzerEngine(registry=build_registry(logging.getLogger("bench")))

    rows = pq.read_table(DATASET).to_pylist()
    if args.limit:
        rows = rows[: args.limit]

    per_label = collections.defaultdict(lambda: [0, 0])
    per_domain = collections.defaultdict(lambda: [0, 0])
    decoys = [0, 0]

    for row in rows:
        results = analyzer.analyze(
            text=row["text"], language="en", score_threshold=args.threshold
        )
        if row["difficulty"] == "hard_negative":
            decoys[1] += 1
            decoys[0] += bool(results)
            continue
        for entity in row["entities"]:
            accepted = LABEL_TO_OURS.get(entity["label"], set())
            hit = any(
                overlaps(entity["start"], entity["end"], r.start, r.end)
                and (not accepted or r.entity_type in accepted)
                for r in results
            )
            per_label[entity["label"]][0] += hit
            per_label[entity["label"]][1] += 1
            per_domain[row["domain"]][0] += hit
            per_domain[row["domain"]][1] += 1

    table = Table(title=f"maskara — recall by entity ({len(rows)} docs)")
    table.add_column("their label", style="cyan")
    table.add_column("our entity")
    table.add_column("n", justify="right")
    table.add_column("recall %", justify="right", style="bold")
    for label, (hit, total) in sorted(per_label.items(), key=lambda kv: -kv[1][1]):
        accepted = LABEL_TO_OURS.get(label, set())
        table.add_row(
            label,
            ", ".join(sorted(accepted)) if accepted else "[red]none[/red]",
            str(total),
            f"{hit / total * 100:.0f}" if total else "-",
        )
    console.print(table)

    dtable = Table(title="recall by domain")
    dtable.add_column("domain", style="cyan")
    dtable.add_column("n", justify="right")
    dtable.add_column("recall %", justify="right", style="bold")
    for domain, (hit, total) in sorted(per_domain.items(), key=lambda kv: -kv[1][1]):
        dtable.add_row(domain, str(total), f"{hit / total * 100:.0f}")
    console.print(dtable)

    hit = sum(v[0] for v in per_label.values())
    total = sum(v[1] for v in per_label.values())
    console.print(
        f"\n[bold]Overall recall: {hit / total * 100:.1f}%[/bold] ({hit}/{total})\n"
        f"[yellow]Hard negatives flagged: {decoys[0]}/{decoys[1]}[/yellow]"
    )


if __name__ == "__main__":
    main()

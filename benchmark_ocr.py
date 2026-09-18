#!/usr/bin/env python3
"""Run several OCR configurations over the same images and score each.

Reports redaction recall (from score_run.py's leakage measurement) against
wall-clock cost, so the accuracy/latency trade-off is visible in one table
rather than inferred from entity counts.

Usage:
    python benchmark_ocr.py [--quick] [--input datasets/documents/images]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from redactor import datasets

console = Console()

CONFIGS = [
    ("tesseract-psm3", ["--ocr", "tesseract"]),
    ("tesseract-psm4", ["--ocr", "tesseract", "--psm", "4"]),
    ("tesseract-psm6", ["--ocr", "tesseract", "--psm", "6"]),
    ("tesseract-psm11", ["--ocr", "tesseract", "--psm", "11"]),
    ("tesseract-psm12", ["--ocr", "tesseract", "--psm", "12"]),
    ("rapidocr", ["--ocr", "rapidocr"]),
    ("paddle", ["--ocr", "paddle"]),
]


def run(name: str, flags: list[str], input_dir: str) -> dict | None:
    run_dir = Path("runs") / f"bench_{name}"
    subprocess.run(["rm", "-rf", str(run_dir)], check=False)

    start = time.monotonic()
    proc = subprocess.run(
        [
            sys.executable,
            "evaluate_redactor.py",
            "--input",
            input_dir,
            "--run-name",
            f"bench_{name}",
            *flags,
        ],
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - start
    if proc.returncode not in (0, 2):
        console.print(
            f"[red]{name} failed[/red] (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout)[-400:]}"
        )
        return None

    scored = subprocess.run(
        [sys.executable, "score_run.py", str(run_dir)], capture_output=True, text=True
    )
    score_path = run_dir / "score.json"
    if not score_path.exists():
        console.print(f"[red]{name} scoring failed[/red]: {scored.stderr[-400:]}")
        return None

    score = json.loads(score_path.read_text())
    score["wall_seconds"] = round(elapsed, 1)
    return score


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick", action="store_true", help="Skip paddle (the slow one)"
    )
    parser.add_argument(
        "--input",
        default="datasets/documents/images",
        help="Corpus to run every configuration over",
    )
    args = parser.parse_args()

    # This script picks an OCR configuration by score, which is tuning. A
    # held-out corpus may be scored once with a configuration chosen
    # elsewhere; it may not be the thing that chooses one.
    try:
        datasets.refuse_if_tuning(
            args.input, purpose="Sweeping OCR configurations with benchmark_ocr.py"
        )
    except datasets.HeldOutCorpusError as exc:
        console.print(f"[red]refused[/red]\n{exc}")
        raise SystemExit(2)

    configs = [c for c in CONFIGS if not (args.quick and c[0] == "paddle")]
    results = []
    for name, flags in configs:
        console.print(f"[cyan]running[/cyan] {name} ...")
        score = run(name, flags, args.input)
        if score:
            results.append((name, score))

    table = Table(title="OCR configurations — redaction recall vs cost")
    table.add_column("config", style="cyan")
    table.add_column("redacted", justify="right", style="green")
    table.add_column("leaked", justify="right", style="red")
    table.add_column("unverifiable", justify="right", style="yellow")
    table.add_column("recall % (floor-ceiling)", justify="right", style="bold")
    table.add_column("wall s", justify="right")
    for name, s in sorted(results, key=lambda kv: -kv[1]["recall_floor_pct"]):
        t = s["totals"]
        table.add_row(
            name,
            str(t["redacted"]),
            str(t["leaked"]),
            str(t["unverifiable"]),
            f"{s['recall_floor_pct']:.1f}-{s['recall_ceiling_pct']:.1f}",
            f"{s['wall_seconds']:.0f}",
        )
    console.print(table)

    out = Path("runs/benchmark.json")
    out.write_text(
        json.dumps(
            {
                n: {
                    "recall_floor_pct": s["recall_floor_pct"],
                    "recall_ceiling_pct": s["recall_ceiling_pct"],
                    "totals": s["totals"],
                    "wall_seconds": s["wall_seconds"],
                    "config": s["config"],
                }
                for n, s in results
            },
            indent=2,
        )
    )
    console.print(f"[green]Written to[/green] {out}")


if __name__ == "__main__":
    main()

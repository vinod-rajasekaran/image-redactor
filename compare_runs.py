#!/usr/bin/env python3
"""Diff two vision-scored runs: what the candidate catches, and what it costs.

Built for one question — **is a second detection pass worth running?** — but
it does not know anything about vision models. Any two runs over the same
corpus can be compared: OCR backends, thresholds, a recognizer change, or a
VLM pass unioned on top.

Three numbers decide it, and the third is the one usually skipped:

- **marginal catch** — items the baseline leaked and the candidate covered.
  The only reason to add a pass.
- **regressions** — items the baseline covered and the candidate leaked.
  Unioning boxes should make this impossible; if it is not zero, something
  is wrong and the run is not a straight improvement.
- **cost per marginal catch** — wall-clock seconds spent per leak actually
  prevented. A pass that catches two more items for twenty minutes is a
  different proposition from one that catches two for twenty seconds.

Usage:
    python evaluate_redactor.py --input <images> --run-name base
    REDACTOR_CORPUS=<corpus> python vision_score.py runs/base

    python evaluate_redactor.py --input <images> --run-name vlm --vlm
    REDACTOR_CORPUS=<corpus> python vision_score.py runs/vlm

    python compare_runs.py runs/base runs/vlm
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def load(run_dir: Path) -> tuple[dict, dict]:
    verdicts_path = run_dir / "vision_verdicts.json"
    summary_path = run_dir / "summary.json"
    if not verdicts_path.exists():
        console.print(
            f"[red]{verdicts_path} missing[/red] — vision-score it first:\n"
            f"  REDACTOR_CORPUS=<corpus> python vision_score.py {run_dir}"
        )
        raise SystemExit(1)
    verdicts = {k: v for k, v in json.loads(verdicts_path.read_text()).items()
                if not k.startswith("_")}
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    return verdicts, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--show", type=int, default=15,
                        help="how many individual items to list")
    args = parser.parse_args()

    base_dir, cand_dir = Path(args.baseline), Path(args.candidate)
    base, base_summary = load(base_dir)
    cand, cand_summary = load(cand_dir)

    shared_files = sorted(set(base) & set(cand))
    if not shared_files:
        console.print("[red]These runs share no images.[/red]")
        raise SystemExit(1)
    if set(base) != set(cand):
        console.print(
            f"[yellow]Runs cover different images; comparing the "
            f"{len(shared_files)} in both.[/yellow]"
        )

    caught, regressed = [], []
    base_leaks = cand_leaks = scored = 0
    for filename in shared_files:
        b, c = base[filename], cand[filename]
        for value, base_verdict in b.items():
            cand_verdict = c.get(value)
            if cand_verdict is None:
                continue
            scored += 1
            base_leaks += base_verdict == "leaked"
            cand_leaks += cand_verdict == "leaked"
            if base_verdict == "leaked" and cand_verdict == "redacted":
                caught.append((filename, value))
            elif base_verdict == "redacted" and cand_verdict == "leaked":
                regressed.append((filename, value))

    base_time = base_summary.get("duration_seconds") or 0.0
    cand_time = cand_summary.get("duration_seconds") or 0.0
    images = len(shared_files)
    extra_time = cand_time - base_time

    table = Table(title=f"{base_dir.name} -> {cand_dir.name}  ({images} images)")
    table.add_column("", style="cyan")
    table.add_column("baseline", justify="right")
    table.add_column("candidate", justify="right")
    table.add_row("items scored", str(scored), str(scored))
    table.add_row("leaked", str(base_leaks), str(cand_leaks))
    table.add_row(
        "redacted",
        f"{(scored - base_leaks) / scored * 100:.1f}%" if scored else "-",
        f"{(scored - cand_leaks) / scored * 100:.1f}%" if scored else "-",
    )
    table.add_row("wall seconds", f"{base_time:.0f}", f"{cand_time:.0f}")
    table.add_row("seconds / image", f"{base_time / images:.1f}",
                  f"{cand_time / images:.1f}")
    console.print(table)

    console.print(
        f"\n[bold green]Marginal catch: {len(caught)}[/bold green] "
        f"item(s) the baseline leaked and the candidate covered"
    )
    for filename, value in caught[: args.show]:
        console.print(f"    {filename:34s} {value[:52]}")
    if len(caught) > args.show:
        console.print(f"    … and {len(caught) - args.show} more")

    style = "red" if regressed else "dim"
    console.print(
        f"\n[{style}]Regressions: {len(regressed)}[/{style}] "
        f"item(s) the baseline covered and the candidate leaked"
    )
    for filename, value in regressed[: args.show]:
        console.print(f"    {filename:34s} {value[:52]}")
    if regressed:
        console.print(
            "[red]Unioning boxes should make a regression impossible. A "
            "non-zero count means the candidate removed a box rather than "
            "adding one, or the two runs are not comparable.[/red]"
        )

    console.print()
    if len(caught) and extra_time > 0:
        console.print(
            f"[bold]Cost: {extra_time:.0f}s extra for {len(caught)} "
            f"prevented leak(s) — {extra_time / len(caught):.0f}s each.[/bold]"
        )
    elif extra_time > 0:
        console.print(
            f"[bold red]Cost: {extra_time:.0f}s extra and nothing caught.[/bold red]"
        )
    else:
        console.print("[bold]The candidate was not slower.[/bold]")

    remaining = cand_leaks
    if remaining:
        console.print(
            f"[yellow]{remaining} leak(s) survive both.[/yellow] Whether the "
            "candidate is worth its cost is a judgement about how much a "
            "prevented leak is worth — this prints the exchange rate, not the "
            "verdict."
        )


if __name__ == "__main__":
    main()

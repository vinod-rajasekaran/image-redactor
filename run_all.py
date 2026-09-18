#!/usr/bin/env python3
"""Run and score all three image corpora into one run folder.

One command, one folder, one report. `documents/`, `cheques/` and `holdout/`
each get a complete run directory *inside* it:

    runs/<name>/
      report.html          tabbed, all three corpora
      documents/           an ordinary run folder
      cheques/
      holdout/

Nesting rather than merging is deliberate. Every existing tool takes a run
directory and finds `images/`, `scored/`, `score.json` beside each other, so
each subfolder stays a run folder those tools already understand:

    python score_run.py runs/<name>/documents
    python compare_runs.py runs/old/cheques runs/new/cheques

Merging the three into one flat folder would have meant teaching every one of
them which corpus each image belonged to, and a filename collision between
corpora — which has already happened once here — would have been silent.

**The three numbers are not comparable and the report says so.**
`documents/` and `holdout/` are scored per annotated value; `cheques/` carries
boxes but no ground-truth text, so it is scored per *element* by a vision
model. `documents/` is familiar material the recognizers were written against.
`cheques/` is the only independent image corpus here.

**On scoring `holdout/` every time:** it is held out, and nothing may be
chosen from its number. Because the suite now scores it on every run, the
warning signal is **distinct commits scored**, not the raw run count —
running the suite ten times without committing leaves it at one. Use
`--skip holdout` when you just want the other two.

Usage:
    python run_all.py <name> [--skip cheques] [--no-vision] [--no-open]
    python run_all.py nightly --ocr paddle      # extra flags go to the pipeline
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from redactor import datasets, report

console = Console()

CORPORA = {
    "documents": "datasets/documents/images",
    "cheques": "datasets/cheques/images",
    "holdout": "datasets/holdout/images",
}


def run(cmd: list[str], env: dict | None = None) -> bool:
    """Run one step. A failing corpus never aborts the others."""
    proc = subprocess.run(
        cmd, env={**os.environ, **(env or {})}, capture_output=True, text=True
    )
    if proc.returncode != 0:
        console.print(
            f"[red]failed[/red] {' '.join(cmd[1:3])} "
            f"(exit {proc.returncode}): {(proc.stderr or proc.stdout)[-300:]}"
        )
        return False
    return True


def do_corpus(name: str, run_dir: Path, extra: list[str], *, vision: bool) -> bool:
    """Redact, score and annotate one corpus inside the shared run folder."""
    sub = run_dir / name
    env = {"REDACTOR_CORPUS": name}
    console.rule(f"[bold blue]{name}")

    if not run([sys.executable, "evaluate_redactor.py",
                "--input", CORPORA[name],
                "--run-name", f"{run_dir.name}/{name}", *extra]):
        return False

    if name == "cheques":
        # No ground-truth text: legibility is asked per element instead.
        if vision:
            run([sys.executable, "cheque_benchmark.py", "--legibility", str(sub)])
        return True

    if vision and not run([sys.executable, "vision_score.py", str(sub)], env):
        console.print(
            f"[yellow]{name}: vision scoring failed — the OCR scorer is blind "
            f"exactly where redaction fails, so treat the score as a floor of "
            f"unknown depth.[/yellow]"
        )
    run([sys.executable, "score_run.py", str(sub), "--no-open"], env)
    run([sys.executable, "annotate_leaks.py", str(sub)], env)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("name", help="Run name — becomes runs/<name>/")
    parser.add_argument(
        "--skip", action="append", default=[], choices=sorted(CORPORA),
        help="Corpus to leave out; repeatable",
    )
    parser.add_argument(
        "--no-vision", action="store_true",
        help="Skip vision scoring. Faster and free, and the resulting number "
             "is weaker than it looks — OCR cannot read what it could not read.",
    )
    parser.add_argument("--no-open", action="store_true")
    args, extra = parser.parse_known_args()

    run_dir = Path("runs") / args.name
    run_dir.mkdir(parents=True, exist_ok=True)
    wanted = [c for c in report.SUITE if c not in args.skip]

    done = []
    for name in wanted:
        if not Path(CORPORA[name]).exists():
            console.print(f"[yellow]{name}: {CORPORA[name]} missing — skipped[/yellow]")
            continue
        if do_corpus(name, run_dir, extra, vision=not args.no_vision):
            done.append(name)

    panels = [p for p in (report.panel(run_dir, n) for n in done) if p]
    if not panels:
        console.print("[red]Nothing scored — no report written.[/red]")
        raise SystemExit(1)

    table = Table(title=f"{args.name} — all corpora")
    table.add_column("corpus", style="cyan")
    table.add_column("covered", justify="right", style="green")
    table.add_column("leaked", justify="right", style="red")
    table.add_column("%", justify="right", style="bold")
    table.add_column("scored by")
    for p in panels:
        table.add_row(
            p["name"] + (" (held out)" if p["held_out"] else ""),
            str(p["totals"].get("redacted", 0)),
            str(p["totals"].get("leaked", 0)),
            f"{p['pct']:.1f}",
            "value legibility" if p["unit"] == "items" else "element legibility",
        )
    console.print(table)
    console.print(
        "[dim]Not a leaderboard: cheques is scored per element and is not "
        "comparable with the other two.[/dim]"
    )

    held = [p for p in panels if p["held_out"]]
    for p in held:
        hist = report.history_for(p["name"])
        commits = {h.get("git", {}).get("sha") for h in hist}
        console.print(
            f"[yellow]{p['name']} is held out — scored at {len(commits)} distinct "
            f"commit(s), {len(hist)} run(s). Nothing may be chosen from it.[/yellow]"
        )

    path = report.write_combined(run_dir, panels)
    console.print(f"[green]Report written to[/green] {path}")
    if not args.no_open and report.open_in_browser(path):
        console.print("[dim]opened in your browser[/dim]")


if __name__ == "__main__":
    main()

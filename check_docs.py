#!/usr/bin/env python3
"""Check the docs against the rules in CLAUDE.md, before a push.

Two rules drift one sentence at a time, and neither is visible in a diff:

1. **`README.md` is present tense.** It describes how the tool works *now*.
   History belongs in `DECISIONS.md`, which is why that file exists. Left
   alone, the README silently becomes a changelog — "this was tested and
   rejected", "two corpora were deleted in September", "the label set swung
   across three revisions" — none of which helps a reader work out what the
   thing currently does.

2. **Every filename and flag in the README exists.** A README naming a
   script that was renamed is worse than one that never mentioned it.

`DECISIONS.md` is deliberately exempt from the first rule: it is a
time-ordered record and past tense is correct there.

Usage:
    python check_docs.py            # report and exit non-zero on problems
    python check_docs.py --quiet    # for a git hook
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from rich.console import Console

console = Console()

PRESENT_TENSE_FILES = ("README.md",)

# Phrases that almost always mean a changelog sentence has crept in. Chosen
# to be high-signal: a plain "was" is often legitimate ("what it was for"),
# so this matches constructions that narrate a change instead.
HISTORICAL = [
    (r"\bused to\b", "narrates a past state"),
    (r"\bno longer\b", "narrates a change"),
    (r"\bpreviously\b", "narrates a change"),
    (r"\bformerly\b", "narrates a change"),
    (r"\boriginally\b", "narrates a change"),
    (r"\bat first\b", "narrates a change"),
    (r"\bfirst attempt\b", "narrates a change"),
    (r"\bturned out\b", "narrates a discovery"),
    (r"\bwas (tested|built|removed|deleted|rejected|added|chosen|written)\b",
     "past-tense narration"),
    (r"\bwere (tested|built|removed|deleted|rejected|added|measured|chosen)\b",
     "past-tense narration"),
    (r"\b(has|have) been (corrected|removed|deleted|rejected|revised)\b",
     "past-tense narration"),
    (r"\bacross (two|three|four|several) revisions\b", "narrates history"),
    (r"\b(January|February|March|April|May|June|July|August|September|"
     r"October|November|December)\s+20\d{2}\b", "a date belongs in DECISIONS.md"),
    (r"\bin 20\d{2}\b", "a date belongs in DECISIONS.md"),
]

SCRIPT = re.compile(r"\b([a-z][a-z0-9_]*\.py)\b")
MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.M)
CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)


def anchor(heading: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")


def check_tense(path: Path, problems: list) -> None:
    text = path.read_text()
    # Code blocks and blockquote pointers to the history files are exempt.
    scrubbed = CODE_FENCE.sub("", text)
    for number, line in enumerate(scrubbed.splitlines(), start=1):
        if line.lstrip().startswith(">"):
            continue
        for pattern, why in HISTORICAL:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                problems.append(
                    (path.name, number, f"{match.group(0)!r} — {why}", line.strip())
                )


def check_references(path: Path, problems: list) -> None:
    text = path.read_text()
    root = Path(".")

    for name in sorted(set(SCRIPT.findall(text))):
        if not (root / name).exists() and not (root / "redactor" / name).exists():
            problems.append((path.name, 0, f"names {name}, which does not exist", ""))

    headings = {anchor(h) for h in HEADING.findall(text)}
    for label, target in MD_LINK.findall(text):
        if target.startswith("#"):
            if target[1:] not in headings:
                problems.append((path.name, 0, f"broken anchor {target}", label))
        elif not target.startswith(("http://", "https://", "ftp://", "mailto:")):
            if not (root / target.split("#")[0]).exists():
                problems.append((path.name, 0, f"broken link {target}", label))


def check_scripts_documented(path: Path, problems: list) -> None:
    """A script nobody can find is a script nobody runs."""
    text = path.read_text()
    for script in sorted(p.name for p in Path(".").glob("*.py")):
        if script == "check_docs.py":
            continue
        if script not in text:
            problems.append(
                (path.name, 0, f"{script} exists but is not documented", "")
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true",
                        help="print only problems, for a git hook")
    args = parser.parse_args()

    problems: list = []
    for name in PRESENT_TENSE_FILES:
        path = Path(name)
        if not path.exists():
            problems.append((name, 0, "missing", ""))
            continue
        check_tense(path, problems)
        check_references(path, problems)
        check_scripts_documented(path, problems)

    if not problems:
        if not args.quiet:
            console.print("[green]Docs check passed.[/green] README is present "
                          "tense, every reference resolves, every script documented.")
        return 0

    console.print(f"[red]{len(problems)} documentation problem(s):[/red]\n")
    for filename, line, what, context in problems:
        where = f"{filename}:{line}" if line else filename
        console.print(f"  [cyan]{where}[/cyan]  {what}")
        if context:
            console.print(f"      [dim]{context[:110]}[/dim]")
    console.print(
        "\n[yellow]README.md describes how the tool works now. History goes in "
        "DECISIONS.md — append there rather than narrating in the README.[/yellow]"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

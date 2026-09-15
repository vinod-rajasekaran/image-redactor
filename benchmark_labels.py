#!/usr/bin/env python3
"""Score the label lexicon against IndiaPII-Bench — independent Indian forms.

`redactor/labels.py` has two halves that fail independently:

- the **lexicon**: does it recognise a label as introducing personal data?
- the **geometry**: does it pair that label with the right value on a page?

The geometry half needs annotated document images, which do not exist for
Indian forms under any permissive licence — the cheques are the only
independent image corpus this project has. The lexicon half needs only
label/value text, and IndiaPII-Bench is exactly that: **2,000 Indian forms
written by someone else**, every one of them in `Label: Value` layout,
with character offsets marking the personal data.

That makes this the only independent test of the lexicon available, and
the reason the file exists. It measures both directions:

- **recall** — of the PII values that follow a label, how many labels do we
  recognise. A miss here is a value the redactor will never anchor on.
- **precision** — of the labels we match, how many actually introduce PII.
  A false positive is over-redaction, which this project prefers to a
  miss, but not for free: covering a branch code is harmless, covering a
  whole page is not.

Usage:
    python benchmark_labels.py
    python benchmark_labels.py --misses 40   # show more blind spots
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from rich.console import Console
from rich.table import Table

from redactor import datasets
from redactor.labels import is_pii_label, normalise

console = Console()
DATASET = datasets.ROOT / "text" / "indiapii-v1.0.jsonl"

# A "Label: Value" line. The label is bounded to keep a sentence containing
# a colon from being read as one, and must contain a letter so that a clock
# time ("14:30") is not mistaken for a labelled field — that artifact alone
# accounted for 1,140 spurious rows in the first version of this analysis.
LINE = re.compile(r"^\s*([^:\n]{2,40}?)\s*:\s*(\S.*)$")
HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def labelled_lines(text: str):
    """Yield (label, value start, value end) for every Label: Value line."""
    offset = 0
    for line in text.split("\n"):
        match = LINE.match(line)
        if match:
            label, value = match.group(1), match.group(2)
            if HAS_LETTER.search(label):
                start = offset + line.index(value, len(match.group(1)))
                yield label, start, start + len(value)
        offset += len(line) + 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--misses", type=int, default=20)
    parser.add_argument("--false-positives", type=int, default=15)
    args = parser.parse_args()

    if not DATASET.exists():
        console.print(f"[red]Missing {DATASET}[/red] — see benchmark_indiapii.py.")
        raise SystemExit(1)

    rows = [json.loads(l) for l in DATASET.read_text().splitlines()]

    hit = miss = 0
    true_pos = false_pos = 0
    missed_labels: collections.Counter = collections.Counter()
    false_labels: collections.Counter = collections.Counter()

    for row in rows:
        spans = [
            (e["start"], e["end"])
            for e in row["entities"]
            if e.get("value_class", "positive") == "positive"
        ]
        for label, start, end in labelled_lines(row["text"]):
            carries_pii = any(start <= s < end for s, _ in spans)
            matched = is_pii_label(label)

            if carries_pii:
                if matched:
                    hit += 1
                else:
                    miss += 1
                    missed_labels[normalise(label)] += 1
            if matched:
                if carries_pii:
                    true_pos += 1
                else:
                    false_pos += 1
                    false_labels[normalise(label)] += 1

    total_pii = hit + miss
    matched_total = true_pos + false_pos
    recall = hit / total_pii * 100 if total_pii else 0.0
    precision = true_pos / matched_total * 100 if matched_total else 0.0

    table = Table(title=f"Label lexicon vs IndiaPII-Bench ({len(rows)} independent forms)")
    table.add_column("measure", style="cyan")
    table.add_column("value", justify="right", style="bold")
    table.add_column("meaning")
    table.add_row("PII values after a label", str(total_pii), "the population")
    table.add_row("recall", f"{recall:.1f}%",
                  f"{hit} anchored, {miss} the redactor cannot reach this way")
    table.add_row("precision", f"{precision:.1f}%",
                  f"{false_pos} labels matched that carry no PII (over-redaction)")
    console.print(table)

    if missed_labels:
        console.print(f"\n[yellow]Blind spots — labels introducing PII that we miss:[/yellow]")
        for label, n in missed_labels.most_common(args.misses):
            console.print(f"  {n:5d}  {label}")
    if false_labels:
        console.print(f"\n[dim]Matched but carry no PII (over-redaction):[/dim]")
        for label, n in false_labels.most_common(args.false_positives):
            console.print(f"  {n:5d}  {label}")


if __name__ == "__main__":
    main()

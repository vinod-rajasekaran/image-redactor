#!/usr/bin/env python3
"""Pin the held-out rule: `holdout/` may be scored, never tuned against.

What is pinned here is the *rule*, not the corpus. A test asserting that
`holdout/` contains 71 items would pin an annotation set that is expected to
move as a person audits it. What must not move is which operations the guard
refuses, because the failure it prevents is invisible: a sweep over a held-out
corpus produces a number that looks exactly like the measurement it used to
be, and nothing in a diff shows that a test set became a training set.

The two directions both matter and the second is the one that rots quietly:

- the guard must REFUSE a sweep, by corpus name or by any path inside it
- the guard must NOT refuse loading or scoring — one run of an
  already-chosen configuration is the corpus's entire purpose, and a guard
  that broke scoring would be removed within a week

Run after touching `redactor/datasets.py` or the `_meta` of any corpus.

Usage:
    python test_holdout_guard.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rich.console import Console

from redactor import datasets

console = Console()

HELD_OUT = "holdout"
NOT_HELD_OUT = "documents"


def check(name: str, condition: bool, detail: str = "") -> bool:
    mark = "[green]PASS[/green]" if condition else "[red]FAIL[/red]"
    console.print(f"  {mark}  {name}" + (f" — {detail}" if detail else ""))
    return condition


def refuses(target) -> bool:
    try:
        datasets.refuse_if_tuning(target, purpose="test")
    except datasets.HeldOutCorpusError:
        return True
    return False


def test_corpus_is_marked_held_out() -> bool:
    meta = datasets._meta_of(HELD_OUT)
    return all(
        [
            check(
                "corpus exists",
                HELD_OUT in datasets.available(),
                f"available: {datasets.available()}",
            ),
            check("_meta marks it held_out", meta.get("held_out") is True),
            check("_meta forbids tuning", meta.get("tuning") == "forbidden"),
            check(
                "_meta states the rule in prose",
                "OCR" in meta.get("held_out_rule", ""),
                "a flag with no stated reason gets cleared by the next session",
            ),
            check(
                "held_out_names() reports it",
                HELD_OUT in datasets.held_out_names(),
            ),
        ]
    )


def test_refuses_tuning() -> bool:
    base = datasets.ROOT / HELD_OUT
    return all(
        [
            check("refuses the corpus name", refuses(HELD_OUT)),
            check("refuses the corpus directory", refuses(base)),
            check("refuses the images directory", refuses(base / "images")),
            check(
                "refuses a single image below it",
                refuses(base / "images" / "01_aadhaar_card.png"),
            ),
            check(
                "refuses a relative path",
                refuses(f"datasets/{HELD_OUT}/images"),
            ),
            check(
                "refuses a path with a trailing slash",
                refuses(f"datasets/{HELD_OUT}/images/"),
            ),
        ]
    )


def test_allows_everything_else() -> bool:
    return all(
        [
            check(
                f"does not refuse {NOT_HELD_OUT!r}",
                not refuses(NOT_HELD_OUT),
            ),
            check(
                f"does not refuse datasets/{NOT_HELD_OUT}/images",
                not refuses(f"datasets/{NOT_HELD_OUT}/images"),
            ),
            check(
                "does not refuse an unrelated path",
                not refuses("/tmp/some/user/images"),
            ),
            check(
                "does not refuse an unknown corpus name",
                not refuses("no_such_corpus"),
            ),
        ]
    )


def test_scoring_still_works() -> bool:
    """The corpus must stay loadable. A guard that blocks its own purpose dies."""
    corpus = datasets.load(HELD_OUT)
    images = list(corpus.items())
    return all(
        [
            check("load() succeeds", len(corpus) > 0, f"{len(corpus)} images"),
            check(
                "every annotated image is on disk",
                len(images) == len(corpus),
                f"{len(images)} of {len(corpus)} found",
            ),
            check(
                "items carry text for legibility scoring",
                all(
                    p.get("text")
                    for _, _, entry in images
                    for p in entry["pii"]
                ),
            ),
            check(
                "_meta states the corpus is not independent evidence",
                "NOT independent evidence"
                in datasets._meta_of(HELD_OUT).get("evidence_status", ""),
            ),
        ]
    )


def test_benchmark_ocr_refuses() -> bool:
    """The end-to-end path: the sweep script itself must exit non-zero.

    The timeout is not politeness. When this guard was first broken on
    purpose to check the test could fail, `benchmark_ocr.py` did what it is
    built to do — it started redacting the held-out corpus under six
    Tesseract configurations and had to be killed, leaving five run folders
    full of holdout output under names that said `bench_`. A test whose
    failure mode is a twenty-minute sweep over the corpus it exists to
    protect is not a safe test. Refusal is immediate, so anything slower than
    a few seconds has already failed.
    """
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "benchmark_ocr.py",
                "--input",
                f"datasets/{HELD_OUT}/images",
                "--quick",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return check(
            "benchmark_ocr.py refuses immediately",
            False,
            "it started the sweep instead of refusing — killed after 30s; "
            "check runs/ for holdout output written under bench_ names",
        )
    output = proc.stdout + proc.stderr
    return all(
        [
            check(
                "benchmark_ocr.py exits non-zero",
                proc.returncode != 0,
                f"exit {proc.returncode}",
            ),
            check("it says it refused", "refused" in output.lower()),
            check(
                "it names an alternative corpus",
                "documents" in output,
                "a refusal with no way forward gets worked around",
            ),
            check(
                "it ran nothing",
                "running" not in output.lower(),
                "the refusal must come before the first configuration",
            ),
        ]
    )


TESTS = [
    ("corpus is marked held out", test_corpus_is_marked_held_out),
    ("refuses tuning", test_refuses_tuning),
    ("allows everything else", test_allows_everything_else),
    ("scoring still works", test_scoring_still_works),
    ("benchmark_ocr.py refuses", test_benchmark_ocr_refuses),
]


def main() -> int:
    failed = []
    for title, fn in TESTS:
        console.print(f"[bold]{title}[/bold]")
        if not fn():
            failed.append(title)
        console.print()

    if failed:
        console.print(f"[red]FAILED[/red]: {', '.join(failed)}")
        return 1
    console.print("[green]All held-out guard checks passed.[/green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Evaluate our recognizer stack against IndiaPII-Bench (maskflow-ai).

The harness normally measures OCR and detection together, so a miss could
always be blamed on either. This benchmark is plain text, which isolates
the detection layer completely: anything missed here is a recognizer gap,
not a reading problem.

It also brings something our own ground truth lacks — **hard negatives**.
1,403 of its spans are PII-shaped decoys (order IDs shaped like PANs,
timestamps shaped like Aadhaars, emails shaped like UPI handles) that a
detector is expected *not* to flag. Our sample set has no decoys at all,
so it can only measure recall and is blind to over-redaction.

Dataset: https://huggingface.co/datasets/maskflow-ai/indiapii-bench
Licence: CC-BY-4.0. Download indiapii-v1.0.jsonl into benchmarks/.

Usage:
    python benchmark_indiapii.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()
DATASET = Path("benchmarks/indiapii-v1.0.jsonl")

# Their label -> the Presidio entity types we would accept as a hit.
LABEL_TO_OURS = {
    "PERSON_NAME": {"PERSON"},
    "INDIAN_MOBILE": {"PHONE_NUMBER"},
    "INDIAN_ADDRESS": {"LOCATION"},
    "BANK_ACCOUNT_IN": {"IN_BANK_ACCOUNT"},
    "IFSC": {"IN_IFSC"},
    "PAN": {"IN_PAN"},
    "AADHAAR": {"IN_AADHAAR"},
    "AADHAAR_MASKED": {"IN_AADHAAR"},
    "VEHICLE_REG": {"IN_VEHICLE_REGISTRATION"},
    "DRIVING_LICENCE": {"IN_DRIVING_LICENCE"},
    "VOTER_ID": {"IN_VOTER"},
    "GSTIN": {"IN_GSTIN"},
    "INDIAN_PASSPORT": {"IN_PASSPORT"},
    # No recognizer of ours claims these at all.
    "PIN_CODE": set(),
    "UPI_VPA": set(),
    "ABHA_NUMBER": set(),
    "ABHA_ADDRESS": set(),
}


def build_text_analyzer(logger):
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
    from presidio_analyzer import predefined_recognizers

    from custom_recognizers import build_custom_recognizers
    from evaluate_redactor import (
        INDIA_RECOGNIZER_NAMES,
        build_aadhaar_ocr_fallback_recognizer,
    )

    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()
    for name in INDIA_RECOGNIZER_NAMES:
        registry.add_recognizer(getattr(predefined_recognizers, name)())
    for recognizer in build_custom_recognizers():
        registry.add_recognizer(recognizer)
    registry.add_recognizer(build_aadhaar_ocr_fallback_recognizer())
    return AnalyzerEngine(registry=registry)


# Each decoy mimics a specific real entity. Flagging it as *that* type is
# the error the benchmark probes. Flagging a timestamp as DATE_TIME is a
# different thing — over-redaction, but not the confusion being tested.
DECOY_MIMICS = {
    "NON_VERHOEFF_AADHAAR_SHAPED": {"IN_AADHAAR"},
    "PAN_SHAPED_INVOICE_NO": {"IN_PAN"},
    "VPA_SHAPED_EMAIL": {"EMAIL_ADDRESS"},
    "ORDER_ID_SHAPED": {"IN_AADHAAR", "IN_BANK_ACCOUNT"},
    "TIMESTAMP_SHAPED": {"IN_AADHAAR", "IN_BANK_ACCOUNT"},
}


def overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--threshold", type=float, default=0.4)
    args = parser.parse_args()

    if not DATASET.exists():
        console.print(f"[red]Missing {DATASET}[/red] — download it first.")
        raise SystemExit(1)

    logging.basicConfig(level=logging.CRITICAL)
    analyzer = build_text_analyzer(logging.getLogger("bench"))

    rows = [json.loads(line) for line in DATASET.open()]
    if args.limit:
        rows = rows[: args.limit]

    per_label = defaultdict(lambda: {"total": 0, "hit": 0})
    decoys = defaultdict(lambda: {"total": 0, "flagged": 0, "mimic": 0})
    spurious = 0
    detections_total = 0

    for row in rows:
        results = analyzer.analyze(
            text=row["text"], language="en", score_threshold=args.threshold
        )
        detections_total += len(results)
        positives = [e for e in row["entities"] if e["value_class"] == "positive"]

        for entity in row["entities"]:
            # For a decoy, any detection at all is the error, whatever type
            # it was called — the span should have been left alone.
            hit = any(
                overlaps(entity["start"], entity["end"], r.start, r.end)
                for r in results
            )
            if entity["value_class"] == "positive":
                accepted = LABEL_TO_OURS.get(entity["label"], set())
                typed_hit = any(
                    overlaps(entity["start"], entity["end"], r.start, r.end)
                    and (not accepted or r.entity_type in accepted)
                    for r in results
                )
                per_label[entity["label"]]["total"] += 1
                per_label[entity["label"]]["hit"] += typed_hit
            else:
                mimic = DECOY_MIMICS.get(entity["label"], set())
                as_mimic = any(
                    overlaps(entity["start"], entity["end"], r.start, r.end)
                    and r.entity_type in mimic
                    for r in results
                )
                decoys[entity["label"]]["total"] += 1
                decoys[entity["label"]]["flagged"] += hit
                decoys[entity["label"]]["mimic"] += as_mimic

        for r in results:
            if not any(
                overlaps(p["start"], p["end"], r.start, r.end) for p in positives
            ):
                spurious += 1

    table = Table(title=f"IndiaPII-Bench — recall by entity ({len(rows)} docs)")
    table.add_column("their label", style="cyan")
    table.add_column("our entity")
    table.add_column("n", justify="right")
    table.add_column("found", justify="right")
    table.add_column("recall %", justify="right", style="bold")
    tot = hit = 0
    for label, c in sorted(per_label.items(), key=lambda kv: -kv[1]["total"]):
        accepted = LABEL_TO_OURS.get(label, set())
        ours = ", ".join(sorted(accepted)) if accepted else "[red]none[/red]"
        table.add_row(
            label, ours, str(c["total"]), str(c["hit"]),
            f"{c['hit'] / c['total'] * 100:.0f}" if c["total"] else "-",
        )
        tot += c["total"]
        hit += c["hit"]
    console.print(table)

    dtable = Table(title="Hard negatives — PII-shaped decoys we should NOT flag")
    dtable.add_column("decoy", style="cyan")
    dtable.add_column("n", justify="right")
    dtable.add_column("as the mimicked type", justify="right", style="red")
    dtable.add_column("flagged as anything", justify="right", style="yellow")
    dt = df = dm = 0
    for label, c in sorted(decoys.items(), key=lambda kv: -kv[1]["mimic"]):
        dtable.add_row(
            label, str(c["total"]),
            f"{c['mimic']} ({c['mimic'] / c['total'] * 100:.0f}%)" if c["total"] else "-",
            f"{c['flagged']} ({c['flagged'] / c['total'] * 100:.0f}%)" if c["total"] else "-",
        )
        dt += c["total"]
        df += c["flagged"]
        dm += c["mimic"]
    console.print(dtable)

    console.print(
        f"\n[bold]Recall on real PII: {hit / tot * 100:.1f}%[/bold] ({hit}/{tot})\n"
        f"[red]Decoys flagged as the type they mimic: {dm}/{dt} "
        f"({dm / dt * 100:.0f}%)[/red]   "
        f"[yellow]flagged as anything: {df}/{dt}[/yellow]\n"
        f"[yellow]Detections not matching any labelled PII: {spurious}[/yellow] "
        f"of {detections_total}"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Load synthetic Indian cheques and score redaction coverage on them.

Dataset: https://huggingface.co/datasets/jaganadhg/cheque-synthetic-images
Licence: Apache-2.0. Fully synthetic — no real account holders.

Why this dataset earns a place. Every other test image here was labelled
by this project, so the labels share whatever the tool is blind to. These
carry **human-authored bounding boxes** from an unrelated group, which
buys two things we could not get otherwise:

- independent ground truth
- a *coverage* metric. Per-region coverage was built once from
  vision-generated boxes and removed, because those were off by about a
  text row and reported 0% for a field that was plainly blacked out.
  These boxes are trustworthy, so the measurement means something.

Coverage answers a different question from `score_run.py` and does not
replace it: "how much of this region did the redactor cover" rather than
"can the PII still be read". A region at 85% can still leak, which is why
the legibility score stays the headline — but a region well under 100% is
a concrete, deterministic warning with no model call involved.

Three of the six annotated fields are personal data by this project's
definition: the payee name, the account number, and the signature. IFSC
identifies a branch rather than a person, and the date and amount identify
nobody — all three are excluded, consistent with `build_ground_truth.py`.

Ten of these cheques are committed under `datasets/cheques/`, all four
bank layouts, so scoring needs no download. Fetching is only for a larger
slice; it overwrites the committed annotations, so `git checkout` the
corpus afterwards if you want the tracked set back.

Usage:
    python cheque_benchmark.py --score runs/cheques # coverage for a run
    python cheque_benchmark.py --limit 40           # fetch a larger slice
"""
from __future__ import annotations

import argparse
import io
import json
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image
from redactor import datasets
from rich.console import Console
from rich.table import Table

console = Console()

PARQUET_URL = (
    "https://huggingface.co/datasets/jaganadhg/cheque-synthetic-images/"
    "resolve/main/data/test-00000-of-00001.parquet"
)
# A download cache, not a corpus — the 10 cheques it unpacks to are
# committed. It lived under datasets/text/ once, where 95MB of PNG bytes
# in a folder named for text corpora was both misleading and the only
# reason that folder was excluded from git.
CACHE = datasets.ROOT / ".cache" / "cheques_test.parquet"
IMAGE_DIR = datasets.ROOT / "cheques" / "images"
REGIONS = datasets.ROOT / "cheques" / "annotations.json"

# field -> (our entity type, tier). Only fields that identify a person.
PII_FIELDS = {
    "name": ("PERSON", "core"),
    "acno": ("IN_BANK_ACCOUNT", "core"),
    "sign": (None, "core"),  # a signature is personal data; no recognizer
}
# Present in the annotations, deliberately not counted.
IGNORED_FIELDS = {"ifsc", "date", "amount"}

# A pixel counts as covered when it differs this much from the original,
# summed across channels. Anything the redactor drew over clears it easily.
CHANGED_THRESHOLD = 30


def fetch(limit: int) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not CACHE.exists():
        console.print(f"Downloading {PARQUET_URL.rsplit('/', 1)[-1]} ...")
        urllib.request.urlretrieve(PARQUET_URL, CACHE)

    import pyarrow.parquet as pq

    rows = pq.read_table(CACHE).to_pylist()[:limit]
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    regions: dict[str, list[dict]] = {}

    for row in rows:
        # Stored as JPEG q95 to match the committed corpus: the source PNGs
        # are 4.4MB each. Re-encoding is visible to OCR even though it is
        # invisible to the coverage metric, so a refetch must not quietly
        # produce a different-format corpus from the one measured.
        name = Path(row["filename"]).with_suffix(".jpg").name
        Image.open(io.BytesIO(row["image"]["bytes"])).convert("RGB").save(
            IMAGE_DIR / name, format="JPEG", quality=95, subsampling=0,
            optimize=True,
        )
        items = []
        for field, (entity, tier) in PII_FIELDS.items():
            box = row.get(field)
            if not box:
                continue
            items.append(
                {
                    "field": field,
                    "expected_type": entity,
                    "tier": tier,
                    "box": [box["xmin"], box["ymin"], box["xmax"], box["ymax"]],
                }
            )
        regions[name] = {"pii": items}
        console.print(f"{name:30s} {row['bank']:12s} {len(items)} PII regions")

    # Keep whatever `_meta` the tracked corpus carries — the licence and
    # provenance live there, and a fetch used to overwrite them away.
    meta = json.loads(REGIONS.read_text()).get("_meta", {}) if REGIONS.exists() else {}
    datasets.save("cheques", regions, meta)
    console.print(
        f"\n[green]{len(rows)} cheques -> {IMAGE_DIR}/[/green]  "
        f"regions -> {REGIONS}\n"
        f"Now run: [bold]python evaluate_redactor.py --input {IMAGE_DIR} "
        f"--run-name cheques[/bold]"
    )


def coverage(original: Path, redacted: Path, box) -> float:
    a = np.asarray(Image.open(original).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(redacted).convert("RGB"), dtype=np.int16)
    if a.shape != b.shape:
        return float("nan")
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(a.shape[1], x1), min(a.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        return float("nan")
    patch = np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).sum(axis=2)
    return float((patch > CHANGED_THRESHOLD).mean())


def score(run_dir: Path) -> None:
    if not REGIONS.exists():
        console.print(f"[red]{REGIONS} missing — run without --score first.[/red]")
        raise SystemExit(1)

    regions = {k: v["pii"] if isinstance(v, dict) else v
               for k, v in json.loads(REGIONS.read_text()).items()
               if not k.startswith("_")}
    images = run_dir / "images"
    table = Table(title=f"Cheque region coverage — {run_dir}")
    table.add_column("cheque", style="cyan")
    table.add_column("field")
    table.add_column("entity")
    table.add_column("covered", justify="right")

    by_field: dict[str, list[float]] = {}
    uncovered = 0
    scored = 0
    for name, items in sorted(regions.items()):
        redacted = images / name
        if not redacted.exists():
            continue
        for item in items:
            ratio = coverage(IMAGE_DIR / name, redacted, item["box"])
            if ratio != ratio:
                continue
            scored += 1
            by_field.setdefault(item["field"], []).append(ratio)
            if ratio >= 0.99:
                continue
            uncovered += 1
            style = "red" if ratio < 0.5 else "yellow"
            table.add_row(
                name,
                item["field"],
                item["expected_type"] or "(no recognizer)",
                f"[{style}]{ratio * 100:.0f}%[/{style}]",
            )
    console.print(table)

    summary = Table(title="Mean coverage by field")
    summary.add_column("field", style="cyan")
    summary.add_column("entity")
    summary.add_column("n", justify="right")
    summary.add_column("mean covered", justify="right", style="bold")
    for field, values in sorted(by_field.items()):
        entity = PII_FIELDS[field][0] or "(no recognizer)"
        summary.add_row(
            field, entity, str(len(values)),
            f"{sum(values) / len(values) * 100:.0f}%",
        )
    console.print(summary)
    console.print(
        f"\n[bold]{scored - uncovered}/{scored} regions fully covered[/bold] — "
        "coverage is a warning signal, not a leak verdict; "
        "use score_run.py for whether the PII is still readable"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--score", default=None, metavar="RUN_DIR")
    args = parser.parse_args()

    if args.score:
        score(Path(args.score))
    else:
        fetch(args.limit)


if __name__ == "__main__":
    main()

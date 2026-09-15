#!/usr/bin/env python3
"""Load synthetic Indonesian ID cards and score region coverage on them.

Dataset: https://huggingface.co/datasets/cloverx-id/indonesian-id-card-dummy
Licence: CC-BY-4.0. Fully synthetic "dummy" cards — no real cardholders.

**Why an Indonesian corpus is in an Indian-document project.** The
label-anchored detector has two halves that fail independently: a *lexicon*
(is this label introducing personal data?) which is locale-dependent, and
the *geometry* (is the value beside that label boxed correctly?) which is
not. The lexicon is already measured on 2,000 independent Indian forms.
The geometry had **no real-page evidence at all** — only OCR dictionaries
written by hand in `test_labels.py` — because no annotated Indian form
corpus exists that is both permissively licensed and safe to use.

These cards close that gap. They carry **publisher-authored per-field
boxes**, which is the only circumstance in which coverage means anything
here: the same metric computed from vision-generated boxes was built,
measured and deleted for sitting about a text row off. And structurally a
KTP is an Aadhaar card — national ID number, name, date of birth, address
— so the layout being tested is the layout that matters.

What it cannot test: Devanagari, handwriting, or Indian form conventions.
Those stay open in `VALIDATION.md`.

**Not committed.** CC-BY-4.0 permits redistribution with attribution, but
this project commits only MIT/Apache corpora, so these are fetched on
demand — the same treatment IndiaPII-Bench gets.

Usage:
    python ktp_benchmark.py --limit 20            # fetch + build the corpus
    python evaluate_redactor.py --input datasets/ktp/images --run-name ktp
    python ktp_benchmark.py --score runs/ktp      # coverage per field
"""
from __future__ import annotations

import argparse
import io
import json
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image
from rich.console import Console
from rich.table import Table

from redactor import datasets

console = Console()

PARQUET_URL = (
    "https://huggingface.co/datasets/cloverx-id/indonesian-id-card-dummy/"
    "resolve/main/data/flat/train-00000-of-00012.parquet"
)
CACHE = datasets.ROOT / ".cache" / "ktp_flat_000.parquet"
CORPUS = "ktp"

# The dataset's own `label` -> (our entity, tier). Applying this project's
# settled policy rather than inventing one: a bare gender, marital status,
# occupation or nationality identifies nobody and is not counted, exactly as
# gender is excluded from the documents corpus. Religion and blood type are
# special-category data about a person and are counted as sensitive.
PII_LABELS: dict[str, tuple[str | None, str]] = {
    "id_number": ("IN_AADHAAR", "core"),   # a KTP's NIK is its Aadhaar analogue
    "name": ("PERSON", "core"),
    "birth_info": ("DATE_TIME", "core"),
    "address": ("LOCATION", "core"),
    "religion": (None, "sensitive"),
    "blood_type": (None, "sensitive"),
}
# Present in the annotations and deliberately not scored.
IGNORED_LABELS = {
    "gender", "marital_status", "occupation", "nationality",
    "expiry_date", "issue_city", "issue_date", "header",
}
# Visual regions, scored separately: these test the face and signature
# detectors rather than the text path.
VISUAL_KEYS = {"PHOTO_AREA": "face", "SIGNATURE_AREA": "signature"}

CHANGED_THRESHOLD = 30   # same as the cheque benchmark, for comparability


def fetch(limit: int) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not CACHE.exists():
        console.print(f"Downloading {PARQUET_URL.rsplit('/', 1)[-1]} (~600MB) ...")
        urllib.request.urlretrieve(PARQUET_URL, CACHE)

    import pyarrow.parquet as pq

    rows = pq.read_table(CACHE).slice(0, limit).to_pylist()
    images = datasets.ROOT / CORPUS / "images"
    images.mkdir(parents=True, exist_ok=True)

    annotations: dict = {}
    for row in rows:
        name = row["image_name"]
        Image.open(io.BytesIO(row["image"]["bytes"])).convert("RGB").save(images / name)

        raw = row["annotations_json"]
        ann = json.loads(raw) if isinstance(raw, str) else raw
        fields = ann.get("text_fields", {})

        pii, visual = [], {"face": 0, "qr_code": 0, "barcode": 0, "signature": 0}
        for key, field in fields.items():
            if key in VISUAL_KEYS:
                visual[VISUAL_KEYS[key]] += 1
                continue
            label = field.get("label")
            if label not in PII_LABELS:
                continue
            entity, tier = PII_LABELS[label]
            pii.append(
                {
                    "field": label,
                    "expected_type": entity,
                    "tier": tier,
                    "text": field.get("text", ""),
                    "box": [int(v) for v in field["bounding_box"]],
                }
            )
        annotations[name] = {
            "pii": pii,
            "visual": {k: v for k, v in visual.items() if k != "signature"},
            "notes": f"indonesian KTP; {visual['signature']} signature area(s)",
        }

    meta = {
        "description": (
            f"{len(rows)} synthetic Indonesian national ID cards (KTP), "
            "with publisher-authored per-field bounding boxes."
        ),
        "source": "https://huggingface.co/datasets/cloverx-id/indonesian-id-card-dummy",
        "licence": "CC-BY-4.0 — attribution to cloverx-id. Not committed to this "
                   "repository, which tracks only MIT/Apache corpora; fetched on "
                   "demand by ktp_benchmark.py.",
        "provenance": "Publisher-declared synthetic 'dummy' data, tagged "
                      "dynamic-anonymization. No real cardholders.",
        "annotation": "box + text. Boxes are the publishers', not this project's, "
                      "which is what makes coverage meaningful here.",
        "purpose": "The only real-page test of the label-anchored detector's "
                   "geometry. Locale-independent by design: the lexicon half is "
                   "measured separately on Indian text.",
    }
    datasets.save(CORPUS, annotations, meta)
    items = sum(len(e["pii"]) for e in annotations.values())
    console.print(
        f"\n[green]{len(rows)} cards, {items} PII regions -> "
        f"{datasets.ROOT / CORPUS}/[/green]\n"
        f"Now run: [bold]python evaluate_redactor.py "
        f"--input {datasets.ROOT / CORPUS}/images --run-name ktp[/bold]"
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
    corpus = datasets.load(CORPUS)
    images = run_dir / "images"
    by_field: dict[str, list[float]] = {}
    scored = fully = 0

    for name, path, entry in corpus.items():
        redacted = images / name
        if not redacted.exists():
            continue
        for item in entry["pii"]:
            ratio = coverage(path, redacted, item["box"])
            if ratio != ratio:
                continue
            scored += 1
            fully += ratio >= 0.99
            by_field.setdefault(item["field"], []).append(ratio)

    if not scored:
        console.print(f"[red]Nothing scored — is {images} populated?[/red]")
        raise SystemExit(1)

    table = Table(title=f"Indonesian KTP region coverage — {run_dir}")
    table.add_column("field", style="cyan")
    table.add_column("entity")
    table.add_column("n", justify="right")
    table.add_column("mean covered", justify="right", style="bold")
    table.add_column("fully", justify="right")
    for field, values in sorted(by_field.items(), key=lambda kv: -len(kv[1])):
        entity = PII_LABELS[field][0] or "(no recognizer)"
        table.add_row(
            field, entity, str(len(values)),
            f"{sum(values) / len(values) * 100:.0f}%",
            str(sum(v >= 0.99 for v in values)),
        )
    console.print(table)
    console.print(
        f"\n[bold]{fully}/{scored} regions fully covered[/bold] — coverage is a "
        "warning signal, not a leak verdict; use vision_score.py for whether the "
        "PII is still readable.\n"
        "[dim]Indonesian labels against an English/Devanagari lexicon: a low "
        "score here may be the lexicon rather than the geometry. Compare against "
        "the lexicon-coverage line printed by --diagnose.[/dim]"
    )


def diagnose() -> None:
    """Separate the two failure modes before anyone reads a score as geometry."""
    from redactor.labels import is_pii_label

    corpus = datasets.load(CORPUS)
    # The printed labels on a KTP, in Indonesian.
    printed = {
        "id_number": "NIK", "name": "Nama", "birth_info": "Tempat/Tgl Lahir",
        "address": "Alamat", "religion": "Agama", "blood_type": "Gol. Darah",
    }
    table = Table(title="Lexicon coverage on Indonesian labels")
    table.add_column("field", style="cyan")
    table.add_column("printed label")
    table.add_column("recognised?", justify="right", style="bold")
    known = 0
    for field, label in printed.items():
        hit = is_pii_label(label)
        known += hit
        table.add_row(field, label, "yes" if hit else "[red]no[/red]")
    console.print(table)
    console.print(
        f"\n[bold]{known}/{len(printed)} Indonesian labels are in the "
        f"lexicon.[/bold] Labels the lexicon does not know cannot be anchored, "
        "so the geometry is untested on those fields regardless of what the "
        "coverage score says."
    )
    console.print(f"[dim]{len(corpus)} cards loaded.[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--score", default=None, metavar="RUN_DIR")
    parser.add_argument("--diagnose", action="store_true",
                        help="report lexicon coverage on Indonesian labels, so a "
                             "coverage score is not misread as a geometry result")
    args = parser.parse_args()

    if args.diagnose:
        diagnose()
    elif args.score:
        score(Path(args.score))
    else:
        fetch(args.limit)


if __name__ == "__main__":
    main()

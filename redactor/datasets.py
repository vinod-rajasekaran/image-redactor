"""Validation corpora, in one place with one annotation schema.

Every image this project validates against lives under `datasets/`, with
its annotations beside it. Before this, three corpora sat in three
top-level folders with three near-identical schemas — one carrying `text`
but no `box`, the others the reverse — and every script hardcoded its own
paths. Adding a fourth meant touching each of them.

**The annotation schema**, one JSON file per corpus, keyed by filename:

    {
      "<image file>": {
        "pii": [
          {
            "field":         where it came from on the page,
            "expected_type": the Presidio entity, or null if none covers it,
            "tier":          "core" | "sensitive",
            "text":          the value, when known,
            "box":           [x0, y0, x1, y1], when known
          }
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes":  free text
      }
    }

`text` and `box` are both optional and at least one is always present,
because they answer different questions. `text` supports legibility
scoring — is the PII still readable — which is the headline metric. `box`
supports coverage — how much of the region was painted over — which is
weaker but deterministic and needs no model. A generator that knows both
should emit both.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "datasets"


@dataclass
class Corpus:
    name: str
    images: Path
    annotations: dict
    meta: dict

    def __len__(self) -> int:
        return len(self.annotations)

    def items(self):
        """(filename, image path, annotation) for images that exist."""
        for filename, entry in sorted(self.annotations.items()):
            path = self.images / filename
            if path.exists():
                yield filename, path, entry

    def pii(self, filename: str) -> list[dict]:
        return self.annotations.get(filename, {}).get("pii", [])


def available() -> list[str]:
    if not ROOT.exists():
        return []
    return sorted(
        p.name for p in ROOT.iterdir() if (p / "annotations.json").exists()
    )


def load(name: str) -> Corpus:
    """Load one corpus by folder name."""
    base = ROOT / name
    path = base / "annotations.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No corpus {name!r} under {ROOT}. Available: {available() or 'none'}"
        )
    raw = json.loads(path.read_text())
    meta = raw.pop("_meta", {})
    return Corpus(name=name, images=base / "images", annotations=raw, meta=meta)


def save(name: str, annotations: dict, meta: dict | None = None) -> Path:
    """Write a corpus annotation file, keeping `_meta` first."""
    base = ROOT / name
    base.mkdir(parents=True, exist_ok=True)
    (base / "images").mkdir(exist_ok=True)
    payload = {"_meta": meta or {}, **annotations}
    path = base / "annotations.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path

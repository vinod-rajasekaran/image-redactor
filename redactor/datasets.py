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


class HeldOutCorpusError(RuntimeError):
    """Raised when a held-out corpus is about to be used for tuning.

    A held-out corpus answers one question — how well does the configuration
    we already chose do on documents it has never seen — and it can answer it
    exactly once per configuration. Sweeping configurations over it and
    keeping the winner converts a test set into a training set silently: the
    images do not change, the annotations do not change, and the number that
    comes out looks like the same measurement it was before. Nothing in a
    diff shows it. Hence a refusal rather than a comment.
    """


def _meta_of(name: str) -> dict:
    """Read one corpus's `_meta` without loading its annotations."""
    path = ROOT / name / "annotations.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text()).get("_meta", {})
    except (OSError, json.JSONDecodeError):
        return {}


def held_out_names() -> list[str]:
    """Corpora whose `_meta` marks them held out from tuning."""
    return [n for n in available() if _meta_of(n).get("held_out")]


def _corpus_for_path(target) -> str | None:
    """The corpus a filesystem path belongs to, if any."""
    try:
        resolved = Path(target).resolve()
    except (OSError, ValueError):
        return None
    for name in available():
        base = (ROOT / name).resolve()
        if resolved == base or resolved.is_relative_to(base):
            return name
    return None


def refuse_if_tuning(target, *, purpose: str) -> None:
    """Refuse `target` if it names or points inside a held-out corpus.

    `target` is a corpus name or a filesystem path, so this works for
    `load("holdout")` and for a `--input datasets/holdout/images` handed to a
    sweep. `purpose` is what the caller is about to do, and it lands in the
    message, because a refusal that does not say what it stopped just gets
    worked around.

    Call this from anything that *chooses* a parameter from a corpus's score.
    Do not call it from anything that merely scores: one run of an
    already-chosen configuration is what a held-out corpus is for.
    """
    name = target if target in available() else _corpus_for_path(target)
    if name is None:
        return
    meta = _meta_of(name)
    if not meta.get("held_out"):
        return
    rule = meta.get("held_out_rule", "")
    raise HeldOutCorpusError(
        f"{purpose} would tune against {name!r}, which is held out.\n\n"
        f"{rule}\n\n"
        f"Score it with a configuration chosen elsewhere, or sweep over a "
        f"corpus that is not held out: "
        f"{', '.join(n for n in available() if n not in held_out_names()) or 'none'}."
    )


class CorpusMismatchError(RuntimeError):
    """Raised when a run is about to be scored against the wrong corpus."""


def _keys_of(name: str) -> set[str]:
    path = ROOT / name / "annotations.json"
    try:
        return set(json.loads(path.read_text())) - {"_meta"}
    except (OSError, json.JSONDecodeError):
        return set()


def matching_corpus(filenames) -> str | None:
    """The corpus whose annotations cover the most of `filenames`."""
    best, best_n = None, 0
    for name in available():
        n = len(set(filenames) & _keys_of(name))
        if n > best_n:
            best, best_n = name, n
    return best


def check_run_matches(corpus: Corpus, images_dir, *, script: str) -> None:
    """Refuse to score a run whose images this corpus does not describe.

    Both scorers take their corpus from `REDACTOR_CORPUS` and default to
    `documents`, which is silent when it is wrong and only *mostly* wrong.
    A holdout run scored without the variable matched on one colliding
    filename and reported "4 redacted, 1 leaked" — a whole-corpus verdict
    shape, carrying one page's numbers, graded against a different
    document's ground truth. Nothing about that output says it is wrong.

    Filenames now differ per corpus, so that exact collision is gone; this
    catches the general case, where the answer is an error rather than a
    number nobody can tell is false.
    """
    files = {p.name for p in Path(images_dir).glob("*") if p.is_file()}
    if not files:
        return
    overlap = files & set(corpus.annotations)
    if len(overlap) * 2 >= len(files):
        return

    better = matching_corpus(files)
    hint = (
        f"\n  Those images look like corpus {better!r}. Re-run with "
        f"REDACTOR_CORPUS={better} {script} <run dir>."
        if better and better != corpus.name
        else "\n  No corpus here describes them. If this run is of your own "
        "images, score it against the annotations you wrote for them."
    )
    raise CorpusMismatchError(
        f"{script}: this run's images are not corpus {corpus.name!r}.\n"
        f"  {len(overlap)} of {len(files)} image(s) in {images_dir} appear in "
        f"{corpus.name!r}'s ground truth.{hint}"
    )

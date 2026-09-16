"""Protect clinical content from redaction, so a document stays usable.

**The problem.** A prescription passing to a downstream reader needs the
patient, doctor, hospital and signature covered and the medication and
dosage left alone. By default the opposite happens in places: on OCR'd
text spaCy tags `Atorvastatin` as `LOCATION` in one preprocessing variant
and as `ORGANIZATION` in another, both at 0.85, so the drug name is
blacked out while the plain variant reads it correctly.

**Why this uses a model and not a rule.** The obvious fix is a pattern —
"a word followed by a dose is a medication" — and it works on this
prescription. It is also exactly the mistake this project has made before:
seven recognizers were removed for encoding shapes invented here, which
matched the test data and nothing else. A dose-adjacency rule would fail
on a lab report, a discharge summary or a vaccination card, and would miss
`Vitamin D3 60K`, which carries no `mg`.

`MedicalNERRecognizer` carries real clinical vocabulary. It tags
`Metformin`, `Atorvastatin` and `Vitamin D3 60K` as medications, the
schedules as dosages, and `Type 2 Diabetes Mellitus` as a disorder —
while claiming neither `Priya Sharma` nor `R. Venkat`.

**What is deliberately not protected.** The same model tags
`Sundaram Medical Centre` as `NONBIOLOGICAL_LOCATION`; protecting that
would un-redact the hospital name. Medical *history* labels are excluded
for the same reason — a history can name a person or a place.

**Protection only removes NER-derived boxes.** A checksum-validated
Aadhaar or a label-anchored account number inside a clinical sentence
still gets covered: those are identifiers, and no amount of clinical
context makes them safe to leave.
"""
from __future__ import annotations

# Clinical content worth keeping. Everything the model can emit that is
# *about the condition or the treatment*, and nothing that can name a
# person or a place.
PROTECTED_LABELS = frozenset({
    "MEDICAL_MEDICATION",
    "DOSAGE",
    "MEDICAL_DISEASE_DISORDER",
    "MEDICAL_THERAPEUTIC_PROCEDURE",
    "MEDICAL_BIOLOGICAL_STRUCTURE",
    "MEDICAL_BIOLOGICAL_ATTRIBUTE",
    "MEDICAL_CLINICAL_EVENT",
    "SIGN_SYMPTOM",
    "SEVERITY",
    "LAB_VALUE",
    "DIAGNOSTIC_PROCEDURE",
    "DURATION",
    "FREQUENCY",
    "ADMINISTRATION",
})

# Only these box types can be withdrawn. A pattern or checksum recognizer
# is never overridden by clinical context.
SUPPRESSIBLE_TYPES = frozenset({"PERSON", "LOCATION", "ORGANIZATION", "NRP"})

# Below this the model is guessing, and what it guesses at is form
# vocabulary: on this corpus it tagged `PAN`, `Aadhaar`, `Passport`,
# `Blood Group` and `Health Insurance` as DIAGNOSTIC_PROCEDURE, all between
# 0.31 and 0.38, while every genuine clinical span scored 0.48 or better
# and the real vocabulary — `Metformin`, `Hemoglobin`, `TSH`, the dosages —
# scored 0.58 to 0.99. One threshold separates them, which is the whole
# reason to prefer a scored model here over a list of per-document rules.
MIN_SCORE = 0.5

# A box is withdrawn when this much of it lies inside protected text.
OVERLAP_TO_SUPPRESS = 0.5


_RECOGNIZER = None


def _build_recognizer():
    """The clinical model, loaded once per process.

    Building it per image loads a transformer from disk every time, which
    measured 3.5x the whole run's wall clock on 20 documents.
    """
    global _RECOGNIZER
    if _RECOGNIZER is None:
        from presidio_analyzer.predefined_recognizers import MedicalNERRecognizer

        _RECOGNIZER = MedicalNERRecognizer()
    return _RECOGNIZER


def protected_regions(ocr: dict, analyzer, scale: int = 1) -> list[tuple]:
    """Boxes covering clinical text, as (left, top, width, height).

    Reconstructs the page text from the OCR words, keeping each word's
    character offset, so a model span can be mapped back to the words it
    covers and then to their boxes.
    """
    words, text_parts, offsets = [], [], []
    cursor = 0
    for index, raw in enumerate(ocr.get("text", [])):
        token = (raw or "").strip()
        if not token:
            continue
        words.append(
            (
                int(ocr["left"][index]),
                int(ocr["top"][index]),
                int(ocr["width"][index]),
                int(ocr["height"][index]),
            )
        )
        offsets.append((cursor, cursor + len(token)))
        text_parts.append(token)
        cursor += len(token) + 1
    if not words:
        return []

    text = " ".join(text_parts)
    recognizer = _build_recognizer()
    artifacts = analyzer.nlp_engine.process_text(text, "en")
    try:
        results = recognizer.analyze(text, list(PROTECTED_LABELS), artifacts)
    except Exception:
        return []

    regions = []
    for result in results:
        if result.entity_type not in PROTECTED_LABELS or result.score < MIN_SCORE:
            continue
        covered = [
            words[i]
            for i, (start, end) in enumerate(offsets)
            if start < result.end and result.start < end
        ]
        if not covered:
            continue
        left = min(w[0] for w in covered)
        top = min(w[1] for w in covered)
        right = max(w[0] + w[2] for w in covered)
        bottom = max(w[1] + w[3] for w in covered)
        regions.append(
            (left // scale, top // scale,
             (right - left) // scale, (bottom - top) // scale)
        )
    return regions


def _overlap_fraction(box, region) -> float:
    bx, by, bw, bh = box
    rx, ry, rw, rh = region
    ix = max(0, min(bx + bw, rx + rw) - max(bx, rx))
    iy = max(0, min(by + bh, ry + rh) - max(by, ry))
    area = bw * bh
    return (ix * iy) / area if area else 0.0


def suppress(raw_boxes: list[tuple], regions: list[tuple]) -> tuple[list, int]:
    """Drop NER boxes that sit inside protected clinical text.

    `raw_boxes` are (entity_type, left, top, width, height). Returns the
    surviving boxes and how many were withdrawn.
    """
    if not regions:
        return raw_boxes, 0
    kept, dropped = [], 0
    for box in raw_boxes:
        entity_type, rest = box[0], box[1:]
        if entity_type in SUPPRESSIBLE_TYPES and any(
            _overlap_fraction(rest, region) >= OVERLAP_TO_SUPPRESS
            for region in regions
        ):
            dropped += 1
            continue
        kept.append(box)
    return kept, dropped

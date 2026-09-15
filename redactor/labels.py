"""Redact the value beside a personal-data label, whatever shape it has.

**Why this replaces six recognizers.** Those six encoded a *shape* for a
kind of identifier — a patient number, a PNR, a policy number, a survey
number — and every one of those shapes was invented by this project while
writing the test data it was then scored against. Four of the six never
fired once across 67 real generated pages, and the misses were exactly the
variants nobody thought of:

    Medical Record No.: MRN-458361    -> nothing   (pattern wanted AB1234567)
    Reg. No.: MMC/2010/06/12345       -> nothing   (pattern wanted MH/MED/2011/45892)
    Reg. No. : 63281                  -> nothing   (no shape at all)
    Customer ID : 100724681           -> nothing   (nobody wrote that one)

Shape-first detection cannot win this: every bank, hospital, registry and
RTO in India invents its own numbering, so the set of shapes is unbounded
and each new one needs new code. The *labels*, by contrast, are a small,
stable, well-documented set — a form says "Account Number" or "खाता संख्या"
because a person has to read it.

So this inverts the question. Instead of "does this token look like an
identifier?", it asks **"is this token sitting where a personal value
goes?"** — and redacts it without caring what it looks like.

**It uses geometry, not text adjacency.** Presidio's context boost works
on the flattened word string, so it depends on OCR emitting a label next
to its value. A two-column form breaks that, which is why the Aadhaar
fallback had to be made context-free. Every OCR word already carries a
box, so pairing by position is both more robust and information we were
throwing away.

Deliberately biased toward over-redaction: it fires on any value beside a
listed label, including the occasional non-personal one. A covered branch
code costs nothing; an uncovered customer ID is the failure this tool
exists to prevent.
"""
from __future__ import annotations

import re
import unicodedata

from .geometry import VisualRegion

# Labels whose value is personal data. Matched against the OCR text with
# punctuation and case normalised away, so "Account No.:" and "ACCOUNT NO"
# are the same key. Devanagari entries are here because real Indian forms
# print the label bilingually and the English half is not always the one
# OCR reads cleanly.
#
# A label earns a place when the value beside it identifies *a person*.
# Institutional fields — branch code, CIN, IFSC of the branch, helpline —
# are excluded: they identify an organisation, and this project has
# already ruled that an amount or a bare date identifies nobody.
PII_LABELS: tuple[str, ...] = (
    # who
    "name", "full name", "applicant name", "patient name", "account holder",
    "account holder name", "holder name", "complainant name", "informant name",
    "registered owner", "owner name", "father name", "fathers name",
    "father husband name", "husband name", "mother name", "spouse name",
    "guardian name", "nominee", "nominee name", "attending doctor",
    "consultant", "pathologist", "referred by", "signatory", "employee name",
    "नाम", "पिता का नाम", "पूरा नाम", "आवेदक का नाम",
    # where / how to reach
    "address", "residential address", "permanent address", "correspondence address",
    "property address", "communication address", "present address",
    "phone", "phone no", "mobile", "mobile no", "contact", "contact no",
    "contact number", "telephone", "email", "email id", "e mail",
    "पता", "मोबाइल", "दूरभाष",
    # account and customer identity
    "account no", "account number", "a c no", "ac no", "customer id",
    "customer no", "client id", "crn", "cif", "cif no", "folio no",
    "खाता संख्या", "ग्राहक संख्या",
    # government identity
    "aadhaar", "aadhaar no", "aadhaar number", "uid", "uid no", "vid",
    "pan", "pan no", "pan number", "passport no", "passport number",
    "voter id", "epic no", "driving licence", "driving license", "dl no",
    "licence no", "license no", "ration card", "ration card no",
    "आधार", "आधार संख्या",
    # health
    "patient id", "uhid", "mrn", "medical record no", "medical record number",
    "hospital no", "ip no", "op no", "opd no", "registration no",
    "reg no", "sample id", "specimen id", "lab no", "lab id",
    # case, policy, booking, property
    "policy no", "policy number", "claim no", "claim number",
    "fir no", "fir number", "case no", "complaint no", "diary no",
    "pnr", "pnr no", "booking ref", "booking reference", "ticket no",
    "survey no", "khasra no", "khata no", "khewat no", "dag no",
    "plot no", "document no", "deed no", "registration number",
    "सर्वे नंबर", "खसरा संख्या",
)

# Normalised for lookup once at import.
_NORMALISED_LABELS = frozenset(PII_LABELS)

# A label may be one to this many OCR words. Bounded so a whole sentence
# cannot be read as a label.
MAX_LABEL_WORDS = 4

# Geometry. A value sits on the label's row starting to its right, or in
# the cell directly beneath it. Expressed in multiples of the label's own
# height so they hold at any resolution.
SAME_ROW_TOLERANCE = 0.6      # vertical overlap needed to count as one row
MAX_GAP_RIGHT = 12.0          # how far right of the label a value may start
BELOW_MAX_DROP = 2.2          # how far beneath, for stacked label/value
BELOW_MAX_SHIFT = 1.0         # horizontal drift allowed for a value beneath

# A value may run to this many words. Addresses are long; a whole
# paragraph is not a field value.
MAX_VALUE_WORDS = 12

_PUNCT = re.compile(r"[^\w\sऀ-ॿ]+", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse spaces. Devanagari preserved."""
    text = unicodedata.normalize("NFKC", text)
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text).strip().lower()


def _words(ocr: dict) -> list[dict]:
    """OCR parallel lists -> a list of word dicts, blanks dropped."""
    out = []
    for i, raw in enumerate(ocr.get("text", [])):
        text = (raw or "").strip()
        if not text:
            continue
        out.append(
            {
                "text": text,
                "norm": normalise(text),
                "left": int(ocr["left"][i]),
                "top": int(ocr["top"][i]),
                "width": int(ocr["width"][i]),
                "height": int(ocr["height"][i]),
            }
        )
    return out


def _same_row(a: dict, b: dict) -> bool:
    """Do two words share a text row, by vertical overlap?"""
    top = max(a["top"], b["top"])
    bottom = min(a["top"] + a["height"], b["top"] + b["height"])
    overlap = bottom - top
    return overlap > SAME_ROW_TOLERANCE * min(a["height"], b["height"])


def find_labels(words: list[dict]) -> list[tuple[int, int, str]]:
    """Locate label phrases as (start index, end index exclusive, label).

    Longest match wins, so "account holder name" is not read as "name",
    and a matched span is not reconsidered.
    """
    found: list[tuple[int, int, str]] = []
    i = 0
    while i < len(words):
        match = None
        for span in range(min(MAX_LABEL_WORDS, len(words) - i), 0, -1):
            group = words[i : i + span]
            # A label does not wrap across rows.
            if any(not _same_row(group[0], w) for w in group[1:]):
                continue
            phrase = normalise(" ".join(w["text"] for w in group))
            if phrase in _NORMALISED_LABELS:
                match = (i, i + span, phrase)
                break
        if match:
            found.append(match)
            i = match[1]
        else:
            i += 1
    return found


def _value_words(words: list[dict], start: int, end: int) -> list[dict]:
    """The words forming the value for the label at [start:end).

    Prefers the same row to the right; falls back to the row beneath for
    stacked label/value layouts. Stops at the next label, so two adjacent
    fields do not merge into one box.
    """
    label = words[start]
    label_right = label["left"] + label["width"]
    height = max(label["height"], 1)

    right = [
        w for w in words[end:]
        if _same_row(label, w)
        and w["left"] >= label_right
        and w["left"] - label_right <= MAX_GAP_RIGHT * height
    ]
    if right:
        return right[:MAX_VALUE_WORDS]

    # The drift limit locates where the value *starts*; it must not then be
    # applied to the rest of the line, or a wrapped address is reduced to
    # its first word ("H.No." out of "H.No. 225, Bhopal").
    label_bottom = label["top"] + label["height"]
    candidates = [
        w for w in words[end:]
        if w["top"] >= label_bottom - 0.3 * height
        and w["top"] - label_bottom <= BELOW_MAX_DROP * height
    ]
    anchor = next(
        (w for w in candidates
         if abs(w["left"] - label["left"]) <= BELOW_MAX_SHIFT * height),
        None,
    )
    if anchor is None:
        return []
    row = [
        w for w in candidates
        if _same_row(anchor, w) and w["left"] >= anchor["left"]
    ]
    return row[:MAX_VALUE_WORDS]


def detect_labelled_values(ocr: dict, scale: int = 1) -> list[VisualRegion]:
    """Boxes covering the value beside every personal-data label found.

    `scale` divides the coordinates, matching the pipeline's upscale factor
    so boxes come back in original-image space.
    """
    words = _words(ocr)
    if not words:
        return []

    labels = find_labels(words)
    label_starts = {start for start, _, _ in labels}
    regions: list[VisualRegion] = []

    for start, end, _phrase in labels:
        value = _value_words(words, start, end)
        if not value:
            continue
        # Stop before the next label on the same row: on a two-column form
        # the next field's label would otherwise be swallowed as value.
        trimmed = []
        for word in value:
            index = words.index(word)
            if index in label_starts:
                break
            trimmed.append(word)
        if not trimmed:
            continue

        left = min(w["left"] for w in trimmed)
        top = min(w["top"] for w in trimmed)
        right = max(w["left"] + w["width"] for w in trimmed)
        bottom = max(w["top"] + w["height"] for w in trimmed)
        regions.append(
            VisualRegion(
                "labelled_value",
                left // scale,
                top // scale,
                (right - left) // scale,
                (bottom - top) // scale,
            )
        )
    return regions

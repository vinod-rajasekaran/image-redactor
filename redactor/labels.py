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

# Whether a label introduces personal data is decided on its **words**, not
# on the whole phrase. Exact-phrase matching was tried first and scored 43.5%
# recall against 2,000 independent Indian forms (IndiaPII-Bench), and the
# misses were not exotic vocabulary — they were morphology. The lexicon knew
# "mobile" but not "mobile number", "account number" but not "bank account
# number", "driving licence" but not "driving licence no". Enumerating every
# variant is the same losing game as enumerating every number format.
#
# So a label matches when it *contains* a term that marks personal data.
# `benchmark_labels.py` measures both directions against that corpus.

# Terms that identify a person on their own. Any one is sufficient.
STRONG_TERMS: frozenset[str] = frozenset({
    # government identity
    "aadhaar", "aadhar", "uid", "vid", "pan", "passport", "voter", "epic",
    "licence", "license", "dl", "ration", "abha", "gstin", "tan", "uan",
    # contact
    "mobile", "phone", "telephone", "email", "mail", "pin", "pincode",
    "postcode", "zip",
    # money
    "account", "acct", "ac", "iban", "upi", "vpa", "micr", "ifsc", "folio",
    "crn", "cif", "customer",
    # health
    "uhid", "mrn", "patient", "abha", "sample", "specimen", "lab",
    # case and booking
    "policy", "claim", "fir", "pnr", "ticket", "booking", "case",
    "complaint", "diary",
    # property
    "survey", "khasra", "khesra", "khata", "khatauni", "khewat", "dag",
    "jamabandi", "patta", "chitta", "pahani", "satbara", "plot", "deed",
    # vehicle
    "vehicle", "registration", "chassis", "engine", "rc",
    # Devanagari
    "आधार", "मोबाइल", "पैन", "खाता", "दूरभाष",
    # Indonesian, for the KTP corpus that tests the geometry half. These are
    # the labels printed on every national ID card, not shapes inferred from
    # data — the same bar a recognizer has to clear. nik = national ID,
    # nama = name, alamat = address, lahir = born, agama = religion.
    "nik", "nama", "alamat", "lahir", "agama", "darah",
    "kecamatan", "kelurahan", "desa", "rt", "rw",
})

# Terms that identify a person only when the label is about a person rather
# than an institution. "Policyholder Name" is personal; "Branch Name" is not.
WEAK_TERMS: frozenset[str] = frozenset({
    "name", "address", "contact", "signature", "nominee", "guardian",
    "father", "mother", "husband", "spouse", "dob", "birth", "age",
    "नाम", "पता", "हस्ताक्षर",
})

# An institution, not a person. These veto a weak term but never a strong
# one, so "Bank Account Number" still matches while "Bank Name" does not.
INSTITUTION_TERMS: frozenset[str] = frozenset({
    "branch", "bank", "hospital", "clinic", "company", "firm", "office",
    "department", "station", "institution", "school", "college", "university",
    "insurer", "issuer", "authority", "board", "corporation", "ltd",
    "limited", "helpline", "website", "cin", "gst", "scheme", "product",
    "merchant", "vendor", "organisation", "organization", "employer",
})

# Words that carry no meaning for this decision. Stripped before matching so
# a label's core survives its packaging.
FILLER_TERMS: frozenset[str] = frozenset({
    "no", "nos", "number", "num", "id", "code", "details", "detail", "of",
    "the", "for", "if", "any", "self", "employed", "please", "enter",
    "registered", "full", "permanent", "present", "current", "correspondence",
    "communication", "residential", "primary", "alternate", "applicant",
    "holder", "s", "and", "or", "in", "as", "per", "type", "date",
    # Indonesian label scaffolding. "jenis kelamin" (gender) reduces to
    # nothing but filler and so is correctly not PII, matching the rule that
    # a bare gender identifies nobody.
    "tempat", "tgl", "tanggal", "gol", "jenis", "kelamin", "kel",
    "status", "perkawinan", "pekerjaan", "kewarganegaraan",
    "berlaku", "hingga",
})


def label_terms(label: str) -> set[str]:
    """The meaningful words of a label, filler removed."""
    return {w for w in normalise(label).split() if w and w not in FILLER_TERMS}


# Every word a label may be built from. A candidate phrase is only a label
# if all of its words are in here — otherwise longest-match swallows the
# value it is supposed to anchor ("Customer ID 100724681" matched as one
# four-word label once "contains a term" replaced exact-phrase matching,
# and the value then vanished from the box entirely).
LABEL_VOCABULARY: frozenset[str] = (
    STRONG_TERMS | WEAK_TERMS | INSTITUTION_TERMS | FILLER_TERMS
)


def is_label_phrase(phrase: str) -> bool:
    """Is every word of this phrase part of label vocabulary?"""
    words = normalise(phrase).split()
    return bool(words) and all(w in LABEL_VOCABULARY for w in words)


def is_pii_label(label: str) -> bool:
    """Does a value beside this label identify a person?

    A strong term decides it outright. A weak term decides it only when no
    institutional term is present, so "Account Holder Name" matches and
    "Bank Name" does not.
    """
    terms = label_terms(label)
    if not terms:
        return False
    if terms & STRONG_TERMS:
        return True
    return bool(terms & WEAK_TERMS) and not (terms & INSTITUTION_TERMS)


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

# Underscore is a word character to `\w`, so a JSON-style key such as
# "customer_name" would survive as one unmatchable token. Independent data
# caught this: 200 labels missed on maskara for exactly that reason.
_PUNCT = re.compile(r"[^\w\sऀ-ॿ]+|_+", re.UNICODE)
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
            if is_label_phrase(phrase) and is_pii_label(phrase):
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

    # The gap limit gates where the value *starts*, never which of its words
    # are kept. Applying it per word truncates the value at whatever point it
    # runs past the limit — "Anita Iyer" became "Anita". The same mistake was
    # made in the stacked branch below; both are fixed the same way.
    on_row = [
        w for w in words[end:]
        if _same_row(label, w) and w["left"] >= label_right
    ]
    start_word = next(
        (w for w in on_row if w["left"] - label_right <= MAX_GAP_RIGHT * height),
        None,
    )
    if start_word is not None:
        right = [w for w in on_row if w["left"] >= start_word["left"]]
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

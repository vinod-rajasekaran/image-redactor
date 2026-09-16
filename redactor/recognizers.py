"""Every recognizer this project registers, and the registry assembly.

One source of truth on purpose. Registry building previously existed in
both the redaction pipeline and the IndiaPII benchmark, which meant a
recognizer added to one was silently absent from the other's scores.

**Only formats that are actually published live here.** Seven recognizers
were removed on 2026-09-15 — patient ID, PNR, policy number, medical
registration, land record, property registration, bank account. Each
encoded a *shape* for a kind of identifier that has no national format, and
each shape was invented by this project while writing the very test data it
was then scored against. Four never fired once across 67 pages, and the
misses were the variants nobody had thought of (``MRN-458361`` against a
pattern built for ``AB1234567``). Identifiers with no published format are
now handled by position instead — see `redactor/labels.py`.

The bar for adding a recognizer here: **cite the published specification.**
If the format cannot be sourced, it is a label problem, not a pattern one.
"""
from __future__ import annotations

import logging
import re

from presidio_analyzer import Pattern, PatternRecognizer

CONTEXT_DEPENDENT_SCORE = 0.1


def ifsc_recognizer() -> PatternRecognizer:
    """IFSC: 4 letters, a mandatory '0', then 6 alphanumerics.

    The one custom format here that is genuinely specified: an RBI
    standard, 11 characters, with position five reserved as '0'. That fixed
    zero makes it near-unambiguous, so it fires without needing a label.
    The branch code is usually digits but may contain a letter, hence
    ``[A-Z0-9]``.

    Identifies a *branch*, not a person — it is redacted because it appears
    beside account details and narrows who an account belongs to, not
    because it is personal on its own.
    """
    return PatternRecognizer(
        supported_entity="IN_IFSC",
        name="InIfscRecognizer",
        patterns=[Pattern("IFSC", r"\b[A-Z]{4}0[A-Z0-9]{6}\b", 0.7)],
        context=["ifsc", "bank", "branch", "neft", "rtgs"],
    )


def driving_licence_recognizer() -> PatternRecognizer:
    """Indian driving licence numbers — **empirical, not specified**.

    This is the one recognizer here without a citable standard, and it is
    kept on those terms. No authoritative specification was findable:
    Wikipedia's licence article does not cover numbering, and secondary
    sources disagree on whether the RTO code is two characters or three.

    The shape below is widened to the variation that **two independent
    corpora** actually contain — not to anything this project generated,
    which is the distinction that matters:

        KA05 20230012345      2 letters, 2-digit RTO, year, 7-digit serial
        KL-2009-119628        2 letters, no RTO, year, 6-digit serial
        WBBY1990931178        4 letters, year, 6-digit serial
        TSJB2003555471        4 letters, year, 6-digit serial

    The invariant across all of them is a **year in the middle**, which is
    what keeps this from matching arbitrary alphanumerics. Scored moderate
    rather than high for the same reason: the label does most of the work,
    and `DL No` is anchored by `redactor/labels.py` regardless of shape.
    """
    return PatternRecognizer(
        supported_entity="IN_DRIVING_LICENCE",
        name="InDrivingLicenceRecognizer",
        patterns=[
            Pattern(
                "state, optional RTO, year, serial",
                r"\b[A-Z]{2,4}[-\s]?\d{0,3}[-\s]?(?:19|20)\d{2}[-\s]?\d{6,7}\b",
                0.5,
            ),
        ],
        context=["driving", "licence", "license", "dl no", "transport", "rto"],
    )


# --- checksum helpers --------------------------------------------------------


def _luhn_ok(digits: str) -> bool:
    """Luhn-10, the check an ABHA number carries."""
    total, parity = 0, len(digits) % 2
    for index, char in enumerate(digits):
        value = int(char)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _verhoeff_ok(digits: str) -> bool:
    """Verhoeff, the check Aadhaar and its Virtual ID carry.

    Delegates to Presidio's implementation rather than re-deriving the
    permutation tables: a silently wrong table would make every VID look
    invalid and the recognizer would simply never fire.
    """
    from presidio_analyzer.predefined_recognizers import InAadhaarRecognizer

    return bool(InAadhaarRecognizer._is_verhoeff_number(int(digits)))


class ChecksumPatternRecognizer(PatternRecognizer):
    """A pattern recognizer that discards matches failing a checksum.

    `validator` receives the match with separators stripped. A checksum is
    what makes a recognizer falsifiable rather than an opinion about what a
    number looks like, which is the bar for adding one here.
    """

    def __init__(self, *args, validator=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._validator = validator

    def validate_result(self, pattern_text: str):
        if self._validator is None:
            return None
        return bool(self._validator(re.sub(r"[^0-9]", "", pattern_text)))


def abha_number_recognizer() -> PatternRecognizer:
    """ABHA (Ayushman Bharat Health Account) number.

    14 digits, written ``XX-XXXX-XXXX-XXXX``, carrying a **Luhn-10** check
    digit. Issued by the National Health Authority under ABDM.

    Source: NHA / ABDM published format. The checksum is what earns this a
    high score without context — a 14-digit run that passes Luhn is very
    unlikely to be anything else.
    """
    return ChecksumPatternRecognizer(
        supported_entity="IN_ABHA",
        name="InAbhaRecognizer",
        patterns=[
            Pattern("ABHA grouped", r"\b\d{2}-\d{4}-\d{4}-\d{4}\b", 0.7),
            Pattern("ABHA 14-digit", r"\b\d{14}\b", 0.5),
        ],
        context=["abha", "abdm", "health", "ayushman", "phr"],
        validator=lambda digits: len(digits) == 14 and _luhn_ok(digits),
    )


def abha_ocr_fallback_recognizer() -> PatternRecognizer:
    """ABHA numbers whose Luhn check fails — OCR damage, or a synthetic source.

    `abha_number_recognizer` **discards** a match that fails Luhn, which is
    correct for confidence but repeats the trap Presidio's Aadhaar
    recognizer falls into: one misread digit and a real ABHA number is not
    redacted at all. The same remedy applies as for Aadhaar — a
    checksum-free pattern, scored low enough that it only fires beside ABHA
    context.

    It also covers corpora whose generators never applied the checksum: only
    9% of IndiaPII-Bench's ABHA numbers pass Luhn, which is chance.
    """
    return PatternRecognizer(
        supported_entity="IN_ABHA",
        name="InAbhaOcrFallbackRecognizer",
        patterns=[
            Pattern("ABHA grouped (no checksum)",
                    r"\b\d{2}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b", 0.35),
            Pattern("ABHA 14-digit (no checksum)", r"\b\d{14}\b",
                    CONTEXT_DEPENDENT_SCORE),
        ],
        context=["abha", "abdm", "health", "ayushman", "phr"],
    )


def aadhaar_vid_recognizer() -> PatternRecognizer:
    """Aadhaar Virtual ID — a revocable 16-digit stand-in for an Aadhaar.

    16 digits, last digit a **Verhoeff** check, exactly as the Aadhaar
    number itself. Printed on Aadhaar cards alongside the number, so a tool
    that covers the Aadhaar and leaves the VID has not protected anyone.

    Source: UIDAI Virtual ID specification.
    """
    return ChecksumPatternRecognizer(
        supported_entity="IN_AADHAAR_VID",
        name="InAadhaarVidRecognizer",
        patterns=[
            Pattern("VID grouped", r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b", 0.6),
            Pattern("VID 16-digit", r"\b\d{16}\b", 0.4),
        ],
        context=["vid", "virtual", "aadhaar", "uidai"],
        validator=lambda digits: len(digits) == 16 and _verhoeff_ok(digits),
    )


def masked_aadhaar_recognizer() -> PatternRecognizer:
    """A partly-masked Aadhaar, ``XXXX XXXX 1234``.

    UIDAI's own masking convention, and the form that appears on documents
    somebody has *already* partially redacted. The last four digits are
    still personal data: they narrow an individual sharply when combined
    with anything else on the page, and Presidio's Aadhaar recognizer
    cannot see them because the string is not twelve digits.

    The shape is self-evidencing — eight masking characters followed by
    four digits is not a number that occurs by accident — so no checksum is
    needed and none exists.
    """
    return PatternRecognizer(
        supported_entity="IN_AADHAAR_MASKED",
        name="InMaskedAadhaarRecognizer",
        patterns=[
            # `\b` cannot be used at the start: the leading character may be
            # `*`, which is not a word character, so no boundary exists there
            # and `****-****-1234` would never match while `XXXX-XXXX-1234`
            # did. A lookbehind for "not a word or mask character" works for
            # both.
            Pattern(
                "masked aadhaar",
                r"(?<![\w*])[Xx*]{4}[\s-]?[Xx*]{4}[\s-]?\d{4}\b",
                0.6,
            ),
        ],
        context=["aadhaar", "aadhar", "uid", "uidai"],
    )


def abha_address_recognizer() -> PatternRecognizer:
    """ABHA address — a health handle, ``someone@abdm`` or ``@sbx``.

    The suffix set is fixed and published by NHA, which makes this
    unambiguous. It is not an email: there is no dot-TLD, which is why the
    email recognizer never claims it.
    """
    return PatternRecognizer(
        supported_entity="IN_ABHA_ADDRESS",
        name="InAbhaAddressRecognizer",
        patterns=[
            Pattern("abha address", r"\b[A-Za-z0-9](?:[A-Za-z0-9._-]{1,48})@(?:abdm|sbx)\b", 0.7),
        ],
        context=["abha", "abdm", "health", "phr"],
    )


def upi_vpa_recognizer() -> PatternRecognizer:
    """UPI Virtual Payment Address — ``someone@psp``.

    A VPA is distinguished from an email address structurally: the part
    after ``@`` is a PSP handle with **no dot and no TLD**. That property
    is the whole recognizer; the handle list below only raises confidence
    for the common ones, so a new PSP does not mean a missed VPA.

    Source: NPCI UPI specification and its published PSP handle list.
    """
    handles = (
        "okhdfcbank|okicici|oksbi|okaxis|ybl|ibl|axl|apl|paytm|upi|"
        "airtel|freecharge|jupiteraxis|fam|slc|naviaxis|timecosmos"
    )
    return PatternRecognizer(
        supported_entity="IN_UPI_VPA",
        name="InUpiVpaRecognizer",
        patterns=[
            Pattern("VPA known handle",
                    rf"\b[A-Za-z0-9](?:[A-Za-z0-9._-]{{1,48}})@(?:{handles})\b", 0.7),
            # Any handle with no dot after the @ — a shape an email cannot take.
            Pattern("VPA generic",
                    r"\b[A-Za-z0-9](?:[A-Za-z0-9._-]{2,48})@[A-Za-z][A-Za-z0-9]{1,19}\b",
                    0.35),
        ],
        context=["upi", "vpa", "pay", "payment", "paid", "transfer", "gpay", "phonepe"],
    )


def vehicle_registration_recognizer() -> PatternRecognizer:
    """Indian vehicle registration marks, per Rule 50 of the CMVR 1989.

    Presidio's own `IN_VEHICLE_REGISTRATION` scores 22-31% against two
    independent corpora, because the real format is looser than a single
    shape: the series is **one, two, three or no letters at all**, and the
    BH series inverts the whole layout.

    Standard:  2-letter state, 1-2 digit RTO, 0-3 letter series, 4 digits
               — ``MH 12 AB 1234``, ``KA 05 A 9999``, ``DL 1 CAB 4321``
    Bharat:    2-digit year, literal ``BH``, 4 digits, 1-2 letters
               — ``21 BH 1234 AB``

    Source: Central Motor Vehicles Rules 1989, Rule 50.

    Registered alongside Presidio's rather than replacing it: both emit
    `IN_VEHICLE_REGISTRATION`, and overlapping boxes cost nothing.
    """
    return PatternRecognizer(
        supported_entity="IN_VEHICLE_REGISTRATION",
        name="InVehicleRegistrationCmvrRecognizer",
        patterns=[
            Pattern(
                "CMVR standard",
                r"\b[A-Z]{2}[\s-]?\d{1,2}[\s-]?[A-Z]{0,3}[\s-]?\d{4}\b",
                0.4,
            ),
            Pattern(
                "Bharat series",
                r"\b\d{2}[\s-]?BH[\s-]?\d{4}[\s-]?[A-HJ-NP-Z]{1,2}\b",
                0.7,
            ),
        ],
        context=["vehicle", "registration", "reg no", "rto", "chassis",
                 "engine", "car", "motor", "number plate"],
    )


def build_custom_recognizers() -> list[PatternRecognizer]:
    return [build() for build in CUSTOM_RECOGNIZER_BUILDERS]


def build_aadhaar_ocr_fallback_recognizer():
    """A checksum-free IN_AADHAAR recognizer for OCR-garbled numbers.

    Presidio's InAadhaarRecognizer validates a Verhoeff checksum and DROPS
    the match outright when it fails — so a single OCR digit error means a
    real Aadhaar number is not redacted at all.

    The grouped 4-4-4 form scores high enough to fire on its own, because
    OCR of a two-column form emits every label before every value, which
    strands the "Aadhaar" context word far from its number and makes
    context-based scoring unreliable.

    It deliberately carries no look-around guards against matching inside a
    longer digit run. OCR flattens the page into one string with no field
    boundaries, so a neighbouring phone number is indistinguishable from a
    continuation of the same number, and guards drop real Aadhaars. The
    cost is that a credit card or account number also matches here; those
    spans are redacted as CREDIT_CARD/DATE_TIME regardless, so the
    over-match costs label precision in the report, not redaction quality.

    The ungrouped 12-digit form is weaker and still needs context.
    """
    from presidio_analyzer import Pattern, PatternRecognizer

    return PatternRecognizer(
        supported_entity="IN_AADHAAR",
        name="AadhaarOcrFallbackRecognizer",
        patterns=[
            Pattern(
                "Aadhaar 4-4-4 grouped (no checksum)",
                r"\b[0-9]{4}[- :][0-9]{4}[- :][0-9]{4}\b",
                0.5,
            ),
            Pattern("Aadhaar 12-digit (no checksum)", r"\b[0-9]{12}\b", 0.2),
        ],
        context=["aadhaar", "aadhar", "uidai", "uid"],
    )


INDIA_RECOGNIZER_NAMES = [
    "InAadhaarRecognizer",
    "InPanRecognizer",
    "InVoterRecognizer",
    "InPassportRecognizer",
    "InVehicleRegistrationRecognizer",
    "InGstinRecognizer",
]



def build_registry(
    logger: logging.Logger | None = None,
    ocr_tolerant_aadhaar: bool = True,
    medical_ner: bool = False,
):
    """Assemble the recognizer registry used by every scorer and the pipeline."""
    from presidio_analyzer import RecognizerRegistry, predefined_recognizers

    log = logger or logging.getLogger(__name__)
    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()

    for name in INDIA_RECOGNIZER_NAMES:
        registry.add_recognizer(getattr(predefined_recognizers, name)())
    log.info(
        "Registered %d India-specific recognizers: %s",
        len(INDIA_RECOGNIZER_NAMES),
        ", ".join(INDIA_RECOGNIZER_NAMES),
    )

    custom = build_custom_recognizers()
    for recognizer in custom:
        registry.add_recognizer(recognizer)
    log.info(
        "Registered %d custom Indian recognizers: %s",
        len(custom),
        ", ".join(sorted({r.supported_entities[0] for r in custom})),
    )

    if medical_ner:
        try:
            from presidio_analyzer.predefined_recognizers import MedicalNERRecognizer

            registry.add_recognizer(MedicalNERRecognizer())
            log.info("Medical NER enabled (blaze999/Medical-NER)")
        except Exception:
            log.exception("Could not load MedicalNERRecognizer — continuing without it")

    if ocr_tolerant_aadhaar:
        registry.add_recognizer(build_aadhaar_ocr_fallback_recognizer())
        log.info(
            "OCR-tolerant Aadhaar fallback enabled "
            "(catches checksum-invalid numbers near Aadhaar context words)"
        )
    return registry


CUSTOM_RECOGNIZER_BUILDERS = (
    ifsc_recognizer,
    driving_licence_recognizer,
    abha_number_recognizer,
    abha_ocr_fallback_recognizer,
    aadhaar_vid_recognizer,
    masked_aadhaar_recognizer,
    abha_address_recognizer,
    upi_vpa_recognizer,
    vehicle_registration_recognizer,
)

CUSTOM_ENTITIES = (
    "IN_IFSC",
    "IN_DRIVING_LICENCE",
    "IN_ABHA",
    "IN_AADHAAR_VID",
    "IN_AADHAAR_MASKED",
    "IN_ABHA_ADDRESS",
    "IN_UPI_VPA",
    "IN_VEHICLE_REGISTRATION",
)

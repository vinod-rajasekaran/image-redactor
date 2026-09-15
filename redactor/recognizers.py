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
    """Indian driving licence: state code, RTO code, year of issue, serial.

    A **convention, not a published standard** — unlike IFSC, no
    authoritative specification was findable. Secondary sources agree on
    state + RTO + 4-digit year + 7-digit serial, but disagree on whether
    the RTO code is two characters or two-to-three, so both are accepted.
    Written spaced, hyphenated and compact (``KA05 20230012345``,
    ``KA-05-2023-0012345``). Presidio has no IN_DRIVING_LICENCE at all.

    It survives the 2026-09-15 cull because the shape is at least
    externally attested rather than invented here — but the uncertainty is
    real, and a miss on an unusual state's numbering should be treated as
    expected, not surprising.
    """
    return PatternRecognizer(
        supported_entity="IN_DRIVING_LICENCE",
        name="InDrivingLicenceRecognizer",
        patterns=[
            Pattern(
                "DL spaced or hyphenated",
                r"\b[A-Z]{2}[-\s]?[0-9]{2,3}[-\s]?[0-9]{4}[-\s]?[0-9]{7}\b",
                0.6,
            ),
            Pattern(
                "DL compact", r"\b[A-Z]{2}[0-9]{2,3}[-\s]?[0-9]{11}\b", 0.6
            ),
        ],
        context=["driving", "licence", "license", "dl no", "transport", "rto"],
    )


CUSTOM_RECOGNIZER_BUILDERS = (
    ifsc_recognizer,
    driving_licence_recognizer,
)

CUSTOM_ENTITIES = (
    "IN_IFSC",
    "IN_DRIVING_LICENCE",
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

"""Every recognizer this project registers, and the registry assembly.

One source of truth on purpose. Registry building previously existed in
both the redaction pipeline and the IndiaPII benchmark, which meant a
recognizer added to one was silently absent from the other's scores.
"""
from __future__ import annotations

import logging

from presidio_analyzer import Pattern, PatternRecognizer

CONTEXT_DEPENDENT_SCORE = 0.1


def ifsc_recognizer() -> PatternRecognizer:
    """IFSC: 4 letters, a mandatory '0', then 6 alphanumerics.

    The fixed zero in position five makes this near-unambiguous, so it
    does not need context to fire.
    """
    return PatternRecognizer(
        supported_entity="IN_IFSC",
        name="InIfscRecognizer",
        patterns=[Pattern("IFSC", r"\b[A-Z]{4}0[A-Z0-9]{6}\b", 0.7)],
        context=["ifsc", "bank", "branch", "neft", "rtgs"],
    )


def driving_licence_recognizer() -> PatternRecognizer:
    """Indian driving licence: 2-letter state, 2-digit RTO, then 11 digits.

    Written both spaced and unspaced (``KA05 20230012345``,
    ``KA-05-2023-0012345``). Presidio has no IN_DRIVING_LICENCE at all.
    """
    return PatternRecognizer(
        supported_entity="IN_DRIVING_LICENCE",
        name="InDrivingLicenceRecognizer",
        patterns=[
            Pattern(
                "DL spaced or hyphenated",
                r"\b[A-Z]{2}[-\s]?[0-9]{2}[-\s]?[0-9]{4}[-\s]?[0-9]{7}\b",
                0.6,
            ),
            Pattern(
                "DL compact", r"\b[A-Z]{2}[0-9]{2}[-\s]?[0-9]{11}\b", 0.6
            ),
        ],
        context=["driving", "licence", "license", "dl no", "transport", "rto"],
    )


def bank_account_recognizer() -> PatternRecognizer:
    """Indian bank account numbers: 9-18 digits, no checksum, no standard.

    Deliberately weak. A bare digit run is not PII, so this only fires
    beside an account label.
    """
    return PatternRecognizer(
        supported_entity="IN_BANK_ACCOUNT",
        name="InBankAccountRecognizer",
        patterns=[
            Pattern(
                "account digits",
                r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{0,6}\b",
                CONTEXT_DEPENDENT_SCORE,
            ),
            Pattern("account digits compact", r"\b\d{9,18}\b",
                    CONTEXT_DEPENDENT_SCORE),
        ],
        context=["account", "acct", "a/c", "passbook", "statement", "holder"],
    )


def uhid_recognizer() -> PatternRecognizer:
    """Hospital patient identifiers — UHID, MRN, registration numbers.

    No national format exists; each hospital invents one. Matches a
    generic letters-then-digits token and leans entirely on context.
    """
    return PatternRecognizer(
        supported_entity="IN_PATIENT_ID",
        name="InPatientIdRecognizer",
        patterns=[
            Pattern("UHID", r"\b[A-Z]{1,4}[0-9]{5,12}\b", CONTEXT_DEPENDENT_SCORE)
        ],
        context=["uhid", "mrn", "patient", "hospital", "registration", "ip no"],
    )


def pnr_recognizer() -> PatternRecognizer:
    """Airline/rail PNR: six alphanumerics, or ten digits for IRCTC.

    Six alphanumerics is an extremely common shape, so this is entirely
    context-driven — it must not fire on ordinary words or codes.
    """
    return PatternRecognizer(
        supported_entity="IN_PNR",
        name="InPnrRecognizer",
        patterns=[
            Pattern("PNR alphanumeric", r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{6}\b",
                    CONTEXT_DEPENDENT_SCORE),
            Pattern("PNR IRCTC", r"\b\d{10}\b", CONTEXT_DEPENDENT_SCORE),
        ],
        context=["pnr", "booking", "reference", "ticket", "passenger", "flight"],
    )


def policy_number_recognizer() -> PatternRecognizer:
    """Insurance policy numbers — slash- or hyphen-separated, no standard."""
    return PatternRecognizer(
        supported_entity="IN_POLICY_NUMBER",
        name="InPolicyNumberRecognizer",
        patterns=[
            Pattern(
                "policy number",
                r"\b[A-Z]{2,6}[/-][A-Z0-9]{2,6}[/-][A-Z0-9]{3,10}\b",
                0.3,
            )
        ],
        context=["policy", "insurance", "claim", "premium", "insured"],
    )


def medical_registration_recognizer() -> PatternRecognizer:
    """State medical council registration numbers, e.g. MH/MED/2011/45892."""
    return PatternRecognizer(
        supported_entity="IN_MEDICAL_REG",
        name="InMedicalRegRecognizer",
        patterns=[
            Pattern(
                "medical council reg",
                r"\b[A-Z]{2}[/-][A-Z]{2,6}[/-][0-9]{4}[/-][0-9]{3,8}\b",
                0.4,
            )
        ],
        context=["registration", "reg no", "council", "doctor", "mbbs", "md"],
    )


CUSTOM_RECOGNIZER_BUILDERS = (
    ifsc_recognizer,
    driving_licence_recognizer,
    bank_account_recognizer,
    uhid_recognizer,
    pnr_recognizer,
    policy_number_recognizer,
    medical_registration_recognizer,
)

CUSTOM_ENTITIES = (
    "IN_IFSC",
    "IN_DRIVING_LICENCE",
    "IN_BANK_ACCOUNT",
    "IN_PATIENT_ID",
    "IN_PNR",
    "IN_POLICY_NUMBER",
    "IN_MEDICAL_REG",
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

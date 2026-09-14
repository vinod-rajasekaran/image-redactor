"""Pattern recognizers for Indian PII that Presidio does not cover.

Ground-truth scoring found twelve values in the sample set that no
Presidio recognizer claims, seven of which leaked through redaction:
IFSC codes, driving licence numbers, hospital UHIDs, airline PNRs, bank
account numbers, insurance policy numbers and medical registration
numbers.

They fall into two groups, and the distinction drives the scores below.

**Deterministic formats** — IFSC and driving licence numbers have
distinctive shapes that cannot plausibly be anything else, so they score
high enough to fire on their own.

**Shapeless values** — an account number is a run of digits, a PNR is six
alphanumerics, a UHID is letters followed by digits. Nothing about the
value marks it as PII; only the neighbouring label does. These carry a
low base score and depend on Presidio's context enhancer (+0.35) to clear
the 0.4 threshold, which means they fire next to "Account No." and stay
quiet elsewhere.

That context dependency is only safe because OCR reading order puts the
label beside its value. Tesseract PSM 4 does; PSM 3 emits every label
before every value and would strand them. If you change the OCR backend
or page-segmentation mode, re-score before trusting these.
"""
from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

# Base score for values that are only PII because of an adjacent label.
# +0.35 of context enhancement lands them at 0.45, above the 0.4 default
# threshold; without a context word they stay at 0.1 and never fire.
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

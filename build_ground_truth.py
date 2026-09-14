#!/usr/bin/env python3
"""Build ground_truth.json — what PII actually exists in each test image.

Without this, every number the harness reports is an entity *count*, which
moves on both misses and false positives and cannot tell you what fraction
of PII was caught.

The ten real document photos were labelled by reading each image directly
at full resolution. An earlier version labelled them from a downscaled
contact sheet and **materially under-counted**: it missed the age/gender
line and every test result on the lab report, the age and all three
prescribed medications on the prescription, all six transactions and the
closing balance on the bank statement, and the flight number, times and
seat on the boarding pass. Numbers computed against that version were
optimistic, because the items it omitted were largely ones the pipeline
does not redact.

The ten synthetic documents are derived from `generate_test_images
.DOCUMENTS`, so their values stay exact and in sync with the generator.

Scope is deliberately tight: an item counts only if it **identifies a
person**. An earlier version counted bare gender, standalone ages, account
balances, individual transactions, lab measurements, institution names,
flight numbers and seat allocations — 43 such items — and then scored the
tool as failing for leaving them alone. None of those identify anyone, so
including them measured the wrong thing and made the harness look worse
than it is.

Two tiers, because one genuinely is a policy question:

    core       identifies a person: names, Aadhaar/PAN/account/PNR/UHID,
               email, phone, home address, date of birth
    sensitive  health conditions and medications. Not identifying on
               their own, but they attach to a named patient, and most
               redaction policies cover them. Counted separately so a
               policy that excludes them is not scored against.

Deliberately excluded as not PII: gender, standalone age, blood group,
lab values, amounts, balances, transaction lines, bill periods and due
dates, institution names and addresses, bank helplines, IFSC codes (which
identify a branch, not a person), flight numbers, seats and times.
"""
from __future__ import annotations

import json
from pathlib import Path

from generate_test_images import DOCUMENTS

OUTPUT = Path("ground_truth.json")

# field label -> (presidio entity or None, tier)
LABEL_MAP = {
    "Name": ("PERSON", "core"),
    "Applicant Name": ("PERSON", "core"),
    "Patient Name": ("PERSON", "core"),
    "Account Holder": ("PERSON", "core"),
    "Claimant Name": ("PERSON", "core"),
    "Landlord Name": ("PERSON", "core"),
    "Tenant Name": ("PERSON", "core"),
    "Father's Name": ("PERSON", "core"),
    "Admitting Doctor": ("PERSON", "core"),
    "Signature": ("PERSON", "core"),
    "DOB": ("DATE_TIME", "core"),
    "Aadhaar No.": ("IN_AADHAAR", "core"),
    "Aadhaar Ref.": ("IN_AADHAAR", "core"),
    "Tenant Aadhaar": ("IN_AADHAAR", "core"),
    "PAN": ("IN_PAN", "core"),
    "Landlord PAN": ("IN_PAN", "core"),
    "EPIC No.": ("IN_VOTER", "core"),
    "Passport No.": ("IN_PASSPORT", "core"),
    "Vehicle Registration": ("IN_VEHICLE_REGISTRATION", "core"),
    "Mobile": ("PHONE_NUMBER", "core"),
    "Phone": ("PHONE_NUMBER", "core"),
    "Tenant Phone": ("PHONE_NUMBER", "core"),
    "Email": ("EMAIL_ADDRESS", "core"),
    "Address": ("LOCATION", "core"),
    "Property Address": ("LOCATION", "core"),
    "Account No.": ("IN_BANK_ACCOUNT", "core"),
    "DL No.": ("IN_DRIVING_LICENCE", "core"),
    "Policy No.": ("IN_POLICY_NUMBER", "core"),
    "Doctor Reg. No.": ("IN_MEDICAL_REG", "core"),
    "Diagnosis": (None, "sensitive"),
}

# Present in the documents but not PII: institution names and addresses,
# role descriptions, qualifications, amounts, and anything that describes a
# thing rather than a person.
SKIP_LABELS = {
    "Ward / Bed", "Position Applied", "Highest Degree", "Year of Passing",
    "Gender", "Age", "Age / Sex", "Blood Group", "IFSC Code", "Balance",
    "Monthly Rent", "Claim Amount", "Current CTC", "Branch", "Hospital",
    "Clinic Address", "Date", "Admission Date", "Valid Till", "Signature",
}


def synthetic_ground_truth() -> dict:
    out = {}
    for doc in DOCUMENTS:
        items = []
        for label, value in doc["fields"]:
            if not label or label in SKIP_LABELS or not value.strip():
                continue
            if label not in LABEL_MAP:
                continue
            etype, tier = LABEL_MAP[label]
            items.append(
                {
                    "text": value.strip(),
                    "expected_type": etype,
                    "field": label,
                    "tier": tier,
                }
            )
        out[doc["filename"]] = {
            "source": "synthetic",
            "labelled_by": "generator",
            "pii": items,
            "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        }
    return out


def p(text, etype, field, tier="core"):
    return {"text": text, "expected_type": etype, "field": field, "tier": tier}


# Labelled by reading each image at full resolution, then filtered to
# items that identify a person. See the module docstring for what was
# deliberately excluded.
REAL_GROUND_TRUTH = {
    "11_aadhaar_card.png": {
        "pii": [
            p("Priya Sharma", "PERSON", "Name"),
            p("14/08/1987", "DATE_TIME", "DOB"),
            p("4587 6321 9876", "IN_AADHAAR", "Aadhaar No."),
        ],
        "visual": {"face": 1, "qr_code": 1, "barcode": 0},
        "notes": "Aadhaar number is checksum-INVALID; stock Presidio misses it.",
    },
    "12_pan_card.png": {
        "pii": [
            p("ABCDE1234F", "IN_PAN", "PAN"),
            p("Priya Sharma", "PERSON", "Name"),
            p("Rajesh Sharma", "PERSON", "Father's Name"),
            p("14/08/1987", "DATE_TIME", "DOB"),
        ],
        "visual": {"face": 1, "qr_code": 0, "barcode": 0},
        "notes": "PAN 4th char 'D' is not a valid holder-type code, scores 0.45.",
    },
    "13_water_bill.png": {
        "pii": [
            p("Priya Sharma", "PERSON", "Customer Name"),
            p("1234567890", "IN_BANK_ACCOUNT", "Account No."),
            p("12, 3rd Cross Indiranagar Bengaluru - 560038", "LOCATION",
              "Service Address"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 1},
    },
    "14_passport.png": {
        "pii": [],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Closed passport cover. Any detection here is a false positive.",
    },
    "15_job_application_form.png": {
        "pii": [
            p("Priya Sharma", "PERSON", "Full Name"),
            p("14/08/1987", "DATE_TIME", "Date of Birth"),
            p("12, 3rd Cross Indiranagar Bengaluru - 560038", "LOCATION",
              "Address"),
            p("+91 98765 43210", "PHONE_NUMBER", "Phone No."),
            p("priya.sharma@gmail.com", "EMAIL_ADDRESS", "Email"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
    },
    "16_lab_test_report.png": {
        "pii": [
            p("Priya Sharma", "PERSON", "Patient Name"),
            p("AH12345678", "IN_PATIENT_ID", "UHID"),
            p("Dr. Anitha Reddy", "PERSON", "Consultant Pathologist"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Lab values excluded: a measurement identifies nobody.",
    },
    "17_doctor_prescription.png": {
        "pii": [
            p("Priya Sharma", "PERSON", "Patient Name"),
            p("Dr. R. Venkat", "PERSON", "Consultant Physician"),
            p("Metformin 500 mg", None, "Medication", "sensitive"),
            p("Atorvastatin 10 mg", None, "Medication", "sensitive"),
            p("Vitamin D3 60K", None, "Medication", "sensitive"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Handwritten body; neither OCR engine reads it reliably.",
    },
    "18_bank_statement.png": {
        "pii": [
            p("50100123456789", "IN_BANK_ACCOUNT", "Account No."),
            p("Priya Sharma", "PERSON", "Customer Name"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Transactions, balances and the bank helpline excluded: "
                 "amounts and merchants identify nobody on their own.",
    },
    "19_loan_application.png": {
        "pii": [
            p("Priya Sharma", "PERSON", "Full Name"),
            p("14/08/1987", "DATE_TIME", "Date of Birth"),
            p("+91 98765 43210", "PHONE_NUMBER", "Mobile Number"),
            p("priya.sharma@gmail.com", "EMAIL_ADDRESS", "Email Address"),
            p("12, 3rd Cross, Indiranagar Bengaluru - 560038", "LOCATION",
              "Residential Address"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Photo of a laptop screen; Tesseract reads almost nothing.",
    },
    "20_flight_booking.png": {
        "pii": [
            p("6E3F7K", "IN_PNR", "PNR"),
            p("Priya Sharma", "PERSON", "Passenger Name"),
        ],
        "visual": {"face": 0, "qr_code": 1, "barcode": 0},
        "notes": "Route, flight number, times and seat excluded as "
                 "non-identifying.",
    },
}


def main() -> None:
    truth = synthetic_ground_truth()
    for name, entry in REAL_GROUND_TRUTH.items():
        truth[name] = {"source": "real", "labelled_by": "vision", **entry}

    by_tier: dict[str, int] = {}
    unsupported = 0
    for entry in truth.values():
        for item in entry["pii"]:
            by_tier[item["tier"]] = by_tier.get(item["tier"], 0) + 1
            unsupported += item["expected_type"] is None

    total = sum(by_tier.values())
    OUTPUT.write_text(json.dumps(truth, indent=2, ensure_ascii=False))
    print(f"Wrote {OUTPUT}")
    print(f"  images           : {len(truth)}")
    print(f"  PII items        : {total}")
    for tier, count in sorted(by_tier.items(), key=lambda kv: -kv[1]):
        print(f"    {tier:18s} {count}")
    print(f"  no Presidio type : {unsupported}")
    print(f"  visual regions   : {sum(sum(v['visual'].values()) for v in truth.values())}")


if __name__ == "__main__":
    main()

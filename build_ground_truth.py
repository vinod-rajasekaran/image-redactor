#!/usr/bin/env python3
"""Build ground_truth.json — what PII actually exists in each test image.

Without this, every number the harness reports is an entity *count*, which
moves on both misses and false positives and cannot tell you what fraction
of PII was caught.

The synthetic half is derived from `generate_test_images.DOCUMENTS`, so it
stays exact and in sync with the generator. The real half was labelled by
reading the documents.

`expected_type` is what Presidio *should* call each item. `null` means no
Presidio recognizer covers it — those entries are coverage gaps, and are
counted separately from misses.
"""
from __future__ import annotations

import json
from pathlib import Path

from generate_test_images import DOCUMENTS

OUTPUT = Path("ground_truth.json")

# Field label -> the entity type Presidio should assign. None = no recognizer
# exists for this kind of value, so a miss is a coverage gap, not a failure.
LABEL_TO_TYPE = {
    "Name": "PERSON",
    "Applicant Name": "PERSON",
    "Patient Name": "PERSON",
    "Account Holder": "PERSON",
    "Claimant Name": "PERSON",
    "Landlord Name": "PERSON",
    "Tenant Name": "PERSON",
    "Father's Name": "PERSON",
    "Admitting Doctor": "PERSON",
    "Signature": "PERSON",
    "DOB": "DATE_TIME",
    "Date": "DATE_TIME",
    "Admission Date": "DATE_TIME",
    "Valid Till": "DATE_TIME",
    "Aadhaar No.": "IN_AADHAAR",
    "Aadhaar Ref.": "IN_AADHAAR",
    "Tenant Aadhaar": "IN_AADHAAR",
    "PAN": "IN_PAN",
    "Landlord PAN": "IN_PAN",
    "EPIC No.": "IN_VOTER",
    "Passport No.": "IN_PASSPORT",
    "Vehicle Registration": "IN_VEHICLE_REGISTRATION",
    "Mobile": "PHONE_NUMBER",
    "Phone": "PHONE_NUMBER",
    "Tenant Phone": "PHONE_NUMBER",
    "Email": "EMAIL_ADDRESS",
    "Address": "LOCATION",
    "Clinic Address": "LOCATION",
    "Property Address": "LOCATION",
    "Branch": "LOCATION",
    "Hospital": "LOCATION",
    "Account No.": None,        # no Indian bank-account recognizer
    "IFSC Code": None,
    "DL No.": None,             # no Indian driving-licence recognizer
    "Policy No.": None,
    "Doctor Reg. No.": None,
    "Diagnosis": None,          # health data: PII in spirit, no recognizer
}

# Values that are not PII even though they sit in a labelled field.
SKIP_LABELS = {
    "Gender", "Age", "Age / Sex", "Blood Group", "Ward / Bed",
    "Position Applied", "Current CTC", "Balance", "Monthly Rent",
    "Claim Amount", "Highest Degree", "Year of Passing",
}


def synthetic_ground_truth() -> dict:
    out = {}
    for doc in DOCUMENTS:
        items = []
        for label, value in doc["fields"]:
            if not label or label in SKIP_LABELS or not value.strip():
                continue
            if label not in LABEL_TO_TYPE:
                continue
            items.append(
                {
                    "text": value.strip(),
                    "expected_type": LABEL_TO_TYPE[label],
                    "field": label,
                }
            )
        out[doc["filename"]] = {
            "source": "synthetic",
            "pii": items,
            "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        }
    return out


def _pii(text: str, etype: str | None, field: str) -> dict:
    return {"text": text, "expected_type": etype, "field": field}


REAL_GROUND_TRUTH = {
    "11_aadhaar_card.png": {
        "pii": [
            _pii("Priya Sharma", "PERSON", "Name"),
            _pii("14/08/1987", "DATE_TIME", "DOB"),
            _pii("4587 6321 9876", "IN_AADHAAR", "Aadhaar No."),
        ],
        "visual": {"face": 1, "qr_code": 1, "barcode": 0},
        "notes": "Aadhaar number is checksum-INVALID; stock Presidio misses it.",
    },
    "12_pan_card.png": {
        "pii": [
            _pii("ABCDE1234F", "IN_PAN", "PAN"),
            _pii("Priya Sharma", "PERSON", "Name"),
            _pii("Rajesh Sharma", "PERSON", "Father's Name"),
            _pii("14/08/1987", "DATE_TIME", "DOB"),
        ],
        "visual": {"face": 1, "qr_code": 0, "barcode": 0},
        "notes": "PAN 4th char 'D' is not a valid holder-type code, so it only "
                 "matches the weak pattern and scores 0.45.",
    },
    "13_water_bill.png": {
        "pii": [
            _pii("Priya Sharma", "PERSON", "Customer Name"),
            _pii("1234567890", None, "Account No."),
            _pii("12, 3rd Cross Indiranagar Bengaluru - 560038", "LOCATION",
                 "Service Address"),
            _pii("Apr 2025 - May 2025", "DATE_TIME", "Bill Period"),
            _pii("25-05-2025", "DATE_TIME", "Due Date"),
            _pii("12345678901234567890", None, "Barcode number"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 1},
    },
    "14_passport.png": {
        "pii": [],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Closed passport cover — no PII visible. Any detection here "
                 "is a false positive.",
    },
    "15_job_application_form.png": {
        "pii": [
            _pii("Priya Sharma", "PERSON", "Full Name"),
            _pii("14/08/1987", "DATE_TIME", "Date of Birth"),
            _pii("12, 3rd Cross Indiranagar Bengaluru - 560038", "LOCATION",
                 "Address"),
            _pii("+91 98765 43210", "PHONE_NUMBER", "Phone No."),
            _pii("priya.sharma@gmail.com", "EMAIL_ADDRESS", "Email"),
            _pii("IIM Bangalore", "LOCATION", "University"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
    },
    "16_lab_test_report.png": {
        "pii": [
            _pii("Priya Sharma", "PERSON", "Patient Name"),
            _pii("AH12345678", None, "UHID"),
            _pii("12-04-2025 10:15 AM", "DATE_TIME", "Date & Time"),
            _pii("Dr. Anitha Reddy", "PERSON", "Consultant Pathologist"),
            _pii("Apollo Hospitals, Chennai", "LOCATION", "Hospital"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Test results are health data — PII in spirit, no recognizer.",
    },
    "17_doctor_prescription.png": {
        "pii": [
            _pii("Priya Sharma", "PERSON", "Patient Name"),
            _pii("Dr. R. Venkat", "PERSON", "Consultant Physician"),
            _pii("No. 45, 100 Feet Road, Indiranagar, Bengaluru - 560038",
                 "LOCATION", "Clinic Address"),
            _pii("12/04/2025", "DATE_TIME", "Date"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Prescription body is handwritten; neither OCR engine reads it.",
    },
    "18_bank_statement.png": {
        "pii": [
            _pii("50100123456789", None, "Account No."),
            _pii("Priya Sharma", "PERSON", "Customer Name"),
            _pii("01-04-2025 to 30-04-2025", "DATE_TIME", "Period"),
            _pii("1800 270 3333", "PHONE_NUMBER", "Helpline"),
            _pii("www.hdfcbank.com", "URL", "Website"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
    },
    "19_loan_application.png": {
        "pii": [
            _pii("Priya Sharma", "PERSON", "Full Name"),
            _pii("14/08/1987", "DATE_TIME", "Date of Birth"),
            _pii("+91 98765 43210", "PHONE_NUMBER", "Mobile Number"),
            _pii("priya.sharma@gmail.com", "EMAIL_ADDRESS", "Email Address"),
            _pii("12, 3rd Cross, Indiranagar Bengaluru - 560038", "LOCATION",
                 "Residential Address"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Photo of a laptop screen; Tesseract reads almost nothing.",
    },
    "20_flight_booking.png": {
        "pii": [
            _pii("6E3F7K", None, "PNR"),
            _pii("Priya Sharma", "PERSON", "Passenger Name"),
            _pii("BLR Bengaluru", "LOCATION", "From"),
            _pii("CCU Kolkata", "LOCATION", "To"),
            _pii("25 Apr 2025", "DATE_TIME", "Date"),
        ],
        "visual": {"face": 0, "qr_code": 1, "barcode": 0},
    },
}


def main() -> None:
    truth = synthetic_ground_truth()
    for name, entry in REAL_GROUND_TRUTH.items():
        truth[name] = {"source": "real", **entry}

    total_pii = sum(len(v["pii"]) for v in truth.values())
    unsupported = sum(
        1 for v in truth.values() for p in v["pii"] if p["expected_type"] is None
    )
    visual = sum(sum(v["visual"].values()) for v in truth.values())

    OUTPUT.write_text(json.dumps(truth, indent=2, ensure_ascii=False))
    print(f"Wrote {OUTPUT}")
    print(f"  images            : {len(truth)}")
    print(f"  PII items         : {total_pii}")
    print(f"  of which no type  : {unsupported} (coverage gaps, not misses)")
    print(f"  visual regions    : {visual}")


if __name__ == "__main__":
    main()

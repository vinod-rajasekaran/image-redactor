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

Every item carries a `category`, because "is this PII?" is a policy
question and different answers are defensible:

    identifier       name, Aadhaar, PAN, account number, PNR
    contact          phone, email, postal address
    quasi_identifier age, gender, date of birth
    health           diagnoses, medications, test results
    financial        balances, transactions, amounts

`expected_type` is what Presidio should call the item, or `null` where no
recognizer covers it. Scoring can be filtered by category so a policy that
does not treat, say, transaction history as PII is not silently scored
against.
"""
from __future__ import annotations

import json
from pathlib import Path

from generate_test_images import DOCUMENTS

OUTPUT = Path("ground_truth.json")

# field label -> (presidio entity or None, category)
LABEL_MAP = {
    "Name": ("PERSON", "identifier"),
    "Applicant Name": ("PERSON", "identifier"),
    "Patient Name": ("PERSON", "identifier"),
    "Account Holder": ("PERSON", "identifier"),
    "Claimant Name": ("PERSON", "identifier"),
    "Landlord Name": ("PERSON", "identifier"),
    "Tenant Name": ("PERSON", "identifier"),
    "Father's Name": ("PERSON", "identifier"),
    "Admitting Doctor": ("PERSON", "identifier"),
    "Signature": ("PERSON", "identifier"),
    "DOB": ("DATE_TIME", "quasi_identifier"),
    "Date": ("DATE_TIME", "quasi_identifier"),
    "Admission Date": ("DATE_TIME", "quasi_identifier"),
    "Valid Till": ("DATE_TIME", "quasi_identifier"),
    "Age": (None, "quasi_identifier"),
    "Age / Sex": (None, "quasi_identifier"),
    "Gender": (None, "quasi_identifier"),
    "Blood Group": (None, "health"),
    "Aadhaar No.": ("IN_AADHAAR", "identifier"),
    "Aadhaar Ref.": ("IN_AADHAAR", "identifier"),
    "Tenant Aadhaar": ("IN_AADHAAR", "identifier"),
    "PAN": ("IN_PAN", "identifier"),
    "Landlord PAN": ("IN_PAN", "identifier"),
    "EPIC No.": ("IN_VOTER", "identifier"),
    "Passport No.": ("IN_PASSPORT", "identifier"),
    "Vehicle Registration": ("IN_VEHICLE_REGISTRATION", "identifier"),
    "Mobile": ("PHONE_NUMBER", "contact"),
    "Phone": ("PHONE_NUMBER", "contact"),
    "Tenant Phone": ("PHONE_NUMBER", "contact"),
    "Email": ("EMAIL_ADDRESS", "contact"),
    "Address": ("LOCATION", "contact"),
    "Clinic Address": ("LOCATION", "contact"),
    "Property Address": ("LOCATION", "contact"),
    "Branch": ("LOCATION", "contact"),
    "Hospital": ("LOCATION", "contact"),
    "Account No.": ("IN_BANK_ACCOUNT", "identifier"),
    "IFSC Code": ("IN_IFSC", "identifier"),
    "DL No.": ("IN_DRIVING_LICENCE", "identifier"),
    "Policy No.": ("IN_POLICY_NUMBER", "identifier"),
    "Doctor Reg. No.": ("IN_MEDICAL_REG", "identifier"),
    "Diagnosis": (None, "health"),
    "Balance": (None, "financial"),
    "Monthly Rent": (None, "financial"),
    "Claim Amount": (None, "financial"),
    "Current CTC": (None, "financial"),
}

# Genuinely not PII: role descriptions and institution-level facts.
SKIP_LABELS = {"Ward / Bed", "Position Applied", "Highest Degree", "Year of Passing"}


def synthetic_ground_truth() -> dict:
    out = {}
    for doc in DOCUMENTS:
        items = []
        for label, value in doc["fields"]:
            if not label or label in SKIP_LABELS or not value.strip():
                continue
            if label not in LABEL_MAP:
                continue
            etype, category = LABEL_MAP[label]
            items.append(
                {
                    "text": value.strip(),
                    "expected_type": etype,
                    "field": label,
                    "category": category,
                }
            )
        out[doc["filename"]] = {
            "source": "synthetic",
            "labelled_by": "generator",
            "pii": items,
            "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        }
    return out


def p(text, etype, field, category):
    return {
        "text": text,
        "expected_type": etype,
        "field": field,
        "category": category,
    }


# Labelled by reading each image at full resolution.
REAL_GROUND_TRUTH = {
    "11_aadhaar_card.png": {
        "pii": [
            p("Priya Sharma", "PERSON", "Name", "identifier"),
            p("14/08/1987", "DATE_TIME", "DOB", "quasi_identifier"),
            p("Female", None, "Gender", "quasi_identifier"),
            p("4587 6321 9876", "IN_AADHAAR", "Aadhaar No.", "identifier"),
        ],
        "visual": {"face": 1, "qr_code": 1, "barcode": 0},
        "notes": "Aadhaar number is checksum-INVALID; stock Presidio misses it.",
    },
    "12_pan_card.png": {
        "pii": [
            p("ABCDE1234F", "IN_PAN", "PAN", "identifier"),
            p("Priya Sharma", "PERSON", "Name", "identifier"),
            p("Rajesh Sharma", "PERSON", "Father's Name", "identifier"),
            p("14/08/1987", "DATE_TIME", "DOB", "quasi_identifier"),
        ],
        "visual": {"face": 1, "qr_code": 0, "barcode": 0},
        "notes": "PAN 4th char 'D' is not a valid holder-type code, scores 0.45.",
    },
    "13_water_bill.png": {
        "pii": [
            p("Priya Sharma", "PERSON", "Customer Name", "identifier"),
            p("1234567890", "IN_BANK_ACCOUNT", "Account No.", "identifier"),
            p("12, 3rd Cross Indiranagar Bengaluru - 560038", "LOCATION",
              "Service Address", "contact"),
            p("Apr 2025 - May 2025", "DATE_TIME", "Bill Period", "quasi_identifier"),
            p("25-05-2025", "DATE_TIME", "Due Date", "quasi_identifier"),
            p("700.00", None, "Total Amount Due", "financial"),
            p("12345678901234567890", None, "Barcode number", "identifier"),
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
            p("Priya Sharma", "PERSON", "Full Name", "identifier"),
            p("14/08/1987", "DATE_TIME", "Date of Birth", "quasi_identifier"),
            p("Female", None, "Gender", "quasi_identifier"),
            p("12, 3rd Cross Indiranagar Bengaluru - 560038", "LOCATION",
              "Address", "contact"),
            p("+91 98765 43210", "PHONE_NUMBER", "Phone No.", "contact"),
            p("priya.sharma@gmail.com", "EMAIL_ADDRESS", "Email", "contact"),
            p("IIM Bangalore", "LOCATION", "University", "quasi_identifier"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
    },
    "16_lab_test_report.png": {
        "pii": [
            p("Priya Sharma", "PERSON", "Patient Name", "identifier"),
            p("AH12345678", "IN_PATIENT_ID", "UHID", "identifier"),
            p("38 Y / F", None, "Age / Gender", "quasi_identifier"),
            p("12-04-2025 10:15 AM", "DATE_TIME", "Date & Time",
              "quasi_identifier"),
            p("Hemoglobin 11.2 g/dL", None, "Test result", "health"),
            p("WBC Count 8,500", None, "Test result", "health"),
            p("Platelet Count 2.4 Lakh", None, "Test result", "health"),
            p("TSH 2.1", None, "Test result", "health"),
            p("Vitamin D 18.5 ng/mL", None, "Test result", "health"),
            p("Vitamin D levels are low", None, "Remarks", "health"),
            p("Dr. Anitha Reddy", "PERSON", "Consultant Pathologist",
              "identifier"),
            p("Apollo Hospitals, Chennai", "LOCATION", "Hospital", "contact"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
    },
    "17_doctor_prescription.png": {
        "pii": [
            p("Priya Sharma", "PERSON", "Patient Name", "identifier"),
            p("38/F", None, "Age/Sex", "quasi_identifier"),
            p("Dr. R. Venkat", "PERSON", "Consultant Physician", "identifier"),
            p("No. 45, 100 Feet Road, Indiranagar, Bengaluru - 560038",
              "LOCATION", "Clinic Address", "contact"),
            p("12/04/2025", "DATE_TIME", "Date", "quasi_identifier"),
            p("Metformin 500 mg", None, "Medication", "health"),
            p("Atorvastatin 10 mg", None, "Medication", "health"),
            p("Vitamin D3 60K", None, "Medication", "health"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Prescription body is handwritten; neither OCR engine reads it.",
    },
    "18_bank_statement.png": {
        "pii": [
            p("50100123456789", "IN_BANK_ACCOUNT", "Account No.", "identifier"),
            p("Priya Sharma", "PERSON", "Customer Name", "identifier"),
            p("01-04-2025 to 30-04-2025", "DATE_TIME", "Period",
              "quasi_identifier"),
            p("Salary Credit 85,000.00", None, "Transaction", "financial"),
            p("UPI - Amazon 2,499.00", None, "Transaction", "financial"),
            p("ATM Withdrawal 10,000.00", None, "Transaction", "financial"),
            p("UPI - Apollo Pharmacy 1,245.00", None, "Transaction", "financial"),
            p("NEFT - Rent 25,000.00", None, "Transaction", "financial"),
            p("UPI - Swiggy 680.00", None, "Transaction", "financial"),
            p("Closing Balance 45,576.00", None, "Balance", "financial"),
            p("1800 270 3333", "PHONE_NUMBER", "Helpline", "contact"),
            p("www.hdfcbank.com", "URL", "Website", "contact"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Helpline and website are the bank's, not the customer's — "
                 "redacting them is harmless but they are not really PII.",
    },
    "19_loan_application.png": {
        "pii": [
            p("Priya Sharma", "PERSON", "Full Name", "identifier"),
            p("14/08/1987", "DATE_TIME", "Date of Birth", "quasi_identifier"),
            p("+91 98765 43210", "PHONE_NUMBER", "Mobile Number", "contact"),
            p("priya.sharma@gmail.com", "EMAIL_ADDRESS", "Email Address",
              "contact"),
            p("12, 3rd Cross, Indiranagar Bengaluru - 560038", "LOCATION",
              "Residential Address", "contact"),
        ],
        "visual": {"face": 0, "qr_code": 0, "barcode": 0},
        "notes": "Photo of a laptop screen; Tesseract reads almost nothing.",
    },
    "20_flight_booking.png": {
        "pii": [
            p("6E3F7K", "IN_PNR", "PNR", "identifier"),
            p("Priya Sharma", "PERSON", "Passenger Name", "identifier"),
            p("BLR Bengaluru", "LOCATION", "From", "contact"),
            p("CCU Kolkata", "LOCATION", "To", "contact"),
            p("6E 217", None, "Flight", "identifier"),
            p("25 Apr 2025", "DATE_TIME", "Date", "quasi_identifier"),
            p("08:45 AM", "DATE_TIME", "Departure", "quasi_identifier"),
            p("11:40 AM", "DATE_TIME", "Arrival", "quasi_identifier"),
            p("12A", None, "Seat", "identifier"),
        ],
        "visual": {"face": 0, "qr_code": 1, "barcode": 0},
    },
}


def main() -> None:
    truth = synthetic_ground_truth()
    for name, entry in REAL_GROUND_TRUTH.items():
        truth[name] = {"source": "real", "labelled_by": "vision", **entry}

    by_category: dict[str, int] = {}
    unsupported = 0
    for entry in truth.values():
        for item in entry["pii"]:
            by_category[item["category"]] = by_category.get(item["category"], 0) + 1
            unsupported += item["expected_type"] is None

    total = sum(by_category.values())
    OUTPUT.write_text(json.dumps(truth, indent=2, ensure_ascii=False))
    print(f"Wrote {OUTPUT}")
    print(f"  images           : {len(truth)}")
    print(f"  PII items        : {total}")
    for category, count in sorted(by_category.items(), key=lambda kv: -kv[1]):
        print(f"    {category:18s} {count}")
    print(f"  no Presidio type : {unsupported}")
    print(f"  visual regions   : {sum(sum(v['visual'].values()) for v in truth.values())}")


if __name__ == "__main__":
    main()

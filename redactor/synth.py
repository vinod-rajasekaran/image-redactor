"""Synthetic Indian document *values* — names, numbers, addresses.

Deliberately separate from any renderer. The same drawn document can be
rendered flat with Pillow or photographically by an image model, and the
field values must be identical either way, because they are what the
ground truth is built from.

Everything here is fabricated. The number formats are shaped like the real
ones so the recognizers have something to match, but no value is valid:
Aadhaar numbers are not Verhoeff-correct and PANs use a random holder-type
character. Nothing here refers to a real person, account or property.
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass, field as dc_field
from datetime import date, timedelta

# --- vocabulary --------------------------------------------------------------

MALE_FIRST_NAMES = [
    "Arjun", "Rohan", "Vikram", "Aditya", "Rahul", "Karan", "Suresh", "Manoj",
    "Deepak", "Sanjay", "Anil", "Ravi", "Ajay", "Vivek", "Nikhil", "Amit",
]
FEMALE_FIRST_NAMES = [
    "Priya", "Anjali", "Neha", "Divya", "Kavita", "Pooja", "Sunita", "Meera",
    "Anita", "Shreya", "Deepika", "Rekha", "Swati", "Nisha", "Lakshmi", "Radha",
]
LAST_NAMES = [
    "Sharma", "Verma", "Iyer", "Nair", "Reddy", "Patel", "Gupta", "Rao",
    "Menon", "Joshi", "Chatterjee", "Mukherjee", "Pillai", "Naidu",
    "Kulkarni", "Desai",
]
CITIES_STATES = [
    ("Mumbai", "Maharashtra", "400001"), ("Pune", "Maharashtra", "411001"),
    ("Chennai", "Tamil Nadu", "600001"), ("Bengaluru", "Karnataka", "560001"),
    ("Hyderabad", "Telangana", "500001"), ("Kolkata", "West Bengal", "700001"),
    ("Lucknow", "Uttar Pradesh", "226001"), ("Bhopal", "Madhya Pradesh", "462001"),
    ("Guwahati", "Assam", "781001"), ("Kochi", "Kerala", "682001"),
]
STREETS = [
    "MG Road", "Station Road", "Gandhi Nagar", "Park Street", "Church Street",
    "Ring Road", "Lake View Colony", "Sector 12", "Nehru Marg", "Anna Salai",
]
HOSPITALS = [
    "City Care Hospital", "Sunrise Multispeciality Hospital",
    "Lifeline Medical Centre", "Green Valley Hospital", "St. Mary's Hospital",
    "Community Health Centre",
]
BANKS = [
    "National Trust Bank", "Union Cooperative Bank", "Regional Rural Bank",
    "State Grameen Bank", "Metro Commercial Bank",
]
POLICE_STATIONS = [
    "Central Police Station", "MG Road Police Station", "Sector 9 Police Station",
    "Lakeview Police Chowki", "Riverside Police Station",
]
ORGANISATIONS = [
    "District Welfare Office", "State Skill Mission", "Urban Livelihoods Trust",
    "Community Development Society", "Youth Employment Board",
]
DIAGNOSES = [
    "Seasonal viral fever", "Type 2 diabetes mellitus (controlled)",
    "Mild hypertension", "Iron-deficiency anemia", "Acute bronchitis",
    "Fracture, left forearm (healed)",
]
STATE_CODES = ["MH", "KA", "TN", "UP", "WB", "DL", "GJ", "RJ", "MP", "KL"]

UPPER = string.ascii_uppercase


# --- value generators --------------------------------------------------------

def rand_name() -> tuple[str, str]:
    if random.random() < 0.5:
        return f"{random.choice(MALE_FIRST_NAMES)} {random.choice(LAST_NAMES)}", "Male"
    return f"{random.choice(FEMALE_FIRST_NAMES)} {random.choice(LAST_NAMES)}", "Female"


def rand_address() -> str:
    city, state, pin = random.choice(CITIES_STATES)
    return (f"H.No. {random.randint(1, 400)}, {random.choice(STREETS)}, "
            f"{city}, {state} - {pin}")


def rand_dob(min_age: int = 18, max_age: int = 75) -> str:
    days = random.randint(min_age * 365, max_age * 365)
    return (date.today() - timedelta(days=days)).strftime("%d-%m-%Y")


def rand_date(days_back_max: int = 1500) -> str:
    return (date.today() - timedelta(days=random.randint(0, days_back_max))
            ).strftime("%d-%m-%Y")


def rand_phone() -> str:
    return f"+91 {random.randint(70000, 99999)}{random.randint(10000, 99999)}"


def rand_email(name: str) -> str:
    return f"{name.lower().replace(' ', '.')}{random.randint(1, 99)}@example.com"


def rand_aadhaar() -> str:
    """Format-only, grouped 4-4-4. Not Verhoeff-valid, by design."""
    n = "".join(str(random.randint(0, 9)) for _ in range(12))
    return f"{n[0:4]} {n[4:8]} {n[8:12]}"


def rand_pan() -> str:
    return ("".join(random.choice(UPPER) for _ in range(5))
            + f"{random.randint(0, 9999):04d}" + random.choice(UPPER))


def rand_bank_account() -> str:
    return "".join(str(random.randint(0, 9))
                   for _ in range(random.choice([11, 12, 14])))


def rand_ifsc() -> str:
    return ("".join(random.choice(UPPER) for _ in range(4))
            + f"0{random.randint(0, 999999):06d}")


def rand_dl_number() -> str:
    return (f"{random.choice(STATE_CODES)}{random.randint(1, 99):02d} "
            f"{random.randint(1998, 2024)}{random.randint(1000000, 9999999)}")


def rand_fir_number() -> str:
    return f"FIR No. {random.randint(1, 999)}/{random.randint(2020, 2026)}"


def rand_mrn() -> str:
    return f"MRN-{random.randint(100000, 999999)}"


def rand_land_reg_number() -> str:
    return f"REG-{random.randint(2019, 2026)}-{random.randint(10000, 99999)}"


def rand_survey_number() -> str:
    return f"Survey No. {random.randint(1, 500)}/{random.choice('ABC')}"


# --- what counts as PII, and what the redactor should call it ----------------

# category -> (Presidio entity we expect to fire, tier). `None` means no
# recognizer covers it and none is claimed to — a signature, a diagnosis.
# Categories absent from this map are rendered on the page but are not PII
# and are not scored: a bare gender or a visit date identifies nobody.
PII_CATEGORIES: dict[str, tuple[str | None, str]] = {
    "PERSON_NAME": ("PERSON", "core"),
    "FATHER_OR_SPOUSE_NAME": ("PERSON", "core"),
    "DOCTOR_NAME": ("PERSON", "core"),
    "DOB": ("DATE_TIME", "core"),
    "ADDRESS": ("LOCATION", "core"),
    "PHONE_NUMBER": ("PHONE_NUMBER", "core"),
    "EMAIL": ("EMAIL_ADDRESS", "core"),
    "AADHAAR_NUMBER": ("IN_AADHAAR", "core"),
    "PAN_NUMBER": ("IN_PAN", "core"),
    "BANK_ACCOUNT_NUMBER": ("IN_BANK_ACCOUNT", "core"),
    "IFSC_CODE": ("IN_IFSC", "core"),
    "DRIVING_LICENSE_NUMBER": ("IN_DRIVING_LICENCE", "core"),
    "MEDICAL_RECORD_NUMBER": ("IN_PATIENT_ID", "core"),
    "LAND_REGISTRATION_NUMBER": ("IN_PROPERTY_REGISTRATION", "core"),
    "SURVEY_NUMBER": ("IN_LAND_RECORD", "core"),
    "FIR_NUMBER": (None, "core"),
    "DIAGNOSIS": (None, "sensitive"),
}

NOT_PII = {"GENDER", "DATE", "ORGANISATION_NAME"}


@dataclass
class Field:
    label: str
    value: str
    category: str

    @property
    def is_pii(self) -> bool:
        return self.category in PII_CATEGORIES


@dataclass
class Document:
    doc_type: str
    title: str
    fields: list[Field] = dc_field(default_factory=list)
    has_portrait: bool = False

    def add(self, label: str, value: str, category: str) -> None:
        self.fields.append(Field(label, value, category))

    def pii(self) -> list[Field]:
        return [f for f in self.fields if f.is_pii]


# --- document templates ------------------------------------------------------

def _aadhaar() -> Document:
    name, gender = rand_name()
    d = Document("aadhaar", "Government of India — Unique Identification Authority",
                 has_portrait=True)
    d.add("Name", name, "PERSON_NAME")
    d.add("Date of Birth", rand_dob(), "DOB")
    d.add("Gender", gender, "GENDER")
    d.add("Aadhaar Number", rand_aadhaar(), "AADHAAR_NUMBER")
    d.add("Address", rand_address(), "ADDRESS")
    return d


def _pan() -> Document:
    d = Document("pan", "Income Tax Department — Permanent Account Number",
                 has_portrait=True)
    d.add("Name", rand_name()[0], "PERSON_NAME")
    d.add("Father's Name", rand_name()[0], "FATHER_OR_SPOUSE_NAME")
    d.add("Date of Birth", rand_dob(), "DOB")
    d.add("PAN", rand_pan(), "PAN_NUMBER")
    return d


def _driving_license() -> Document:
    name, gender = rand_name()
    d = Document("driving_license", "Transport Department — Driving Licence",
                 has_portrait=True)
    d.add("Name", name, "PERSON_NAME")
    d.add("DL Number", rand_dl_number(), "DRIVING_LICENSE_NUMBER")
    d.add("Date of Birth", rand_dob(), "DOB")
    d.add("Gender", gender, "GENDER")
    d.add("Date of Issue", rand_date(), "DATE")
    d.add("Address", rand_address(), "ADDRESS")
    return d


def _bank_statement() -> Document:
    bank = random.choice(BANKS)
    d = Document("bank_statement", f"{bank} — Account Statement")
    d.add("Account Holder", rand_name()[0], "PERSON_NAME")
    d.add("Account Number", rand_bank_account(), "BANK_ACCOUNT_NUMBER")
    d.add("IFSC Code", rand_ifsc(), "IFSC_CODE")
    d.add("Registered Phone", rand_phone(), "PHONE_NUMBER")
    d.add("Address", rand_address(), "ADDRESS")
    return d


def _medical_report() -> Document:
    name, gender = rand_name()
    hospital = random.choice(HOSPITALS)
    d = Document("medical_report", f"{hospital} — Outpatient Report")
    d.add("Patient Name", name, "PERSON_NAME")
    d.add("Medical Record No.", rand_mrn(), "MEDICAL_RECORD_NUMBER")
    d.add("Date of Birth", rand_dob(), "DOB")
    d.add("Gender", gender, "GENDER")
    d.add("Attending Doctor", f"Dr. {rand_name()[0]}", "DOCTOR_NAME")
    d.add("Visit Date", rand_date(), "DATE")
    d.add("Diagnosis", random.choice(DIAGNOSES), "DIAGNOSIS")
    return d


def _land_registration() -> Document:
    d = Document("land_registration",
                 "Office of the Sub-Registrar — Sale Deed Extract")
    d.add("Registered Owner", rand_name()[0], "PERSON_NAME")
    d.add("Registration No.", rand_land_reg_number(), "LAND_REGISTRATION_NUMBER")
    d.add("Survey Number", rand_survey_number(), "SURVEY_NUMBER")
    d.add("Date of Registration", rand_date(), "DATE")
    d.add("Property Address", rand_address(), "ADDRESS")
    return d


def _police_report() -> Document:
    station = random.choice(POLICE_STATIONS)
    d = Document("police_report", f"{station} — First Information Report")
    d.add("Complainant Name", rand_name()[0], "PERSON_NAME")
    d.add("FIR Number", rand_fir_number(), "FIR_NUMBER")
    d.add("Contact Number", rand_phone(), "PHONE_NUMBER")
    d.add("Date Filed", rand_date(), "DATE")
    d.add("Complainant Address", rand_address(), "ADDRESS")
    return d


def _application_form() -> Document:
    name, gender = rand_name()
    org = random.choice(ORGANISATIONS)
    d = Document("application_form", f"{org} — Application Form")
    d.add("Applicant Name", name, "PERSON_NAME")
    d.add("Date of Birth", rand_dob(), "DOB")
    d.add("Gender", gender, "GENDER")
    d.add("Phone", rand_phone(), "PHONE_NUMBER")
    d.add("Email", rand_email(name), "EMAIL")
    d.add("Aadhaar (for reference)", rand_aadhaar(), "AADHAAR_NUMBER")
    d.add("Address", rand_address(), "ADDRESS")
    return d


DOC_TYPES = {
    "aadhaar": _aadhaar,
    "pan": _pan,
    "driving_license": _driving_license,
    "bank_statement": _bank_statement,
    "medical_report": _medical_report,
    "land_registration": _land_registration,
    "police_report": _police_report,
    "application_form": _application_form,
}


def draw(doc_type: str) -> Document:
    return DOC_TYPES[doc_type]()


def round_robin(count: int, types: list[str] | None = None) -> list[Document]:
    """`count` documents, evenly spread across the requested types."""
    names = types or list(DOC_TYPES)
    return [draw(names[i % len(names)]) for i in range(count)]

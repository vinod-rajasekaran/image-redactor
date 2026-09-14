#!/usr/bin/env python3
"""Generate synthetic Indian-context document images for testing the
Presidio image redactor evaluation harness.

All names, numbers, and addresses below are fabricated placeholders —
none correspond to real people or real documents.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

OUTPUT_DIR = Path("input_images")
IMAGE_SIZE = (900, 1100)
MARGIN = 60
LINE_HEIGHT = 42

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
)
log = logging.getLogger("generate_test_images")

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]
BOLD_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


def _load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    log.warning("No system TrueType font found, falling back to PIL default font.")
    return ImageFont.load_default(size=size)


TITLE_FONT = _load_font(BOLD_FONT_CANDIDATES or FONT_CANDIDATES, 34)
LABEL_FONT = _load_font(BOLD_FONT_CANDIDATES or FONT_CANDIDATES, 24)
BODY_FONT = _load_font(FONT_CANDIDATES, 24)


def render_document(
    filename: str,
    title: str,
    header_color: str,
    fields: list[tuple[str, str]],
    footer_note: str | None = None,
) -> None:
    """Render a simple label/value document image and save it."""
    img = Image.new("RGB", IMAGE_SIZE, color="white")
    draw = ImageDraw.Draw(img)

    # Header bar
    draw.rectangle([0, 0, IMAGE_SIZE[0], 110], fill=header_color)
    draw.text((MARGIN, 35), title, font=TITLE_FONT, fill="white")

    # Border
    draw.rectangle(
        [MARGIN // 2, 130, IMAGE_SIZE[0] - MARGIN // 2, IMAGE_SIZE[1] - MARGIN // 2],
        outline="black",
        width=2,
    )

    y = 170
    for label, value in fields:
        if label:
            draw.text((MARGIN, y), f"{label}:", font=LABEL_FONT, fill="black")
        draw.text((MARGIN + 260, y), value, font=BODY_FONT, fill="black")
        y += LINE_HEIGHT

    if footer_note:
        y += 20
        draw.multiline_text(
            (MARGIN, y), footer_note, font=BODY_FONT, fill="black", spacing=10
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    img.save(path)
    log.info("Generated [bold]%s[/bold]", path, extra={"markup": True})


DOCUMENTS = [
    dict(
        filename="01_aadhaar_card.png",
        title="Government of India - Aadhaar",
        header_color="#1a5fb4",
        fields=[
            ("Name", "Rajesh Kumar Sharma"),
            ("DOB", "14/03/1985"),
            ("Gender", "Male"),
            ("Aadhaar No.", "4521 8734 9012"),
            ("Address", "12, MG Road, Andheri West,"),
            ("", "Mumbai, Maharashtra - 400058"),
            ("Mobile", "+91 98765 43210"),
        ],
    ),
    dict(
        filename="02_pan_card.png",
        title="Income Tax Department - PAN",
        header_color="#26a269",
        fields=[
            ("Name", "Priya Venkataraman"),
            ("Father's Name", "Suresh Venkataraman"),
            ("DOB", "22/07/1990"),
            ("PAN", "BXKPP4521Q"),
            ("Signature", "P. Venkataraman"),
        ],
    ),
    dict(
        filename="03_job_application.png",
        title="Employment Application Form",
        header_color="#5e5c64",
        fields=[
            ("Applicant Name", "Ananya Reddy"),
            ("Email", "ananya.reddy1990@gmail.com"),
            ("Phone", "+91 90123 45678"),
            ("Address", "45, Jubilee Hills, Hyderabad,"),
            ("", "Telangana - 500033"),
            ("Aadhaar Ref.", "3412 6690 8821"),
            ("Position Applied", "Senior Software Engineer"),
            ("Current CTC", "Rs. 18,50,000 per annum"),
        ],
    ),
    dict(
        filename="04_hospital_admission_report.png",
        title="Apollo Care Hospital - Admission Report",
        header_color="#c64600",
        fields=[
            ("Patient Name", "Mohammed Irfan Ali"),
            ("Age / Sex", "52 / Male"),
            ("Address", "78, Park Street, Kolkata - 700016"),
            ("Phone", "+91 91234 56789"),
            ("Admission Date", "03/09/2026"),
            ("Diagnosis", "Type 2 Diabetes Mellitus, Hypertension"),
            ("Admitting Doctor", "Dr. Kavitha Nair"),
            ("Ward / Bed", "Cardiology - Bed 14B"),
        ],
    ),
    dict(
        filename="05_doctor_prescription.png",
        title="Dr. Anil Deshmukh, MBBS MD - Prescription",
        header_color="#1c71d8",
        fields=[
            ("Patient Name", "Sunita Devi Yadav"),
            ("Age", "34 years"),
            ("Date", "12/09/2026"),
            ("Doctor Reg. No.", "MH/MED/2011/45892"),
            ("Clinic Address", "Shop 5, Lokhandwala Complex, Mumbai"),
        ],
        footer_note=(
            "Rx:\n"
            "1. Tab. Metformin 500mg - twice daily after food\n"
            "2. Tab. Amlodipine 5mg - once daily morning\n"
            "3. Follow up after 15 days"
        ),
    ),
    dict(
        filename="06_bank_passbook.png",
        title="State Union Bank of India - Passbook",
        header_color="#613583",
        fields=[
            ("Account Holder", "Vikram Singh Chauhan"),
            ("Account No.", "0234 5678 9012 345"),
            ("IFSC Code", "SUBI0002341"),
            ("Branch", "Connaught Place, New Delhi - 110001"),
            ("Phone", "+91 99887 66554"),
            ("Balance", "Rs. 2,45,678.90"),
        ],
    ),
    dict(
        filename="07_driving_license.png",
        title="Transport Department - Driving Licence",
        header_color="#e5a50a",
        fields=[
            ("Name", "Arjun Nair"),
            ("DL No.", "KA05 20230012345"),
            ("DOB", "05/11/1995"),
            ("Address", "22, Indiranagar 100ft Road,"),
            ("", "Bengaluru, Karnataka - 560038"),
            ("Valid Till", "04/11/2045"),
            ("Blood Group", "O+"),
        ],
    ),
    dict(
        filename="08_voter_id.png",
        title="Election Commission of India - EPIC",
        header_color="#a51d2d",
        fields=[
            ("Name", "Lakshmi Narayanan"),
            ("Father's Name", "Ramaswamy Narayanan"),
            ("EPIC No.", "TNV2345678"),
            ("Age", "41"),
            ("Address", "9, Anna Nagar East, Chennai - 600102"),
        ],
    ),
    dict(
        filename="09_insurance_claim.png",
        title="National Health Insurance - Claim Form",
        header_color="#0d7377",
        fields=[
            ("Policy No.", "NHI/2024/778812"),
            ("Claimant Name", "Farhan Ahmed Khan"),
            ("Phone", "+91 93456 78901"),
            ("Diagnosis", "Fractured left femur - road accident"),
            ("Hospital", "City Care Multispeciality Hospital, Pune"),
            ("Claim Amount", "Rs. 3,25,000"),
        ],
    ),
    dict(
        filename="10_rental_agreement.png",
        title="Residential Rental Agreement (Excerpt)",
        header_color="#241f31",
        fields=[
            ("Landlord Name", "Ramesh Chandra Gupta"),
            ("Landlord PAN", "AHGPG7734L"),
            ("Tenant Name", "Deepika Iyer"),
            ("Tenant Aadhaar", "5678 1234 9087"),
            ("Property Address", "Flat 302, Green Valley Apts,"),
            ("", "Whitefield, Bengaluru - 560066"),
            ("Monthly Rent", "Rs. 32,000"),
            ("Tenant Phone", "+91 97865 43210"),
        ],
    ),
]


def main() -> None:
    console.rule("[bold blue]Generating synthetic PII test documents")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Rendering documents", total=len(DOCUMENTS))
        for doc in DOCUMENTS:
            try:
                render_document(**doc)
            except Exception:
                log.exception("Failed to generate %s", doc["filename"])
            finally:
                progress.advance(task)

    console.rule("[bold green]Done")
    console.print(
        f"[green]Created {len(DOCUMENTS)} test images in "
        f"[bold]{OUTPUT_DIR}/[/bold][/green]"
    )


if __name__ == "__main__":
    main()

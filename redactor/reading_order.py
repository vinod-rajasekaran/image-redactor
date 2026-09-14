"""Re-sorting OCR output into reading order.

Presidio scores an entity higher when a context word sits near it, which
only works if the OCR emits each label beside its value. Some page
segmentation modes emit every label and then every value, stranding them.
"""
from __future__ import annotations

from presidio_image_redactor.ocr import OCR

class ReadingOrderOCR(OCR):
    """Wraps any OCR backend and re-sorts its words into reading order.

    Presidio flattens the word list into one string and scores an entity
    higher when a context word sits near it. That only works if the OCR
    emits each label beside its value. Tesseract PSM 3 does not: on a
    two-column form it emits *every* label and then *every* value, which
    strands "Account No." far from the number it labels and silently
    disables context scoring for the shapeless entities that depend on it
    (IN_BANK_ACCOUNT, IN_PNR, IN_PATIENT_ID, IN_PASSPORT).

    PSM 4 happens to order correctly, which is why it scores better. This
    wrapper makes that a property of the pipeline rather than a lucky
    choice of segmentation mode, so a backend swap cannot quietly
    reintroduce the problem.

    Words are grouped into rows by vertical overlap, rows ordered top to
    bottom, and each row left to right.
    """

    def __init__(self, base: OCR, row_tolerance: float = 0.6) -> None:
        self.base = base
        self.row_tolerance = row_tolerance

    def perform_ocr(self, image: object, **kwargs) -> dict:
        return reorder_reading_order(
            self.base.perform_ocr(image, **kwargs), self.row_tolerance
        )


def reorder_reading_order(result: dict, row_tolerance: float = 0.6) -> dict:
    """Sort an OCR result dict top-to-bottom, then left-to-right."""
    n = len(result.get("text", []))
    if n < 2:
        return result

    tops = result["top"]
    heights = result["height"]
    lefts = result["left"]

    # Tesseract's image_to_data interleaves page/block/paragraph/line rows
    # with the word rows. Those carry empty text and page-spanning boxes,
    # and their heights would swamp the row tolerance, so group words only.
    items = [i for i in range(n) if str(result["text"][i]).strip()]
    if len(items) < 2:
        return result

    # Group into rows: a word joins the current row while its vertical
    # centre stays within a fraction of the row's typical height.
    order = sorted(items, key=lambda i: (tops[i], lefts[i]))
    rows: list[list[int]] = []
    for i in order:
        centre = tops[i] + heights[i] / 2
        placed = False
        for row in rows:
            ref = row[0]
            ref_centre = tops[ref] + heights[ref] / 2
            if abs(centre - ref_centre) <= max(heights[ref], 1) * row_tolerance:
                row.append(i)
                placed = True
                break
        if not placed:
            rows.append([i])

    flat: list[int] = []
    for row in rows:
        flat.extend(sorted(row, key=lambda i: lefts[i]))

    return {key: [values[i] for i in flat] for key, values in result.items()
            if isinstance(values, list) and len(values) == n}



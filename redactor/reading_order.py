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

    # Group into rows: a word joins the row whose vertical centre is
    # **nearest**, among those within a fraction of the row's typical
    # height.
    #
    # Nearest, not first-within-tolerance, and measured against the row's
    # running mean rather than its seed word. Both details are load-bearing
    # and were fixed after a leak: on a tilted Aadhaar card the OCR emitted
    # a garbage token `OVS` (height 43) just above the number, which seeded
    # a row whose band reached down far enough to capture `9876` while
    # `4587 6321` fell into the next row. Flattened, that reads
    # `9876 OVS 4587 6321`, the 4-4-4 grouping never forms, and IN_AADHAAR
    # does not fire at all. Seeding on one word lets whichever word happens
    # to sit highest — often OCR noise, whose height is arbitrary — decide
    # the band for the whole line.
    order = sorted(items, key=lambda i: (tops[i], lefts[i]))
    rows: list[list[int]] = []
    centres: list[float] = []   # running mean centre, parallel to rows
    row_heights: list[float] = []   # running mean height, parallel to rows
    for i in order:
        centre = tops[i] + heights[i] / 2
        best, best_gap = None, None
        for r, row_centre in enumerate(centres):
            gap = abs(centre - row_centre)
            limit = max(row_heights[r], heights[i], 1) * row_tolerance
            if gap <= limit and (best_gap is None or gap < best_gap):
                best, best_gap = r, gap
        if best is None:
            rows.append([i])
            centres.append(centre)
            row_heights.append(float(heights[i]))
        else:
            n_row = len(rows[best])
            rows[best].append(i)
            centres[best] = (centres[best] * n_row + centre) / (n_row + 1)
            row_heights[best] = (
                row_heights[best] * n_row + heights[i]
            ) / (n_row + 1)

    # Rows are emitted by vertical position, not by creation order: a row
    # created early by a high, short token must not outrank the line it
    # was later merged alongside.
    flat: list[int] = []
    for _, row in sorted(zip(centres, rows), key=lambda pair: pair[0]):
        flat.extend(sorted(row, key=lambda i: lefts[i]))

    return {key: [values[i] for i in flat] for key, values in result.items()
            if isinstance(values, list) and len(values) == n}



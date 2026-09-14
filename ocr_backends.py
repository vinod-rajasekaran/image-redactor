"""OCR backends for the redaction harness.

Presidio accepts any `OCR` subclass whose `perform_ocr` returns a
pytesseract-style dict of parallel lists (text + left/top/width/height +
conf), so swapping engines is an adapter, not a rewrite.
"""
from __future__ import annotations

import numpy as np
from presidio_image_redactor import TesseractOCR
from presidio_image_redactor.ocr import OCR

OCR_BACKENDS = ("tesseract", "paddle", "rapidocr")

# Tesseract page-segmentation modes worth trying on documents. The default
# is 3 (fully automatic); the others assume progressively more about layout.
TESSERACT_PSM_MODES = (3, 4, 6, 11, 12)


class TesseractPSMOCR(TesseractOCR):
    """Tesseract pinned to a specific page-segmentation mode."""

    def __init__(self, psm: int = 3) -> None:
        self.psm = psm

    def perform_ocr(self, image: object, **kwargs) -> dict:
        kwargs.setdefault("config", f"--psm {self.psm}")
        return super().perform_ocr(image, **kwargs)

EMPTY_RESULT: dict[str, list] = {
    "text": [],
    "left": [],
    "top": [],
    "width": [],
    "height": [],
    "conf": [],
    "level": [],
    "page_num": [],
    "block_num": [],
    "par_num": [],
    "line_num": [],
    "word_num": [],
}


def _blank_result() -> dict[str, list]:
    return {k: [] for k in EMPTY_RESULT}


def _split_line_into_words(text: str, x: int, y: int, w: int, h: int) -> list[tuple]:
    """Emit each word in a line carrying the *whole line box*.

    PaddleOCR detects text lines, not words, and gives no way to locate a
    word inside one. An earlier version divided the line box between words
    in proportion to their character counts, which assumes uniform spacing
    — and that is wrong for exactly the documents this tool targets. In a
    label/value form ("Name:        Rajesh Kumar Sharma") the wide gap
    shifts every estimated box leftward, so the black rectangle lands on
    the label while the value stays legible. Leakage scoring caught it:
    Paddle detected *more* entities than Tesseract while redacting less of
    the PII (62.4% vs 74.1%), with a DOB and a mobile number left fully
    visible under boxes floating in the margin.

    So a PII word blacks out its entire line. That over-redacts the label
    next to it, which is the correct trade here: a heavier box leaks
    nothing, a misplaced one leaks everything.
    """
    words = text.split()
    return [(word, x, y, w, h) for word in words]


class PaddleOCREngine(OCR):
    """PaddleOCR adapter.

    Paddle's angle classifier handles documents photographed at a tilt,
    which is where Tesseract degrades badly.
    """

    def __init__(self, lang: str = "en") -> None:
        from paddleocr import PaddleOCR as _PaddleOCR

        # Document orientation and UVDoc unwarping must stay OFF. They
        # geometrically rectify the page and then report boxes in *that*
        # space, so every coordinate comes back shifted relative to the
        # image we redact — roughly 50px vertically on an A4-ish scan,
        # enough to black out the row above the PII and leave the PII
        # itself legible.
        try:
            self._ocr = _PaddleOCR(
                lang=lang,
                use_textline_orientation=True,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
            )
        except TypeError:
            # Older releases used a different flag for the angle classifier.
            self._ocr = _PaddleOCR(lang=lang, use_angle_cls=True, show_log=False)

    def _raw_predict(self, array: np.ndarray):
        if hasattr(self._ocr, "predict"):
            return self._ocr.predict(array)
        return self._ocr.ocr(array)

    @staticmethod
    def _iter_lines(raw):
        """Yield (text, confidence, polygon) across PaddleOCR API versions."""
        for page in raw or []:
            if isinstance(page, dict):
                texts = page.get("rec_texts", [])
                scores = page.get("rec_scores", [])
                polys = page.get("dt_polys", page.get("rec_polys", []))
                for text, score, poly in zip(texts, scores, polys):
                    yield text, score, poly
            else:
                for line in page or []:
                    if not line:
                        continue
                    poly, payload = line[0], line[1]
                    text, score = (
                        payload if isinstance(payload, (list, tuple)) else (payload, 1.0)
                    )
                    yield text, score, poly

    def perform_ocr(self, image: object, **kwargs) -> dict:
        from PIL import Image as PILImage

        if isinstance(image, PILImage.Image):
            array = np.array(image.convert("RGB"))
        elif isinstance(image, str):
            array = np.array(PILImage.open(image).convert("RGB"))
        else:
            array = np.asarray(image)

        result = _blank_result()
        for text, score, poly in self._iter_lines(self._raw_predict(array)):
            if not text or not str(text).strip():
                continue
            pts = np.asarray(poly, dtype=float).reshape(-1, 2)
            x, y = int(pts[:, 0].min()), int(pts[:, 1].min())
            w = int(pts[:, 0].max() - pts[:, 0].min())
            h = int(pts[:, 1].max() - pts[:, 1].min())
            for word, wx, wy, ww, wh in _split_line_into_words(str(text), x, y, w, h):
                result["text"].append(word)
                result["left"].append(wx)
                result["top"].append(wy)
                result["width"].append(ww)
                result["height"].append(wh)
                result["conf"].append(float(score) * 100.0)
                result["level"].append(5)
                result["page_num"].append(1)
                result["block_num"].append(1)
                result["par_num"].append(1)
                result["line_num"].append(1)
                result["word_num"].append(len(result["text"]))
        return result


class RapidOCREngine(OCR):
    """RapidOCR adapter — PaddleOCR's models on the ONNXRuntime runtime.

    Same model lineage as PaddleOCR, so accuracy should track it closely,
    without the paddlepaddle runtime. Like Paddle it returns line-level
    boxes, so the same whole-line rule applies (see _split_line_into_words).
    """

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR as _RapidOCR

        self._ocr = _RapidOCR()

    def perform_ocr(self, image: object, **kwargs) -> dict:
        from PIL import Image as PILImage

        if isinstance(image, PILImage.Image):
            array = np.array(image.convert("RGB"))
        elif isinstance(image, str):
            array = np.array(PILImage.open(image).convert("RGB"))
        else:
            array = np.asarray(image)

        raw, _elapsed = self._ocr(array)
        result = _blank_result()
        for entry in raw or []:
            poly, text, score = entry[0], entry[1], entry[2]
            if not text or not str(text).strip():
                continue
            pts = np.asarray(poly, dtype=float).reshape(-1, 2)
            x, y = int(pts[:, 0].min()), int(pts[:, 1].min())
            w = int(pts[:, 0].max() - pts[:, 0].min())
            h = int(pts[:, 1].max() - pts[:, 1].min())
            for word, wx, wy, ww, wh in _split_line_into_words(str(text), x, y, w, h):
                result["text"].append(word)
                result["left"].append(wx)
                result["top"].append(wy)
                result["width"].append(ww)
                result["height"].append(wh)
                result["conf"].append(float(score) * 100.0)
                result["level"].append(5)
                result["page_num"].append(1)
                result["block_num"].append(1)
                result["par_num"].append(1)
                result["line_num"].append(1)
                result["word_num"].append(len(result["text"]))
        return result


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


def build_ocr(
    backend: str, psm: int | None = None, reading_order: bool = True
) -> OCR:
    if backend == "tesseract":
        engine: OCR = TesseractPSMOCR(psm) if psm else TesseractOCR()
    elif backend == "paddle":
        engine = PaddleOCREngine()
    elif backend == "rapidocr":
        engine = RapidOCREngine()
    else:
        raise ValueError(
            f"Unknown OCR backend: {backend!r}. Expected one of {OCR_BACKENDS}"
        )
    return ReadingOrderOCR(engine) if reading_order else engine

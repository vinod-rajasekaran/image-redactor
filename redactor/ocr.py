"""OCR backend adapters.

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
    if reading_order:
        from .reading_order import ReadingOrderOCR

        return ReadingOrderOCR(engine)
    return engine



"""OCR backends for the redaction harness.

Presidio accepts any `OCR` subclass whose `perform_ocr` returns a
pytesseract-style dict of parallel lists (text + left/top/width/height +
conf), so swapping engines is an adapter, not a rewrite.
"""
from __future__ import annotations

import numpy as np
from presidio_image_redactor import TesseractOCR
from presidio_image_redactor.ocr import OCR

OCR_BACKENDS = ("tesseract", "paddle")

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
    """Approximate per-word boxes inside a line box.

    PaddleOCR returns one box per detected line. Handing Presidio whole
    lines would black out an entire line whenever one word in it is PII,
    so the line box is divided between its words in proportion to their
    character counts.
    """
    words = text.split()
    if not words:
        return []
    if len(words) == 1:
        return [(words[0], x, y, w, h)]

    total_chars = sum(len(word) for word in words) + (len(words) - 1)
    cursor = x
    boxes = []
    for i, word in enumerate(words):
        share = len(word) / total_chars
        word_w = max(1, int(round(w * share)))
        boxes.append((word, cursor, y, word_w, h))
        gap = max(1, int(round(w * (1 / total_chars)))) if i < len(words) - 1 else 0
        cursor += word_w + gap
    return boxes


class PaddleOCREngine(OCR):
    """PaddleOCR adapter.

    Paddle's angle classifier handles documents photographed at a tilt,
    which is where Tesseract degrades badly.
    """

    def __init__(self, lang: str = "en") -> None:
        from paddleocr import PaddleOCR as _PaddleOCR

        try:
            self._ocr = _PaddleOCR(lang=lang, use_textline_orientation=True)
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


def build_ocr(backend: str) -> OCR:
    if backend == "tesseract":
        return TesseractOCR()
    if backend == "paddle":
        return PaddleOCREngine()
    raise ValueError(f"Unknown OCR backend: {backend!r}. Expected one of {OCR_BACKENDS}")

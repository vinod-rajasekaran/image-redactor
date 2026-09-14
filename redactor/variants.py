"""Preprocessed copies of an image, OCR'd in parallel and unioned."""
from __future__ import annotations

import cv2
import numpy as np

def build_ocr_variants(image, factor: int = 1, union: bool = True) -> list:
    """Preprocessed copies of an image to OCR in parallel.

    No single preprocessing wins on every document, and the failures land
    on opposite documents. Measured over the sample set (items recovered
    of 77): RGB 66, greyscale 67, CLAHE+Otsu 63 — but their *union* is 71.

    Binarising destroys the coloured gradient backgrounds on Aadhaar and
    PAN cards (CLAHE+Otsu recovers 0 of 4 PAN items), while RGB recovers
    nothing at all from a low-contrast photo of a laptop screen. Running
    one variant means choosing which documents to fail on.

    Redaction boxes are unioned, so a detection found by any variant
    counts and a duplicate box costs nothing.
    """
    from PIL import Image as PILImage

    rgb = image.convert("RGB")
    if factor > 1:
        rgb = rgb.resize((rgb.width * factor, rgb.height * factor), PILImage.LANCZOS)
    if not union:
        return [rgb]

    grey = rgb.convert("L")
    array = np.asarray(grey)
    equalised = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(array)
    binarised = cv2.threshold(
        equalised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[1]
    return [rgb, grey, PILImage.fromarray(binarised)]

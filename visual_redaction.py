"""Detection of non-text PII in images: faces, QR codes and barcodes.

Presidio's ImageRedactorEngine only redacts text found by OCR. On an ID
document that leaves the photo and the QR code untouched — and an Aadhaar
QR encodes the holder's name, DOB and address, so redacting the printed
number while leaving the QR intact is not redaction at all.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw

FACE_CASCADE_FILE = "haarcascade_frontalface_default.xml"


@dataclass
class VisualRegion:
    kind: str  # "face" | "qr_code" | "barcode"
    left: int
    top: int
    width: int
    height: int
    decoded_payload: str | None = None


def _clamp_box(x: int, y: int, w: int, h: int, size: tuple[int, int]) -> tuple:
    max_w, max_h = size
    x = max(0, min(x, max_w))
    y = max(0, min(y, max_h))
    w = max(0, min(w, max_w - x))
    h = max(0, min(h, max_h - y))
    return x, y, w, h


def detect_faces(image: Image.Image) -> list[VisualRegion]:
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + FACE_CASCADE_FILE)
    gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    found = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                     minSize=(20, 20))
    regions = []
    for x, y, w, h in found:
        x, y, w, h = _clamp_box(int(x), int(y), int(w), int(h), image.size)
        regions.append(VisualRegion("face", x, y, w, h))
    return regions


def detect_codes(image: Image.Image) -> list[VisualRegion]:
    """Locate QR codes and barcodes.

    Detection matters more than decoding here: a decorative, damaged or
    low-resolution code still leaks nothing once it is blacked out, and
    pyzbar refuses to decode exactly those. OpenCV locates QR patterns
    without needing to read them; pyzbar adds 1-D barcodes and tells us
    when a payload was actually readable.
    """
    regions: list[VisualRegion] = []
    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    detector = cv2.QRCodeDetector()
    ok, points = detector.detectMulti(gray)
    if not ok:
        ok, points = detector.detect(gray)
    if ok and points is not None:
        for quad in np.array(points).reshape(-1, 4, 2):
            xs, ys = quad[:, 0], quad[:, 1]
            x, y = int(xs.min()), int(ys.min())
            w, h = int(xs.max() - xs.min()), int(ys.max() - ys.min())
            x, y, w, h = _clamp_box(x, y, w, h, image.size)
            if w > 0 and h > 0:
                regions.append(VisualRegion("qr_code", x, y, w, h))

    try:
        from pyzbar import pyzbar

        for code in pyzbar.decode(image):
            r = code.rect
            x, y, w, h = _clamp_box(r.left, r.top, r.width, r.height, image.size)
            kind = "qr_code" if code.type == "QRCODE" else "barcode"
            regions.append(
                VisualRegion(kind, x, y, w, h, code.data.decode("utf-8", "replace"))
            )
    except ImportError:
        pass

    return _deduplicate(regions)


def _deduplicate(regions: list[VisualRegion]) -> list[VisualRegion]:
    """Drop regions whose box is already covered by an earlier one."""
    kept: list[VisualRegion] = []
    for r in regions:
        covered = any(
            r.left >= k.left
            and r.top >= k.top
            and r.left + r.width <= k.left + k.width
            and r.top + r.height <= k.top + k.height
            for k in kept
        )
        if not covered:
            kept.append(r)
    return kept


def detect_visual_pii(
    image: Image.Image, faces: bool = True, codes: bool = True
) -> list[VisualRegion]:
    regions: list[VisualRegion] = []
    if faces:
        regions += detect_faces(image)
    if codes:
        regions += detect_codes(image)
    return regions


# Haar face boxes hug the eyes/nose and routinely clip chin, hair and ears,
# which leaves a recognisable sliver behind; codes need only a small margin.
PAD_RATIO = {"face": 0.30, "qr_code": 0.08, "barcode": 0.08}


def redact_regions(
    image: Image.Image, regions: list[VisualRegion], fill=(0, 0, 0)
) -> Image.Image:
    """Draw filled boxes over the given regions on a copy of the image."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    for r in regions:
        ratio = PAD_RATIO.get(r.kind, 0.05)
        pad_x = max(2, int(r.width * ratio))
        pad_y = max(2, int(r.height * ratio))
        draw.rectangle(
            [
                max(0, r.left - pad_x),
                max(0, r.top - pad_y),
                min(out.width, r.left + r.width + pad_x),
                min(out.height, r.top + r.height + pad_y),
            ],
            fill=fill,
        )
    return out

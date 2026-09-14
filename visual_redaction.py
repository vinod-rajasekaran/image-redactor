"""Detection of non-text PII in images: faces, QR codes and barcodes.

Presidio's ImageRedactorEngine only redacts text found by OCR. On an ID
document that leaves the photo and the QR code untouched — and an Aadhaar
QR encodes the holder's name, DOB and address, so redacting the printed
number while leaving the QR intact is not redaction at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

FACE_CASCADE_FILE = "haarcascade_frontalface_default.xml"
MODEL_DIR = Path(__file__).parent / "models"
YUNET_MODEL = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
YUNET_SCORE_THRESHOLD = 0.6


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


def _detect_faces_haar(image: Image.Image) -> list[VisualRegion]:
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + FACE_CASCADE_FILE)
    gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    found = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                     minSize=(20, 20))
    regions = []
    for x, y, w, h in found:
        x, y, w, h = _clamp_box(int(x), int(y), int(w), int(h), image.size)
        regions.append(VisualRegion("face", x, y, w, h))
    return regions


def _detect_faces_yunet(image: Image.Image) -> list[VisualRegion]:
    bgr = np.array(image.convert("RGB"))[:, :, ::-1].copy()
    detector = cv2.FaceDetectorYN.create(
        str(YUNET_MODEL), "", (320, 320), YUNET_SCORE_THRESHOLD
    )
    detector.setInputSize((bgr.shape[1], bgr.shape[0]))
    _, faces = detector.detect(bgr)
    regions = []
    for face in faces if faces is not None else []:
        x, y, w, h = (int(v) for v in face[:4])
        x, y, w, h = _clamp_box(x, y, w, h, image.size)
        if w > 0 and h > 0:
            regions.append(VisualRegion("face", x, y, w, h))
    return regions


def detect_faces(image: Image.Image) -> list[VisualRegion]:
    """Locate faces, preferring YuNet over the Haar cascade.

    YuNet is a small CNN and is markedly more precise than the 2001-era
    cascade: on the sample set Haar reported 3 faces for 2 real ones,
    inventing a second face on the Aadhaar card, while YuNet found exactly
    the 2 that exist. Haar remains the fallback when the model file is
    absent, so a missing download degrades quality rather than breaking.
    """
    if YUNET_MODEL.exists():
        try:
            return _detect_faces_yunet(image)
        except Exception:
            pass
    return _detect_faces_haar(image)


def _regions_from_points(points, kind: str, size, payloads=None) -> list[VisualRegion]:
    regions: list[VisualRegion] = []
    if points is None:
        return regions
    for i, quad in enumerate(np.array(points).reshape(-1, 4, 2)):
        xs, ys = quad[:, 0], quad[:, 1]
        x, y = int(xs.min()), int(ys.min())
        w, h = int(xs.max() - xs.min()), int(ys.max() - ys.min())
        x, y, w, h = _clamp_box(x, y, w, h, size)
        if w <= 0 or h <= 0:
            continue
        payload = None
        if payloads is not None and i < len(payloads) and payloads[i]:
            payload = str(payloads[i])
        regions.append(VisualRegion(kind, x, y, w, h, payload))
    return regions


WECHAT_MODEL_DIR = MODEL_DIR
WECHAT_MODEL_FILES = (
    "detect.prototxt",
    "detect.caffemodel",
    "sr.prototxt",
    "sr.caffemodel",
)


def wechat_models_available() -> bool:
    return all((WECHAT_MODEL_DIR / f).exists() for f in WECHAT_MODEL_FILES)


def _detect_wechat(image: Image.Image) -> list[VisualRegion]:
    """WeChat QR detector — an opt-in supplement, never the primary path.

    It is strictly better than the stock detector on small, blurry or
    angled *real* QR codes, and returns the decoded payload. But its only
    Python entry point is detectAndDecode(), so it yields no box at all
    for a code it cannot read. Measured here: 4 codes located by the stock
    detector, 0 by WeChat, while a genuine encodable QR was found and
    decoded by both. Union it with the stock detector; never substitute.
    """
    detector = cv2.wechat_qrcode.WeChatQRCode(
        *(str(WECHAT_MODEL_DIR / f) for f in WECHAT_MODEL_FILES)
    )
    texts, points = detector.detectAndDecode(np.array(image.convert("RGB")))
    return _regions_from_points(points, "qr_code", image.size, list(texts))


def detect_codes(
    image: Image.Image, use_pyzbar: bool = False, use_wechat: bool = False
) -> list[VisualRegion]:
    """Locate QR codes and barcodes, preferring detection over decoding.

    A decorative, damaged or low-resolution code leaks nothing once it is
    blacked out — and those are exactly the ones a decoder refuses to read.
    So the primary path is OpenCV's *detectors*, which locate a code without
    decoding it: QRCodeDetector for QR, barcode.BarcodeDetector for 1-D.
    Measured on the sample set, pyzbar decoded nothing at all, while these
    located every code present including a barcode pyzbar missed entirely.

    pyzbar remains an opt-in supplement: when a code really is decodable its
    payload is worth recording, since a readable Aadhaar QR carries the
    holder's name, DOB and address.
    """
    regions: list[VisualRegion] = []
    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    qr = cv2.QRCodeDetector()
    ok, points = qr.detectMulti(gray)
    if not ok:
        ok, points = qr.detect(gray)
    if ok:
        regions += _regions_from_points(points, "qr_code", image.size)

    if hasattr(cv2, "barcode"):
        bar = cv2.barcode.BarcodeDetector()
        # Locate first, decode second. detectAndDecode returns *no boxes* for a
        # barcode it cannot read, which would silently skip exactly the
        # unreadable codes we most need to black out.
        found, bar_points = bar.detect(rgb)
        if found:
            payloads = None
            try:
                decoded, _types, _pts = bar.detectAndDecode(rgb)
                payloads = decoded or None
            except Exception:
                payloads = None
            regions += _regions_from_points(bar_points, "barcode", image.size, payloads)

    if use_wechat and wechat_models_available():
        try:
            regions += _detect_wechat(image)
        except Exception:
            pass

    if use_pyzbar:
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
    image: Image.Image,
    faces: bool = True,
    codes: bool = True,
    use_pyzbar: bool = False,
    use_wechat: bool = False,
) -> list[VisualRegion]:
    regions: list[VisualRegion] = []
    if faces:
        regions += detect_faces(image)
    if codes:
        regions += detect_codes(
            image, use_pyzbar=use_pyzbar, use_wechat=use_wechat
        )
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

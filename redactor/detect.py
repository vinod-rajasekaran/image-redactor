"""Detection of non-text PII: faces, QR codes and barcodes.

Presidio's ImageRedactorEngine only redacts text found by OCR. On an ID
document that leaves the photo and the QR code untouched — and an Aadhaar
QR encodes the holder's name, DOB and address, so redacting the printed
number while leaving the QR intact is not redaction at all.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .geometry import VisualRegion, clamp_box

FACE_CASCADE_FILE = "haarcascade_frontalface_default.xml"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
YUNET_MODEL = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
YUNET_SCORE_THRESHOLD = 0.6

def _detect_faces_haar(image: Image.Image) -> list[VisualRegion]:
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + FACE_CASCADE_FILE)
    gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    found = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                     minSize=(20, 20))
    regions = []
    for x, y, w, h in found:
        x, y, w, h = clamp_box(int(x), int(y), int(w), int(h), image.size)
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
        x, y, w, h = clamp_box(x, y, w, h, image.size)
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
        x, y, w, h = clamp_box(x, y, w, h, size)
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
                x, y, w, h = clamp_box(r.left, r.top, r.width, r.height, image.size)
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
    signatures: bool = True,
) -> list[VisualRegion]:
    regions: list[VisualRegion] = []
    if faces:
        regions += detect_faces(image)
    if signatures:
        try:
            regions += detect_signatures(image)
        except Exception:
            pass
    if codes:
        regions += detect_codes(
            image, use_pyzbar=use_pyzbar, use_wechat=use_wechat
        )
    return regions




# Words that anchor a signature. Matched as whole tokens against OCR
# output, never as substrings: "signs and symptoms" on a medical note
# must not summon a redaction box.
SIGNATURE_CUES = {
    "sign", "signature", "signatures", "signatory", "signed",
    "authorised", "authorized",
}
SIGNATURE_MAX_FILL = 0.85  # above this a component is a printed rule or block

# Cursive connects, print does not. Measured over the cheque ground truth:
# a signature region averages ~24 connected components with 56% of its ink
# in the largest one; a printed name field averages ~239 components with
# 15%. Dilation merges a column of printed labels into one sprawling blob
# that scores well on area and fill, so a candidate is checked against the
# *undilated* ink before it is accepted.
SIGNATURE_MAX_COMPONENTS = 80
SIGNATURE_MIN_LARGEST_FRACTION = 0.30


def _looks_handwritten(crop) -> bool:
    _, mask = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink = int((mask > 0).sum())
    if ink < 50:
        return False
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1 or count - 1 > SIGNATURE_MAX_COMPONENTS:
        return False
    largest = stats[1:, cv2.CC_STAT_AREA].max()
    return (largest / ink) >= SIGNATURE_MIN_LARGEST_FRACTION


def detect_signatures(image: Image.Image, ocr_data: dict | None = None):
    """Locate handwritten signatures, anchored on a nearby printed label.

    A signature is personal data and nothing else here looks for one — the
    cheque benchmark redacted 13% of signature area, and the ground-truth
    auditor separately flagged an unlabelled signature on a PAN card.

    Pure shape analysis was tried first and rejected: ranking every
    connected component by how much it sprawls put the signature at rank
    3-8 on the sample cheques, so taking the top few would have blacked out
    unrelated ink. Anchoring on the printed label instead gives 15/20 with
    *zero* false positives, and the label says only where to look — the ink
    itself is found by connected components, so no page geometry is
    assumed and the same code works on a cheque, a card or a prescription.

    Its ceiling is the label: the five misses are the five cheques where
    OCR never read the cue word.
    """
    import pytesseract

    grey = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    height, width = grey.shape
    data = ocr_data or pytesseract.image_to_data(
        image, config="--psm 4", output_type=pytesseract.Output.DICT
    )

    regions: list[VisualRegion] = []
    for i, raw in enumerate(data["text"]):
        token = str(raw).strip().lower().strip(".:,;")
        if token not in SIGNATURE_CUES:
            continue

        lx, ly = data["left"][i], data["top"][i]
        lw, lh = data["width"][i], data["height"][i]
        # Signatures sit above the label far more often than below it.
        pad_x, up, down = int(width * 0.14), int(height * 0.28), int(height * 0.04)
        x0, y0 = max(0, lx - pad_x), max(0, ly - up)
        x1, y1 = min(width, lx + lw + pad_x), min(height, ly + lh + down)
        crop = grey[y0:y1, x0:x1]
        if crop.size == 0:
            continue

        _, mask = cv2.threshold(
            crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        mask = cv2.dilate(
            mask, cv2.getStructuringElement(cv2.MORPH_RECT, (11, 7)), 1
        )
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

        best = None
        for j in range(1, count):
            x, y, w, h, area = stats[j]
            if w < crop.shape[1] * 0.12 or h < crop.shape[0] * 0.08:
                continue
            fill = area / max(w * h, 1)
            if fill > SIGNATURE_MAX_FILL:
                continue
            # Sprawling ink scores highest: large area, low fill.
            score = area * (1 - fill)
            if best is None or score > best[0]:
                best = (score, x, y, w, h)

        if best:
            _, x, y, w, h = best
            if not _looks_handwritten(crop[y:y + h, x:x + w]):
                continue
            bx, by, bw, bh = clamp_box(x0 + x, y0 + y, w, h, image.size)
            if bw > 0 and bh > 0:
                regions.append(VisualRegion("signature", bx, by, bw, bh))

    return _deduplicate(regions)

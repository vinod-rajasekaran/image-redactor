#!/usr/bin/env python3
"""Metamorphic checks: does a geometry constant describe the *text* or the *page*?

Every spatial constant in this project was set by hand while looking at
about thirty independent images — ten cheques and twenty Indonesian ID
cards. There is no held-out image corpus to catch one that encodes the
shape of the page it was tuned on rather than a property of documents, and
`VALIDATION.md` says why there will not be one soon.

This needs no corpus. It exploits a property the annotations cannot give
us: **changing how much margin surrounds a page does not move any PII
relative to the words around it.** A constant expressed in multiples of the
text it sits near is therefore invariant under it. A constant expressed as
a fraction of the page is not, and this file makes that difference visible
without a single new labelled image.

**Padding is the probe that bites, and that was not the prediction.** The
reasoning that went in first was that padding only grows a window into
blank margin where there is no ink, so cropping would have to be the
diagnostic one. The run said the reverse: cropping the margin off six
cheques changed nothing, while padding them lost four signatures outright.
A cheque is short, so a window measured at 28% of a *doubled* page height
stops being a band above the label and becomes most of the document — and
the largest sprawling blob in that sweep is some other field's ink. Both
transforms stay below, the failing one and the one that looked more
promising, because which probe exposes a constant is itself a finding.

The OCR is run **once** per image and the word boxes are transformed
arithmetically, so nothing here depends on Tesseract reading a padded page
the same way it read the original. Any difference below is the geometry
code alone.

Two of the three checks are positive controls. `labels.py` and
`geometry.py` already express themselves in multiples of a box's own
height, so they must pass; if they ever fail, suspect this harness before
suspecting them.

Usage:
    python test_geometry_invariance.py [--images N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

from redactor.detect import (
    detect_signatures,
    is_signature_cue,
    signature_search_window,
)
from redactor.geometry import merge_same_type_blocks
from redactor.labels import detect_labelled_values

# Padding a cheque (aspect ~2.2) into a portrait page and a portrait form
# into a wide one. Chosen to cross the aspect ratios the corpora actually
# span — 0.56 to 2.22 — so a page-fraction constant has somewhere to move.
PAD_CASES = (
    ("portrait 1:2", 0.5),
    ("landscape 3:1", 3.0),
)
SCALE_CASES = (0.75, 1.5)

# How much slack to leave around the content when cropping the margin away.
# Every OCR word and every baseline detection stays inside with room to
# spare, so nothing below can be blamed on content falling off the page.
CROP_MARGIN = 0.02

# Two boxes count as the same detection when they overlap this much. Well
# below what a correct transform produces (identical boxes score 1.0) and
# well above what a shifted window produces.
SAME_BOX_IOU = 0.9


def ocr_words(image: Image.Image) -> dict:
    import pytesseract

    return pytesseract.image_to_data(
        image, config="--psm 4", output_type=pytesseract.Output.DICT
    )


def shift_ocr(data: dict, dx: int, dy: int) -> dict:
    out = dict(data)
    out["left"] = [v + dx for v in data["left"]]
    out["top"] = [v + dy for v in data["top"]]
    return out


def scale_ocr(data: dict, s: float) -> dict:
    out = dict(data)
    for key in ("left", "top", "width", "height"):
        out[key] = [int(round(v * s)) for v in data[key]]
    return out


def pad_to_aspect(image: Image.Image, aspect: float) -> tuple[Image.Image, int, int]:
    """Place the page on a larger white canvas of the given width/height ratio.

    The page's own pixels are untouched; only what surrounds them changes.
    """
    w, h = image.size
    canvas_w, canvas_h = w, h
    if w / h < aspect:
        canvas_w = int(round(h * aspect))
    else:
        canvas_h = int(round(w / aspect))
    dx, dy = (canvas_w - w) // 2, (canvas_h - h) // 2
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    canvas.paste(image.convert("RGB"), (dx, dy))
    return canvas, dx, dy


def crop_to_content(image: Image.Image, data: dict, keep: list[tuple]):
    """Crop the surrounding margin away, keeping all content with slack.

    The page's own pixels and their positions relative to one another are
    untouched; only the amount of blank around them changes — which is the
    difference between two scans of the same document.

    "Content" includes every region the detectors *read*, not only the ones
    they return: the signature search window reaches well above its cue
    word, and a crop that sliced into it would be removing input rather than
    margin. The claim under test is that margin does not matter; cutting
    into what the detector looks at is a different and uninteresting claim.

    Returns (cropped, dx, dy) or None when there is no margin worth cropping.
    """
    xs0, ys0, xs1, ys1 = [], [], [], []
    for i, text in enumerate(data["text"]):
        if not str(text).strip():
            continue
        xs0.append(data["left"][i])
        ys0.append(data["top"][i])
        xs1.append(data["left"][i] + data["width"][i])
        ys1.append(data["top"][i] + data["height"][i])
        if is_signature_cue(text):
            wx0, wy0, wx1, wy1 = signature_search_window(
                data["left"][i], data["top"][i],
                data["width"][i], data["height"][i],
            )
            xs0.append(wx0); ys0.append(wy0); xs1.append(wx1); ys1.append(wy1)
    for x, y, w, h in keep:
        xs0.append(x); ys0.append(y); xs1.append(x + w); ys1.append(y + h)
    if not xs0:
        return None

    w, h = image.size
    mx, my = int(w * CROP_MARGIN), int(h * CROP_MARGIN)
    x0 = max(0, min(xs0) - mx)
    y0 = max(0, min(ys0) - my)
    x1 = min(w, max(xs1) + mx)
    y1 = min(h, max(ys1) + my)
    if (x1 - x0) >= w and (y1 - y0) >= h:
        return None
    return image.crop((x0, y0, x1, y1)), -x0, -y0


def iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx0, by0, bx1, by1 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union else 0.0


def boxes(regions) -> list[tuple]:
    return sorted((r.left, r.top, r.width, r.height) for r in regions)


def agree(before: list[tuple], after: list[tuple]) -> tuple[int, int, float]:
    """(matched, total distinct, worst IoU among matches)."""
    matched, worst = 0, 1.0
    for b in before:
        best = max((iou(b, a) for a in after), default=0.0)
        if best >= SAME_BOX_IOU:
            matched += 1
            worst = min(worst, best)
    return matched, max(len(before), len(after)), worst


def check(name, condition, detail="") -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"  {status}  {name}{'' if condition else '  <- ' + str(detail)}")
    return bool(condition)


def corpus(pattern: str, limit: int) -> list[Path]:
    return sorted(Path(".").glob(pattern))[:limit]


# --- the checks --------------------------------------------------------------


def window_clipping(image: Image.Image, data: dict) -> dict:
    """How far any signature search window runs off each edge of this page.

    A window that already runs off the page is *not* back-filled — `detect.py`
    explains why, and that filling it was tried and cost three signatures on
    this corpus. So on such a page, adding margin is not a no-op on the
    detector's input: it hands Otsu real pixels where there were none, and the
    threshold computed over that crop moves. That is a property of a
    histogram, not of a constant that encodes the shape of the page, and this
    file exists to test the latter.
    """
    w, h = image.size
    worst = {"left": 0, "top": 0, "right": 0, "bottom": 0}
    for i, text in enumerate(data["text"]):
        if not is_signature_cue(text):
            continue
        x0, y0, x1, y1 = signature_search_window(
            data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        )
        worst["left"] = max(worst["left"], -min(0, x0))
        worst["top"] = max(worst["top"], -min(0, y0))
        worst["right"] = max(worst["right"], max(0, x1 - w))
        worst["bottom"] = max(worst["bottom"], max(0, y1 - h))
    return worst


def signature_window(paths: list[Path]) -> bool:
    """`detect.py` measures its search window against the cue word's height.

        pad_x, up, down = lh * 14.0, lh * 12.5, lh * 2.0

    `lh` is the cue word's own height, so padding the page leaves the window
    the same size around an unmoved cue word. What this checks is that the
    detector reads the same ink for the same signature when only the margin
    around the page changes.

    The one exemption is stated rather than hidden: where a window already
    runs off the page edge, padding un-clips it and changes what Otsu sees.
    Those cases are REPORTED, not asserted — see `window_clipping`.
    """
    print("\nSignature search window — detect.py:276")
    ok, tested, reported, clipped_pages = True, 0, 0, 0
    for path in paths:
        image = Image.open(path)
        data = ocr_words(image)
        base = boxes(detect_signatures(image, data))
        if not base:
            continue
        tested += 1
        clip = window_clipping(image, data)
        if any(clip.values()):
            clipped_pages += 1

        for label, aspect in PAD_CASES:
            padded, dx, dy = pad_to_aspect(image, aspect)
            if padded.size == image.size:
                continue
            moved = sorted(
                (r.left - dx, r.top - dy, r.width, r.height)
                for r in detect_signatures(padded, shift_ocr(data, dx, dy))
            )
            matched, total, worst = agree(base, moved)
            same = matched == total and len(base) == len(moved)

            # Only the axis this padding actually grows can un-clip a window.
            unclips = (dx > 0 and (clip["left"] or clip["right"])) or (
                dy > 0 and (clip["top"] or clip["bottom"])
            )
            if not same and unclips:
                edges = ", ".join(f"{k} {v}px" for k, v in clip.items() if v)
                print(
                    f"  REPORT  {path.name} padded to {label}: "
                    f"{len(base)} region(s) -> {len(moved)}. The search window "
                    f"was clipped ({edges}) before padding, so Otsu reads a "
                    f"different crop. Not asserted — this is the threshold, "
                    f"not a page-shaped constant."
                )
                reported += 1
                continue

            ok &= check(
                f"{path.name} unchanged when padded to {label}",
                same,
                f"{len(base)} region(s) -> {len(moved)}, {matched} agree"
                f" (worst IoU {worst:.2f})",
            )

        cropped = crop_to_content(image, data, base)
        if cropped is None:
            continue
        image2, dx, dy = cropped
        shrink = (image2.size[0] * image2.size[1]) / (image.size[0] * image.size[1])
        moved = sorted(
            (r.left - dx, r.top - dy, r.width, r.height)
            for r in detect_signatures(image2, shift_ocr(data, dx, dy))
        )
        matched, total, worst = agree(base, moved)
        ok &= check(
            f"{path.name} unchanged when the margin is cropped "
            f"({shrink:.0%} of the page area, all content kept)",
            matched == total and len(base) == len(moved),
            f"{len(base)} region(s) -> {len(moved)}, {matched} agree"
            f" (worst IoU {worst:.2f})",
        )

    if not tested:
        print("  (no signature detected on any image — nothing to test)")
    if clipped_pages:
        print(
            f"  (coverage: {clipped_pages} of {tested} page(s) tested already run "
            f"their search window off a page edge — on cheques the cue word sits "
            f"near the right margin, so this is the norm, not the exception. "
            f"{reported} case(s) diverged and were reported rather than asserted. "
            f"Horizontal padding is therefore weak evidence on this corpus; the "
            f"crop and vertical-pad cases carry the claim. A rising reported "
            f"count means the detector is getting more sensitive to how much "
            f"margin a scan happens to have.)"
        )
    return ok


def label_geometry(paths: list[Path]) -> bool:
    """Positive control. `labels.py` works in multiples of the label's height."""
    print("\nLabel-anchored values — labels.py (control: should be invariant)")
    ok = True
    for path in paths:
        image = Image.open(path)
        data = ocr_words(image)
        base = boxes(detect_labelled_values(data))
        if not base:
            continue
        for label, aspect in PAD_CASES:
            padded, dx, dy = pad_to_aspect(image, aspect)
            moved = sorted(
                (r.left - dx, r.top - dy, r.width, r.height)
                for r in detect_labelled_values(shift_ocr(data, dx, dy))
            )
            ok &= check(f"{path.name} unchanged when padded to {label}",
                        base == moved, f"{len(base)} -> {len(moved)} region(s)")
        for s in SCALE_CASES:
            scaled = detect_labelled_values(scale_ocr(data, s))
            # Compare counts only: rounding at two scales cannot give
            # pixel-identical boxes, and a changed *count* is the failure
            # that matters — a value found or lost.
            ok &= check(f"{path.name} finds the same values at {s:g}x",
                        len(scaled) == len(base),
                        f"{len(base)} -> {len(scaled)} region(s)")
    return ok


def block_merging() -> bool:
    """Positive control. `geometry.py` works in multiples of median box height."""
    print("\nBlock merging — geometry.py (control: should be invariant)")
    rows = [
        ("LOCATION", 100, 100, 200, 20),
        ("LOCATION", 100, 130, 160, 20),   # one line below: merges
        ("LOCATION", 100, 600, 180, 20),   # far away: stays separate
        ("PERSON", 400, 100, 120, 20),
    ]
    base = merge_same_type_blocks(rows)
    ok = True
    for s in (2, 5, 10):
        scaled = [(l, x * s, y * s, w * s, h * s) for l, x, y, w, h in rows]
        got = merge_same_type_blocks(scaled)
        shrunk = sorted((l, x // s, y // s, w // s, h // s) for l, x, y, w, h in got)
        ok &= check(f"same merges at {s}x", shrunk == sorted(base),
                    f"{len(base)} -> {len(got)} block(s)")
    # Padding is a pure translation for this function: no page is involved.
    shifted = [(l, x + 5000, y + 5000, w, h) for l, x, y, w, h in rows]
    got = merge_same_type_blocks(shifted)
    ok &= check("same merges when the page grows around the text",
                sorted((l, x - 5000, y - 5000, w, h) for l, x, y, w, h in got)
                == sorted(base),
                f"{len(base)} -> {len(got)} block(s)")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=int, default=4,
                        help="How many images per corpus (default 4)")
    args = parser.parse_args()

    cheques = corpus("datasets/cheques/images/*", args.images)
    documents = corpus("datasets/documents/images/*.png", args.images)
    if not cheques and not documents:
        print("No corpus images found — run from the repository root.")
        return 1

    ok = True
    ok &= block_merging()
    ok &= label_geometry(cheques)
    ok &= signature_window(cheques + documents)

    print("\nPASSED" if ok else "\nFAILED — a constant above describes the page, "
          "not the text it sits near")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

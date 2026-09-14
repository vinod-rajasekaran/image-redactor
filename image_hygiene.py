"""Metadata hygiene for redacted images.

A redacted image can still leak through its container rather than its
pixels. A phone photo carries GPS coordinates, device identifiers and
capture timestamps in EXIF, and often an embedded thumbnail — which is a
copy of the image *as it was before* anything was drawn on it. Publishing
a carefully blacked-out document with an intact thumbnail of the original
defeats the entire exercise.

Pillow happens not to propagate `Image.info["exif"]` unless a caller
passes it to `save()`, so the pipeline is already clean by accident. That
is a fragile thing to rely on: a single `save(**img.info)` or an added
`exif=` argument would silently reintroduce the leak, and nothing would
fail. These helpers make the property explicit and testable instead.

`test_metadata_stripping.py` is the regression guard.
"""
from __future__ import annotations

from PIL import Image, ImageOps

# Formats whose savers accept metadata we would otherwise inherit.
_METADATA_KWARGS = ("exif", "pnginfo", "icc_profile", "xmp", "comment")


def sanitize_for_processing(image: Image.Image) -> Image.Image:
    """Bake in EXIF orientation, then return a metadata-free copy.

    Orientation is applied rather than discarded. A phone photo tagged
    "rotate 90" is stored sideways, and OCR on a sideways page finds
    almost nothing — so transposing first improves detection as well as
    making the stripped image look the way the original did.
    """
    upright = ImageOps.exif_transpose(image) or image

    # Palette images lose their palette through frombytes; normalise first.
    if upright.mode in ("P", "PA"):
        upright = upright.convert("RGBA" if "A" in upright.mode else "RGB")

    clean = Image.frombytes(upright.mode, upright.size, upright.tobytes())
    return clean


def save_clean(image: Image.Image, path) -> None:
    """Save without carrying any metadata across.

    Explicitly refuses the metadata keywords rather than trusting the
    caller to omit them.
    """
    payload = {k: v for k, v in image.info.items() if k not in _METADATA_KWARGS}
    payload.pop("exif", None)
    image.save(path, **{k: v for k, v in payload.items() if k in ("quality",)})


def describe_metadata(image: Image.Image) -> dict:
    """Summarise identifying metadata, for logging and tests."""
    exif = image.getexif()
    return {
        "exif_tags": len(exif),
        "has_gps": 0x8825 in exif,
        "has_thumbnail": bool(exif.get_ifd(0x0201)) if hasattr(exif, "get_ifd") else False,
        "info_keys": sorted(image.info.keys()),
    }

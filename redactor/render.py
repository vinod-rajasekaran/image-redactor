"""Applying redactions to an image.

Separate from detection: what to cover and how to cover it change for
different reasons, and only this module needs to know about pixels.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from .geometry import VisualRegion, region_box

REDACTION_STYLES = ("solid", "blur", "pixelate")

# Deliberately aggressive. Light blur and coarse pixelation are both
# reversible in practice — see the warning in redact_regions.
BLUR_RADIUS_RATIO = 0.6  # of the region's short side
PIXELATE_BLOCKS = 3  # region is reduced to ~3x3 cells before upscaling


def redact_regions(
    image: Image.Image,
    regions: list[VisualRegion],
    fill=(0, 0, 0),
    style: str = "solid",
) -> Image.Image:
    """Obscure the given regions on a copy of the image.

    **Only `solid` actually destroys the information.** Blur and pixelate
    are presentation choices, not security ones: blurring is a convolution
    that can be partially inverted, and pixelating a value drawn from a
    small known alphabet — a 12-digit Aadhaar in a standard font — is
    recoverable by rendering every candidate and matching blocks. Neither
    should be used on output that leaves a trusted environment.

    They are worth having because a reviewer often needs to read the rest
    of the page and judge whether a redaction landed correctly, and a wall
    of black boxes makes that harder. The parameters below are set
    aggressively to make casual recovery difficult, which does not make
    them safe against a deliberate attempt.
    """
    if style not in REDACTION_STYLES:
        raise ValueError(f"Unknown redaction style {style!r}; expected {REDACTION_STYLES}")

    out = image.copy()
    draw = ImageDraw.Draw(out)
    for r in regions:
        box = region_box(r, out.size)
        left, top, right, bottom = box
        if right <= left or bottom <= top:
            continue

        if style == "solid":
            draw.rectangle(box, fill=fill)
        elif style == "blur":
            patch = out.crop(box)
            radius = max(4, int(min(patch.size) * BLUR_RADIUS_RATIO))
            out.paste(patch.filter(ImageFilter.GaussianBlur(radius)), (left, top))
        else:  # pixelate
            patch = out.crop(box)
            small = patch.resize((PIXELATE_BLOCKS, PIXELATE_BLOCKS), Image.BILINEAR)
            out.paste(small.resize(patch.size, Image.NEAREST), (left, top))
    return out



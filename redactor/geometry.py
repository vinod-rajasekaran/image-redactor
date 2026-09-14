"""Region geometry: the box type, clamping, padding and block merging.

Kept separate from detection and from rendering because all three have
different reasons to change. Block merging in particular operates on
*text* entity boxes from Presidio, not only on visually-detected regions,
so it does not belong with the face and QR detectors.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VisualRegion:
    kind: str  # "face" | "qr_code" | "barcode" | "text"
    left: int
    top: int
    width: int
    height: int
    decoded_payload: str | None = None


def clamp_box(x: int, y: int, w: int, h: int, size: tuple[int, int]) -> tuple:
    max_w, max_h = size
    x = max(0, min(x, max_w))
    y = max(0, min(y, max_h))
    w = max(0, min(w, max_w - x))
    h = max(0, min(h, max_h - y))
    return x, y, w, h



# Haar face boxes hug the eyes/nose and routinely clip chin, hair and ears,
# which leaves a recognisable sliver behind; codes need only a small margin.
PAD_RATIO = {"face": 0.30, "qr_code": 0.08, "barcode": 0.08}


def region_box(r: VisualRegion, size: tuple[int, int]) -> tuple:
    ratio = PAD_RATIO.get(r.kind, 0.05)
    pad_x = max(2, int(r.width * ratio))
    pad_y = max(2, int(r.height * ratio))
    return (
        max(0, r.left - pad_x),
        max(0, r.top - pad_y),
        min(size[0], r.left + r.width + pad_x),
        min(size[1], r.top + r.height + pad_y),
    )



# A wrapped address is detected line by line, and often only partially:
# on the sample driving licence, "Bengaluru, Karnataka" was found on the
# second line while the first line matched only a 61px fragment at its
# right end, leaving "22, Indiranagar 100ft" legible. Redacting each
# detected box separately can never fix that, because the missed text was
# never detected. Taking the bounding box of a vertically-stacked cluster
# does: line 2's horizontal extent covers what line 1 missed.
BLOCK_VERTICAL_GAP = 1.6  # multiples of the median box height for that label
BLOCK_HORIZONTAL_SLACK = 0.5  # multiples of median height, for near-misses


def merge_same_type_blocks(items: list[tuple]) -> list[tuple]:
    """Collapse vertically-stacked boxes of one entity type into blocks.

    `items` are (label, left, top, width, height). Boxes of the same label
    within roughly one line of each other, and horizontally overlapping,
    are replaced by the rectangle enclosing them.

    Merging repeats until nothing changes, rather than assigning each box
    to a cluster once: a first pass in reading order left the leftmost
    fragment of an address stranded, because the cluster it belonged to
    only grew wide enough to reach it *after* a later box joined.

    This over-redacts by design — whatever sits between two lines of an
    address goes too, which on a form is nearly always more of the same
    address.
    """
    rects = [[it[0], it[1], it[2], it[1] + it[3], it[2] + it[4]] for it in items]

    # Median height per label, not across all of them: a global median mixes
    # entity types with different fonts and is meaningless. It also silently
    # broke this function once — the address lines sat 21px apart while the
    # global median height was 17, so they failed to merge by four pixels.
    per_label_height: dict[str, float] = {}
    for label in {it[0] for it in items}:
        heights = sorted(it[4] for it in items if it[0] == label)
        per_label_height[label] = heights[len(heights) // 2] if heights else 1

    def near(a, b) -> bool:
        if a[0] != b[0]:
            return False
        median_h = per_label_height.get(a[0], 1)
        vertical = max(0, max(a[2], b[2]) - min(a[4], b[4]))
        horizontal = max(0, max(a[1], b[1]) - min(a[3], b[3]))
        return (
            vertical <= median_h * BLOCK_VERTICAL_GAP
            and horizontal <= median_h * BLOCK_HORIZONTAL_SLACK
        )

    changed = True
    while changed:
        changed = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                if near(rects[i], rects[j]):
                    a, b = rects[i], rects[j]
                    rects[i] = [
                        a[0], min(a[1], b[1]), min(a[2], b[2]),
                        max(a[3], b[3]), max(a[4], b[4]),
                    ]
                    rects.pop(j)
                    changed = True
                    break
            if changed:
                break

    return [(r[0], r[1], r[2], r[3] - r[1], r[4] - r[2]) for r in rects]

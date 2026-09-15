#!/usr/bin/env python3
"""Parsing checks for `redactor.vlm` — no model, no network.

The risky part of using a vision model for redaction is not the model, it
is the coordinate convention. Models disagree: some answer in fractions of
the image, some in Qwen's per-mille 0–1000, some in absolute pixels.
Guessing wrong puts every box in the wrong place — and **a box in the
wrong place is a leak that looks like a redaction**, which is the exact
failure that killed the per-region coverage metric earlier in this project.

So the inference is pinned here, along with the malformed replies a local
model actually produces: code fences, commentary around the JSON, reversed
corners, out-of-range boxes, missing fields.
"""
from __future__ import annotations

import sys

from redactor.vlm import VLMError, parse_items

W, H = 1000, 2000


def check(name, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          f"{'' if condition else '  <- ' + str(detail)}")
    return condition


def main() -> int:
    ok = True

    print("coordinate conventions")
    fractional = '{"items":[{"text":"Nisha","kind":"name","box":[0.1,0.2,0.5,0.25]}]}'
    r = parse_items(fractional, W, H)
    ok &= check("fractions of the image are scaled up",
                len(r) == 1 and r[0].left == 100 and r[0].top == 400
                and r[0].width == 400 and r[0].height == 100, r)

    permille = '{"items":[{"text":"Nisha","kind":"name","box":[100,200,500,250]}]}'
    r = parse_items(permille, W, H)
    ok &= check("per-mille (0-1000) is scaled by 1000",
                len(r) == 1 and r[0].left == 100 and r[0].top == 400, r)

    pixels = '{"items":[{"text":"Nisha","kind":"name","box":[100,1200,500,1400]}]}'
    r = parse_items(pixels, W, H)
    ok &= check("absolute pixels are used as given",
                len(r) == 1 and r[0].left == 100 and r[0].top == 1200
                and r[0].height == 200, r)

    print("\nmalformed replies a local model actually produces")
    fenced = '```json\n{"items":[{"text":"x","kind":"name","box":[0,0,0.5,0.5]}]}\n```'
    ok &= check("code fences stripped", len(parse_items(fenced, W, H)) == 1)

    chatty = ('Sure! Here is what I found:\n'
              '{"items":[{"text":"x","kind":"name","box":[0,0,0.5,0.5]}]}\nHope that helps.')
    ok &= check("JSON extracted from surrounding prose",
                len(parse_items(chatty, W, H)) == 1)

    reversed_box = '{"items":[{"text":"x","kind":"name","box":[0.5,0.5,0.1,0.2]}]}'
    r = parse_items(reversed_box, W, H)
    ok &= check("reversed corners normalised, not dropped",
                len(r) == 1 and r[0].width == 400 and r[0].height == 600, r)

    overflow = '{"items":[{"text":"x","kind":"name","box":[0.8,0.9,1.4,1.6]}]}'
    r = parse_items(overflow, W, H)
    ok &= check("box past the edge is clamped inside the image",
                len(r) == 1 and r[0].left + r[0].width <= W
                and r[0].top + r[0].height <= H, r)

    print("\ndegenerate input")
    ok &= check("empty result", parse_items('{"items":[]}', W, H) == [])
    ok &= check("missing box dropped",
                parse_items('{"items":[{"text":"x","kind":"name"}]}', W, H) == [])
    ok &= check("wrong-length box dropped",
                parse_items('{"items":[{"text":"x","box":[1,2,3]}]}', W, H) == [])
    ok &= check("zero-area box dropped",
                parse_items('{"items":[{"text":"x","box":[0.5,0.5,0.5,0.5]}]}', W, H) == [])

    unknown = '{"items":[{"text":"x","kind":"invented_category","box":[0,0,0.2,0.2]}]}'
    r = parse_items(unknown, W, H)
    ok &= check("unknown kind is still redacted, not discarded",
                len(r) == 1 and r[0].kind == "vlm_other", r)

    try:
        parse_items("I could not read the image.", W, H)
        ok &= check("non-JSON reply raises", False, "no exception")
    except VLMError:
        ok &= check("non-JSON reply raises VLMError", True)

    print("\nPASSED" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

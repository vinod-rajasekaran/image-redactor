#!/usr/bin/env python3
"""Geometry checks for `redactor.labels`, on hand-built OCR output.

The lexicon half of `labels.py` is measured on independent data by
`benchmark_labels.py`. The geometry half cannot be — no annotated Indian
form images exist under a permissive licence — so it is pinned here
instead, on OCR dicts written by hand.

That is a weaker kind of evidence and the file says so out loud: these
cases were written from the failures they caught, not from imagination.
Three real bugs are pinned below, two of them the same mistake made twice:
applying a *positional limit* to every word of a value rather than only to
where the value starts, which silently truncated multi-word values.
"""
from __future__ import annotations

import sys

from redactor.labels import (
    detect_labelled_values,
    find_labels,
    is_pii_label,
    normalise,
    _words,
)


def ocr(rows):
    """(text, left, top, width, height) tuples -> a pytesseract-style dict."""
    keys = ("text", "left", "top", "width", "height", "conf")
    out = {k: [] for k in keys}
    for text, left, top, width, height in rows:
        for key, value in zip(keys, (text, left, top, width, height, 90)):
            out[key].append(value)
    return out


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  {status}  {name}{'' if condition else '  <- ' + str(detail)}")
    return condition


def main() -> int:
    ok = True
    print("label vocabulary")
    for phrase, expected in [
        ("Bank Account Number", True),    # strong term survives institution word
        ("Bank Name", False),             # weak term vetoed by institution word
        ("Branch Code", False),
        ("Policyholder Name", True),
        ("Mobile Number", True),          # morphology, not a new vocabulary entry
        ("Driving Licence No", True),
        ('"customer_name"', True),        # underscore split; caught on maskara
        ("Amount", False),
        ("Date", False),
    ]:
        ok &= check(f"{phrase!r} -> {expected}", is_pii_label(phrase) == expected)

    print("\ngeometry")
    two_col = ocr([
        ("Customer", 100, 200, 90, 20), ("ID", 195, 200, 25, 20),
        ("100724681", 400, 200, 120, 20),
        ("Branch", 100, 240, 70, 20), ("Code", 175, 240, 50, 20),
        ("90519", 400, 240, 60, 20),
    ])
    found = detect_labelled_values(two_col)
    ok &= check("value to the right of its label, Branch Code ignored",
                len(found) == 1 and found[0].left == 400 and found[0].width == 120,
                found)
    ok &= check("label does not swallow its own value",
                [p for _, _, p in find_labels(_words(two_col))] == ["customer id"])

    wrapped = ocr([
        ("Account", 100, 500, 80, 20), ("Holder", 185, 500, 60, 20),
        ("Name", 250, 500, 50, 20),
        ("Anita", 400, 500, 50, 20), ("Iyer", 455, 500, 40, 20),
    ])
    found = detect_labelled_values(wrapped)
    ok &= check("multi-word value kept whole (gap limit gates the start only)",
                len(found) == 1 and found[0].left == 400 and found[0].width == 95,
                found)
    ok &= check("longest label wins: 'account holder name', not 'name'",
                [p for _, _, p in find_labels(_words(wrapped))] == ["account holder name"])

    stacked = ocr([
        ("Address", 100, 300, 80, 20),
        ("H.No.", 100, 330, 50, 20), ("225,", 155, 330, 40, 20),
        ("Bhopal", 200, 330, 60, 20),
    ])
    found = detect_labelled_values(stacked)
    ok &= check("value stacked beneath its label, whole line kept",
                len(found) == 1 and found[0].top == 330 and found[0].width == 160,
                found)

    devanagari = ocr([
        ("आधार", 100, 400, 60, 20),
        ("8643", 300, 400, 50, 20), ("6694", 355, 400, 50, 20),
    ])
    found = detect_labelled_values(devanagari)
    ok &= check("Devanagari label, Latin value",
                len(found) == 1 and found[0].left == 300, found)

    two_fields = ocr([
        ("Name", 100, 600, 50, 20), ("Anita", 200, 600, 50, 20),
        ("Mobile", 400, 600, 60, 20), ("9876543210", 500, 600, 110, 20),
    ])
    found = detect_labelled_values(two_fields)
    ok &= check("two fields on one row do not merge",
                len(found) == 2 and found[0].width == 50, found)

    ok &= check("scale divides back to original-image space",
                detect_labelled_values(two_col, scale=2)[0].left == 200)
    ok &= check("empty OCR is handled", detect_labelled_values(ocr([])) == [])

    print("\nPASSED" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

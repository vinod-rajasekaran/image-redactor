#!/usr/bin/env python3
"""Checks for `redactor.clinical` — what it will and will not withdraw.

The model half is not pinned here. `MedicalNERRecognizer` is a transformer
whose outputs are its own business, and a test asserting that it scores
`Metformin` at 0.83 would pin the model version, not this code. What is
pinned is the part this project owns and could get wrong in a way that
leaks: the rule that decides which boxes a protected region may withdraw.

Three properties matter, and a failure in any of them is a leak rather
than an inconvenience:

- an identifier is never withdrawn, however clinical its surroundings
- a box only partly on clinical text is never withdrawn
- no protected regions means nothing is withdrawn, so a model that fails
  to load leaves redaction exactly as it was
"""
from __future__ import annotations

import sys

from redactor.clinical import OVERLAP_TO_SUPPRESS, suppress


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  {status}  {name}{'' if condition else '  <- ' + str(detail)}")
    return bool(condition)


def main() -> int:
    ok = True
    # A region covering "Metformin 500 mg", and a PERSON box sitting on it.
    region = [(100, 200, 200, 30)]

    kept, dropped = suppress([("PERSON", 100, 200, 200, 30)], region)
    ok &= check("a name box wholly on clinical text is withdrawn",
                dropped == 1 and kept == [], (kept, dropped))

    kept, dropped = suppress([("IN_AADHAAR", 100, 200, 200, 30)], region)
    ok &= check("an identifier on the same text is kept",
                dropped == 0 and len(kept) == 1, (kept, dropped))

    for entity in ("IN_IFSC", "PHONE_NUMBER", "EMAIL_ADDRESS",
                   "IN_DRIVING_LICENCE", "CREDIT_CARD"):
        kept, dropped = suppress([(entity, 100, 200, 200, 30)], region)
        ok &= check(f"{entity} is not suppressible", dropped == 0, kept)

    # Mostly outside: below the threshold, so it stays. A name that merely
    # abuts a drug name must not be un-redacted by it.
    kept, dropped = suppress([("PERSON", 220, 200, 200, 30)], region)
    ok &= check("a box 40% on clinical text is kept",
                dropped == 0 and len(kept) == 1, (kept, dropped))

    # The threshold is inclusive, so exactly half is withdrawn. Pinned
    # because a strict/non-strict comparison is easy to flip by accident.
    kept, dropped = suppress([("PERSON", 200, 200, 200, 30)], region)
    ok &= check("exactly at the threshold is withdrawn",
                dropped == 1 and kept == [], (kept, dropped))

    # Comfortably over the threshold.
    kept, dropped = suppress([("LOCATION", 140, 200, 200, 30)], region)
    ok &= check("a box 80% on clinical text is withdrawn",
                dropped == 1 and kept == [], (kept, dropped))

    ok &= check("the threshold is a fraction of the box, not the region",
                0 < OVERLAP_TO_SUPPRESS <= 1)

    boxes = [("PERSON", 100, 200, 200, 30), ("ORGANIZATION", 0, 0, 50, 50)]
    kept, dropped = suppress(boxes, [])
    ok &= check("no protected regions withdraws nothing",
                dropped == 0 and kept == boxes, (kept, dropped))

    kept, dropped = suppress([("PERSON", 100, 900, 200, 30)], region)
    ok &= check("a box nowhere near clinical text is kept",
                dropped == 0 and len(kept) == 1, (kept, dropped))

    # A zero-area box cannot divide by its area.
    kept, dropped = suppress([("PERSON", 100, 200, 0, 0)], region)
    ok &= check("a zero-area box does not raise", dropped == 0, (kept, dropped))

    print("\nPASSED" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

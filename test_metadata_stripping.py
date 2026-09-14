#!/usr/bin/env python3
"""Regression guard: redacted output must carry no identifying metadata.

The pipeline is currently clean partly by accident — Pillow does not
propagate `Image.info["exif"]` unless a caller passes it to `save()`. A
future `save(**img.info)`, or an `exif=` argument added for some other
reason, would silently reintroduce GPS coordinates and an embedded
thumbnail of the *unredacted* original, and no existing check would fail.

Run directly (`python test_metadata_stripping.py`) or under pytest.
"""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

from PIL import Image

from redactor.hygiene import sanitize_for_processing, save_clean

GPS_IFD = 0x8825
ORIENTATION = 0x0112
DESCRIPTION = 0x010E
MODEL = 0x0110


def _make_tagged_jpeg(path: Path, orientation: int | None = None) -> None:
    """A JPEG carrying GPS, device, description and an original thumbnail."""
    base = Image.new("RGB", (400, 300), "white")
    secret = Image.new("RGB", (160, 120), "red")  # stands in for the original
    buf = io.BytesIO()
    secret.save(buf, format="JPEG")

    exif = Image.Exif()
    exif[GPS_IFD] = {1: "N", 2: (12.0, 58.0, 0.0), 3: "E", 4: (77.0, 35.0, 0.0)}
    exif[DESCRIPTION] = "Aadhaar of a real person"
    exif[MODEL] = "iPhone 15 Pro"
    if orientation:
        exif[ORIENTATION] = orientation

    base.save(path, exif=exif.tobytes(), thumbnail=buf.getvalue())


def test_sanitize_drops_all_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "tagged.jpg"
        _make_tagged_jpeg(src)

        original = Image.open(src)
        assert GPS_IFD in original.getexif(), "fixture should carry GPS"

        clean = sanitize_for_processing(original)
        assert len(clean.getexif()) == 0, "EXIF survived sanitize"
        assert not clean.info.get("exif"), "info['exif'] survived sanitize"


def test_saved_file_has_no_gps_or_thumbnail() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "tagged.jpg", Path(tmp) / "out.jpg"
        _make_tagged_jpeg(src)

        save_clean(sanitize_for_processing(Image.open(src)), dst)

        assert len(Image.open(dst).getexif()) == 0, "EXIF survived the save"

        raw = dst.read_bytes()
        for needle in (b"Exif", b"iPhone", b"Aadhaar"):
            assert needle not in raw, f"{needle!r} survived into the output file"
        # A second JPEG start-of-image marker means an embedded thumbnail.
        assert raw.count(b"\xff\xd8\xff") == 1, "embedded thumbnail survived"


def test_orientation_is_baked_in_not_discarded() -> None:
    """A sideways phone photo must come out upright.

    Dropping the orientation tag without applying it would leave OCR
    reading a rotated page, which finds almost nothing.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "rotated.jpg"
        _make_tagged_jpeg(src, orientation=6)  # rotate 90° CW

        original = Image.open(src)
        assert original.size == (400, 300)

        clean = sanitize_for_processing(original)
        assert clean.size == (300, 400), "orientation was not applied"
        assert len(clean.getexif()) == 0, "orientation tag left behind"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

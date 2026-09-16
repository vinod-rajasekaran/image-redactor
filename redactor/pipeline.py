"""The per-image redaction pipeline and engine assembly.

Order of work per image: sanitize, build preprocessed variants, analyse
them concurrently alongside the visual detectors, union the boxes, merge
stacked blocks, draw, save.
"""
from __future__ import annotations

import logging
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

# Tesseract reads small text poorly, and its own guidance is about
# **character height**, not image size: capitals should be roughly 30px.
# An earlier rule here targeted a 600px image width, which is a proxy for
# nothing — a 2000px scan of 8px text would be left alone while a 300px
# crop of large type would be tripled.
#
# Text height is estimated from connected components rather than a probe
# OCR pass, which would double the cost of the thing being optimised.
AUTO_UPSCALE_TARGET_TEXT_HEIGHT = 24
AUTO_UPSCALE_MAX_FACTOR = 3

# Upscaling an image that is already large makes things worse, not better.
# Tripling a 2365px cheque produces a 7095px image and Tesseract reads it
# *less* well: measured, the MICR line went from 60% covered to 0%, and the
# account number from 40% to 30%. Small text on a big page is a property of
# a dense document, and the fix for that is a better backend, not more
# pixels. Cap the result rather than the factor.
AUTO_UPSCALE_MAX_LONG_SIDE = 2400


@dataclass
class ImageResult:
    filename: str
    status: str  # "processed" | "no_pii_found" | "failed"
    entities: dict[str, int] = field(default_factory=dict)
    entity_count: int = 0
    avg_confidence: float | None = None
    error: str | None = None
    duration_seconds: float = 0.0
    upscale_factor: int = 1
    visual_regions: dict[str, int] = field(default_factory=dict)
    decodable_codes: list[str] = field(default_factory=list)
    clinical_withdrawn: int = 0


def estimate_text_height(image) -> int:
    """Median height of the text-like connected components, in pixels.

    Cheap stand-in for "how tall are the characters": binarise, take
    connected components, keep the ones shaped like glyphs, and report the
    median height. Returns 0 when nothing text-like is found, which the
    caller treats as "leave it alone" — a blank or purely pictorial page
    gains nothing from upscaling.
    """
    import cv2
    import numpy as np

    grey = np.asarray(image.convert("L"))
    binary = cv2.threshold(
        grey, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    page_height = grey.shape[0]
    heights = [
        stats[i, cv2.CC_STAT_HEIGHT]
        for i in range(1, count)
        # Glyph-shaped: taller than noise, shorter than a rule or border,
        # and not absurdly wide for its height (which is a line, not a letter).
        if 4 <= stats[i, cv2.CC_STAT_HEIGHT] <= page_height * 0.1
        and stats[i, cv2.CC_STAT_WIDTH] <= stats[i, cv2.CC_STAT_HEIGHT] * 6
    ]
    return int(np.median(heights)) if len(heights) >= 20 else 0


def resolve_upscale_factor(image_or_width, setting: str) -> int:
    """Pick the OCR upscale factor, aiming at a readable character height.

    Accepts a PIL image; an integer width is still accepted so older calls
    and tests keep working, and falls back to leaving the image alone,
    since width alone cannot say how tall the text is.
    """
    if setting != "auto":
        return int(setting)
    if isinstance(image_or_width, int):
        return 1
    height = estimate_text_height(image_or_width)
    if height <= 0:
        return 1
    factor = round(AUTO_UPSCALE_TARGET_TEXT_HEIGHT / height)
    factor = max(1, min(AUTO_UPSCALE_MAX_FACTOR, factor))
    long_side = max(image_or_width.width, image_or_width.height)
    while factor > 1 and long_side * factor > AUTO_UPSCALE_MAX_LONG_SIDE:
        factor -= 1
    return factor


def check_prerequisites(logger: logging.Logger, ocr_backend: str = "tesseract") -> None:
    """Fail fast with an actionable message if a dependency is missing."""
    if ocr_backend == "paddle":
        try:
            import paddleocr  # noqa: F401
        except ImportError:
            logger.error(
                "[red]PaddleOCR is not installed.[/red] Run: "
                "[bold]pip install paddleocr paddlepaddle[/bold]"
            )
            sys.exit(1)
    elif shutil.which("tesseract") is None:
        logger.error(
            "[red]Tesseract binary not found on PATH.[/red] "
            "Install it with: [bold]brew install tesseract[/bold] "
            "(or run ./setup.sh)"
        )
        sys.exit(1)

    try:
        import spacy

        try:
            spacy.load("en_core_web_lg")
        except OSError:
            logger.error(
                "[red]spaCy model 'en_core_web_lg' not found.[/red] Install it with: "
                "[bold]python -m spacy download en_core_web_lg[/bold] (or run ./setup.sh)"
            )
            sys.exit(1)
    except ImportError:
        logger.error(
            "[red]spaCy is not installed.[/red] Run: [bold]pip install -r requirements.txt[/bold]"
        )
        sys.exit(1)



def build_engines(
    logger: logging.Logger,
    ocr_tolerant_aadhaar: bool = True,
    ocr_backend: str = "tesseract",
    psm: int | None = None,
    medical_ner: bool = False,
    reading_order: bool = True,
):
    """Construct Presidio's image analyzer + redactor engines."""
    from presidio_analyzer import AnalyzerEngine
    from presidio_image_redactor import ImageAnalyzerEngine, ImageRedactorEngine

    from .ocr import build_ocr
    from .recognizers import build_nlp_engine, build_registry

    registry = build_registry(
        logger, ocr_tolerant_aadhaar=ocr_tolerant_aadhaar, medical_ner=medical_ner
    )
    analyzer_engine = AnalyzerEngine(registry=registry, nlp_engine=build_nlp_engine())
    logger.info("Loading OCR backend: [bold]%s[/bold]", ocr_backend)
    image_analyzer = ImageAnalyzerEngine(
        analyzer_engine=analyzer_engine, ocr=build_ocr(ocr_backend, psm, reading_order)
    )
    redactor = ImageRedactorEngine(image_analyzer_engine=image_analyzer)
    return image_analyzer, redactor


def _vlm_regions_for(image, options: dict) -> list:
    """Ask a vision model where the PII is. Never fails an image.

    Union, not substitution: a model that misses something the regex layer
    caught must not be able to remove a box, and a model that is down must
    not be able to stop a run.
    """
    from . import vlm as vlm_module

    try:
        return vlm_module.detect_pii_regions(
            image,
            base_url=options.get("url", vlm_module.DEFAULT_URL),
            model=options.get("model", vlm_module.DEFAULT_MODEL),
            timeout=options.get("timeout", vlm_module.DEFAULT_TIMEOUT),
        )
    except Exception:
        return []


def _labelled_values_for(analyzer, image, factor: int) -> list:
    """Run the analyzer's own OCR over one variant and locate labelled values.

    Uses `analyzer.ocr` so this cannot drift from the backend, PSM and
    reading-order wrapper the detection path uses — a second OCR
    configuration would be a second set of boxes with no way to tell which
    was right.
    """
    import numpy as np

    from .labels import detect_labelled_values

    try:
        result = analyzer.ocr.perform_ocr(np.asarray(image))
        return detect_labelled_values(result, scale=factor)
    except Exception:  # never let this path fail an image
        return []


def _clinical_regions_for(analyzer, image, factor: int) -> list:
    """Locate clinical content on one variant, so boxes on it can be withdrawn.

    Failure here must never fail the image, and must never *widen* what is
    withdrawn: an empty list means nothing is protected, which is the safe
    direction.
    """
    import numpy as np

    from .clinical import protected_regions

    try:
        result = analyzer.ocr.perform_ocr(np.asarray(image))
        return protected_regions(result, analyzer.analyzer_engine, factor)
    except Exception:
        return []


def process_image(
    path: Path,
    output_dir: Path,
    analyzer,
    redactor,
    logger: logging.Logger,
    analyzer_kwargs: dict | None = None,
    upscale: str = "auto",
    visual_pii: bool = True,
    use_pyzbar: bool = False,
    use_wechat: bool = False,
    variant_union: bool = True,
    style: str = "solid",
    merge_blocks: bool = True,
    label_anchored: bool = True,
    protect_clinical: bool = False,
    vlm: dict | None = None,
) -> ImageResult:
    from PIL import Image

    from .detect import detect_visual_pii
    from .labels import detect_labelled_values
    from .geometry import VisualRegion, merge_same_type_blocks
    from .hygiene import sanitize_for_processing, save_clean
    from .render import redact_regions
    from .variants import build_ocr_variants

    analyzer_kwargs = analyzer_kwargs or {}
    start = time.monotonic()
    try:
        image = Image.open(path)
        image.load()
        # Orientation baked in, EXIF/GPS/thumbnail dropped, before anything
        # else touches the image — so no later path can carry them through.
        image = sanitize_for_processing(image)
    except Exception as exc:
        logger.error("[red]Failed to open %s: %s[/red]", path.name, exc)
        return ImageResult(
            filename=path.name,
            status="failed",
            error=f"open_failed: {exc}",
            duration_seconds=time.monotonic() - start,
        )

    factor = resolve_upscale_factor(image, upscale)
    variants = build_ocr_variants(image, factor, union=variant_union)

    # Text variants and the visual detectors are independent, so they run
    # concurrently. Threads, not processes: pytesseract shells out and
    # releases the GIL, and a shared AnalyzerEngine was verified to give
    # byte-identical results threaded vs serial across the sample set.
    try:
        with ThreadPoolExecutor(max_workers=len(variants) + 1) as pool:
            text_jobs = [
                pool.submit(analyzer.analyze, v, **analyzer_kwargs) for v in variants
            ]
            visual_job = (
                pool.submit(
                    detect_visual_pii, image, True, True, use_pyzbar, use_wechat
                )
                if visual_pii
                else None
            )
            # Label-anchored boxes come from the same OCR pass the analyzer
            # runs, read for position rather than for pattern. Shapeless
            # identifiers — a customer ID, a sample ID, a bare registration
            # number — have no regex that can find them and are only ever
            # locatable by where they sit.
            label_jobs = [
                pool.submit(_labelled_values_for, analyzer, v, factor)
                for v in (variants if label_anchored else [])
            ]
            # A fourth parallel path, on the original image rather than a
            # preprocessed variant: the preprocessing exists to help OCR,
            # and a vision model does not want it.
            vlm_job = pool.submit(_vlm_regions_for, image, vlm) if vlm else None
            # Clinical protection needs word geometry for the whole page, so
            # it reads its own OCR pass; running it here keeps it off the
            # critical path rather than adding to it.
            clinical_job = (
                pool.submit(_clinical_regions_for, analyzer, variants[0], factor)
                if protect_clinical
                else None
            )
            per_variant = [job.result() for job in text_jobs]
            regions = visual_job.result() if visual_job else []
            label_regions = [job.result() for job in label_jobs]
            if vlm_job is not None:
                label_regions.append(vlm_job.result())
            clinical_regions = clinical_job.result() if clinical_job else []
    except Exception as exc:
        logger.exception("Analysis failed for %s", path.name)
        return ImageResult(
            filename=path.name,
            status="failed",
            error=f"analysis_failed: {exc}",
            duration_seconds=time.monotonic() - start,
            upscale_factor=factor,
        )

    # Union the variants. A box found by any variant counts; duplicates
    # cost nothing, since overlapping black rectangles are identical.
    seen: set[tuple] = set()
    raw_boxes: list[tuple] = []
    entities: dict[str, int] = {}
    scores: list[float] = []
    for results in per_variant:
        for r in results:
            box = (
                r.entity_type,
                r.left // factor,
                r.top // factor,
                r.width // factor,
                r.height // factor,
            )
            if box in seen:
                continue
            seen.add(box)
            entities[r.entity_type] = entities.get(r.entity_type, 0) + 1
            scores.append(r.score)
            raw_boxes.append(box)

    # A wrapped address is detected line by line and often only partly, so
    # redacting each box alone can never cover the words that were never
    # detected. The enclosing rectangle of a stacked cluster does.
    # Withdraw NER boxes sitting on clinical content, before merging —
    # merging first would fuse a drug name into a neighbouring real box and
    # make it unwithdrawable.
    clinical_withdrawn = 0
    if clinical_regions:
        from .clinical import suppress

        raw_boxes, clinical_withdrawn = suppress(raw_boxes, clinical_regions)

    if merge_blocks:
        raw_boxes = merge_same_type_blocks(raw_boxes)
    text_boxes = [VisualRegion("text", *b[1:]) for b in raw_boxes]

    # Unioned with the pattern boxes, not substituted for them: the two
    # find different things and overlapping rectangles cost nothing.
    labelled: list = []
    seen_label_boxes: set[tuple] = set()
    for found in label_regions:
        for region in found:
            key = (region.left, region.top, region.width, region.height)
            if key in seen_label_boxes:
                continue
            seen_label_boxes.add(key)
            labelled.append(region)
    text_boxes.extend(labelled)

    visual_counts: dict[str, int] = {}
    for r in regions:
        visual_counts[r.kind] = visual_counts.get(r.kind, 0) + 1
    decodable = [r.kind for r in regions if r.decoded_payload]

    if not text_boxes and not regions:
        logger.info(
            "[yellow]%s[/yellow]: no PII detected (copied through)", path.name
        )
        try:
            save_clean(image, output_dir / path.name)
        except Exception as exc:
            logger.exception("Copy-through failed for %s", path.name)
            return ImageResult(
                filename=path.name,
                status="failed",
                error=f"copy_through_failed: {exc}",
                duration_seconds=time.monotonic() - start,
                upscale_factor=factor,
            )
        return ImageResult(
            filename=path.name,
            status="no_pii_found",
            duration_seconds=time.monotonic() - start,
            upscale_factor=factor,
        )

    # Boxes are drawn here rather than by ImageRedactorEngine.redact(),
    # which would re-run the whole OCR and analysis pass a second time —
    # measured at 7.6s of a 17.4s run. Drawing directly also keeps the
    # output in colour, since the enhanced variants are greyscale.
    try:
        redacted_image = redact_regions(image, text_boxes + regions, style=style)
        save_clean(redacted_image, output_dir / path.name)
    except Exception as exc:
        logger.exception("Redaction/save failed for %s", path.name)
        return ImageResult(
            filename=path.name,
            status="failed",
            error=f"redaction_failed: {exc}",
            duration_seconds=time.monotonic() - start,
            upscale_factor=factor,
        )

    duration = time.monotonic() - start
    visual_note = (
        " + " + ", ".join(f"{v}x {k}" for k, v in sorted(visual_counts.items()))
        if visual_counts
        else ""
    )
    logger.info(
        "[green]%s[/green]: redacted %d entities (%s)%s%s%s in %.2fs",
        path.name,
        len(text_boxes),
        ", ".join(sorted(entities)) or "none",
        visual_note,
        f" [dim]-{clinical_withdrawn} clinical[/dim]" if clinical_withdrawn else "",
        f" [dim]@{factor}x[/dim]" if factor != 1 else "",
        duration,
    )
    return ImageResult(
        filename=path.name,
        status="processed",
        entities=entities,
        entity_count=len(text_boxes),
        avg_confidence=round(sum(scores) / len(scores), 3) if scores else None,
        duration_seconds=duration,
        upscale_factor=factor,
        visual_regions=visual_counts,
        decodable_codes=decodable,
        clinical_withdrawn=clinical_withdrawn,
    )



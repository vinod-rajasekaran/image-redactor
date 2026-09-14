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

# Tesseract reads small photographed documents poorly; upscaling before OCR
# recovers text it otherwise misses entirely. Narrower inputs than this get
# scaled up toward it (integer factor, capped) purely for the OCR pass.
AUTO_UPSCALE_TARGET_WIDTH = 600
AUTO_UPSCALE_MAX_FACTOR = 3


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


def resolve_upscale_factor(width: int, setting: str) -> int:
    """Pick the OCR upscale factor for an image of this width."""
    if setting != "auto":
        return int(setting)
    factor = round(AUTO_UPSCALE_TARGET_WIDTH / width) if width else 1
    return max(1, min(AUTO_UPSCALE_MAX_FACTOR, factor))


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
    from .recognizers import build_registry

    registry = build_registry(
        logger, ocr_tolerant_aadhaar=ocr_tolerant_aadhaar, medical_ner=medical_ner
    )
    analyzer_engine = AnalyzerEngine(registry=registry)
    logger.info("Loading OCR backend: [bold]%s[/bold]", ocr_backend)
    image_analyzer = ImageAnalyzerEngine(
        analyzer_engine=analyzer_engine, ocr=build_ocr(ocr_backend, psm, reading_order)
    )
    redactor = ImageRedactorEngine(image_analyzer_engine=image_analyzer)
    return image_analyzer, redactor


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
) -> ImageResult:
    from PIL import Image

    from .detect import detect_visual_pii
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

    factor = resolve_upscale_factor(image.width, upscale)
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
            per_variant = [job.result() for job in text_jobs]
            regions = visual_job.result() if visual_job else []
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
    if merge_blocks:
        raw_boxes = merge_same_type_blocks(raw_boxes)
    text_boxes = [VisualRegion("text", *b[1:]) for b in raw_boxes]

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
        "[green]%s[/green]: redacted %d entities (%s)%s%s in %.2fs",
        path.name,
        len(text_boxes),
        ", ".join(sorted(entities)) or "none",
        visual_note,
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
    )



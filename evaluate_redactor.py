#!/usr/bin/env python3
"""Evaluate Presidio's image redactor against a folder of input images.

Pipeline per image (all local, no cloud calls):
    1. OCR (Tesseract or PaddleOCR) extracts text + bounding boxes.
    2. Presidio's AnalyzerEngine (spaCy NLP) finds PII entities in that
       text.
    3. Presidio's ImageRedactorEngine blacks out those regions.
    4. Optionally, faces and QR/barcodes are detected and blacked out too,
       which Presidio does not do at all.

Each run writes a self-describing folder containing the config it ran
with, a results summary, the log, and the redacted images.

Usage:
    python evaluate_redactor.py [--input input_images] [--runs-dir runs]
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from ocr_backends import OCR_BACKENDS

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

# Tesseract reads small photographed documents poorly; upscaling before OCR
# recovers text it otherwise misses entirely. Narrower inputs than this get
# scaled up toward it (integer factor, capped) purely for the OCR pass.
AUTO_UPSCALE_TARGET_WIDTH = 600
AUTO_UPSCALE_MAX_FACTOR = 3

console = Console()


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


def setup_logging(output_dir: Path) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "run.log"

    logger = logging.getLogger("evaluate_redactor")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    console_handler = RichHandler(
        console=console, show_path=False, rich_tracebacks=True, markup=True
    )
    console_handler.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    file_handler.setLevel(logging.DEBUG)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


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


def build_aadhaar_ocr_fallback_recognizer():
    """A checksum-free IN_AADHAAR recognizer for OCR-garbled numbers.

    Presidio's InAadhaarRecognizer validates a Verhoeff checksum and DROPS
    the match outright when it fails — so a single OCR digit error means a
    real Aadhaar number is not redacted at all.

    The grouped 4-4-4 form scores high enough to fire on its own, because
    OCR of a two-column form emits every label before every value, which
    strands the "Aadhaar" context word far from its number and makes
    context-based scoring unreliable.

    It deliberately carries no look-around guards against matching inside a
    longer digit run. OCR flattens the page into one string with no field
    boundaries, so a neighbouring phone number is indistinguishable from a
    continuation of the same number, and guards drop real Aadhaars. The
    cost is that a credit card or account number also matches here; those
    spans are redacted as CREDIT_CARD/DATE_TIME regardless, so the
    over-match costs label precision in the report, not redaction quality.

    The ungrouped 12-digit form is weaker and still needs context.
    """
    from presidio_analyzer import Pattern, PatternRecognizer

    return PatternRecognizer(
        supported_entity="IN_AADHAAR",
        name="AadhaarOcrFallbackRecognizer",
        patterns=[
            Pattern(
                "Aadhaar 4-4-4 grouped (no checksum)",
                r"\b[0-9]{4}[- :][0-9]{4}[- :][0-9]{4}\b",
                0.5,
            ),
            Pattern("Aadhaar 12-digit (no checksum)", r"\b[0-9]{12}\b", 0.2),
        ],
        context=["aadhaar", "aadhar", "uidai", "uid"],
    )


INDIA_RECOGNIZER_NAMES = [
    "InAadhaarRecognizer",
    "InPanRecognizer",
    "InVoterRecognizer",
    "InPassportRecognizer",
    "InVehicleRegistrationRecognizer",
    "InGstinRecognizer",
]


def build_engines(
    logger: logging.Logger,
    ocr_tolerant_aadhaar: bool = True,
    ocr_backend: str = "tesseract",
):
    """Construct Presidio's image analyzer + redactor engines.

    Presidio only registers US/UK recognizers by default, so the
    India-specific ones are added explicitly here.
    """
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
    from presidio_analyzer import predefined_recognizers
    from presidio_image_redactor import ImageAnalyzerEngine, ImageRedactorEngine

    from ocr_backends import build_ocr

    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()

    for name in INDIA_RECOGNIZER_NAMES:
        registry.add_recognizer(getattr(predefined_recognizers, name)())
    logger.info(
        "Registered %d India-specific recognizers: %s",
        len(INDIA_RECOGNIZER_NAMES),
        ", ".join(INDIA_RECOGNIZER_NAMES),
    )

    if ocr_tolerant_aadhaar:
        registry.add_recognizer(build_aadhaar_ocr_fallback_recognizer())
        logger.info(
            "OCR-tolerant Aadhaar fallback enabled "
            "(catches checksum-invalid numbers near Aadhaar context words)"
        )

    analyzer_engine = AnalyzerEngine(registry=registry)
    logger.info("Loading OCR backend: [bold]%s[/bold]", ocr_backend)
    image_analyzer = ImageAnalyzerEngine(
        analyzer_engine=analyzer_engine, ocr=build_ocr(ocr_backend)
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
) -> ImageResult:
    from PIL import Image

    from visual_redaction import detect_visual_pii, redact_regions

    analyzer_kwargs = analyzer_kwargs or {}
    start = time.monotonic()
    try:
        image = Image.open(path)
        image.load()
    except Exception as exc:
        logger.error("[red]Failed to open %s: %s[/red]", path.name, exc)
        return ImageResult(
            filename=path.name,
            status="failed",
            error=f"open_failed: {exc}",
            duration_seconds=time.monotonic() - start,
        )

    factor = resolve_upscale_factor(image.width, upscale)
    ocr_image = (
        image
        if factor == 1
        else image.resize(
            (image.width * factor, image.height * factor), Image.LANCZOS
        )
    )

    try:
        analyzer_results = analyzer.analyze(ocr_image, **analyzer_kwargs)
    except Exception as exc:
        logger.exception("OCR/analysis failed for %s", path.name)
        return ImageResult(
            filename=path.name,
            status="failed",
            error=f"analysis_failed: {exc}",
            duration_seconds=time.monotonic() - start,
            upscale_factor=factor,
        )

    regions = []
    if visual_pii:
        try:
            regions = detect_visual_pii(
                image, use_pyzbar=use_pyzbar, use_wechat=use_wechat
            )
        except Exception:
            logger.exception("Visual PII detection failed for %s", path.name)
    visual_counts: dict[str, int] = {}
    for r in regions:
        visual_counts[r.kind] = visual_counts.get(r.kind, 0) + 1
    decodable = [r.kind for r in regions if r.decoded_payload]

    entities: dict[str, int] = {}
    scores: list[float] = []
    for result in analyzer_results:
        entities[result.entity_type] = entities.get(result.entity_type, 0) + 1
        scores.append(result.score)

    if not analyzer_results and not regions:
        # Copy through unchanged so the output folder stays a complete mirror
        # of the input — a consumer of that folder must not silently lose files.
        logger.info(
            "[yellow]%s[/yellow]: no PII entities detected (copied through)",
            path.name,
        )
        try:
            image.save(output_dir / path.name)
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

    try:
        if analyzer_results:
            redacted_image = redactor.redact(
                ocr_image, fill=(0, 0, 0), **analyzer_kwargs
            )
            if factor != 1:
                redacted_image = redacted_image.resize(image.size, Image.LANCZOS)
        else:
            redacted_image = image
        if regions:
            redacted_image = redact_regions(redacted_image, regions)
        output_path = output_dir / path.name
        redacted_image.save(output_path)
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
        len(analyzer_results),
        ", ".join(sorted(entities)) or "none",
        visual_note,
        f" [dim]@{factor}x[/dim]" if factor != 1 else "",
        duration,
    )
    return ImageResult(
        filename=path.name,
        status="processed",
        entities=entities,
        entity_count=len(analyzer_results),
        avg_confidence=round(sum(scores) / len(scores), 3) if scores else None,
        duration_seconds=duration,
        upscale_factor=factor,
        visual_regions=visual_counts,
        decodable_codes=decodable,
    )


def print_summary(results: list[ImageResult]) -> None:
    processed = [r for r in results if r.status == "processed"]
    no_pii = [r for r in results if r.status == "no_pii_found"]
    failed = [r for r in results if r.status == "failed"]

    entity_totals: dict[str, int] = {}
    for r in processed:
        for etype, count in r.entities.items():
            entity_totals[etype] = entity_totals.get(etype, 0) + count

    table = Table(title="Entities Redacted by Type")
    table.add_column("Entity Type", style="cyan")
    table.add_column("Count", justify="right", style="magenta")
    for etype, count in sorted(entity_totals.items(), key=lambda kv: -kv[1]):
        table.add_row(etype, str(count))

    console.print(table)

    visual_totals: dict[str, int] = {}
    for r in results:
        for kind, count in r.visual_regions.items():
            visual_totals[kind] = visual_totals.get(kind, 0) + count
    if visual_totals:
        vtable = Table(title="Visual Regions Redacted")
        vtable.add_column("Kind", style="cyan")
        vtable.add_column("Count", justify="right", style="magenta")
        for kind, count in sorted(visual_totals.items(), key=lambda kv: -kv[1]):
            vtable.add_row(kind, str(count))
        console.print(vtable)

    summary_lines = [
        f"Total images: {len(results)}",
        f"[green]Redacted:[/green] {len(processed)}",
        f"[yellow]No PII found:[/yellow] {len(no_pii)}",
        f"[red]Failed:[/red] {len(failed)}",
    ]
    console.print(Panel("\n".join(summary_lines), title="Run Summary", expand=False))

    if failed:
        fail_table = Table(title="Failures")
        fail_table.add_column("File", style="red")
        fail_table.add_column("Error")
        for r in failed:
            fail_table.add_row(r.filename, r.error or "unknown")
        console.print(fail_table)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", default="input_images", help="Folder of images to redact"
    )
    parser.add_argument(
        "--runs-dir",
        default="runs",
        help="Parent folder under which each run gets its own folder",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Name for this run's folder (default: timestamp + settings)",
    )
    parser.add_argument(
        "--ocr",
        default="tesseract",
        choices=list(OCR_BACKENDS),
        help="OCR backend (default: tesseract)",
    )
    parser.add_argument(
        "--no-visual-pii",
        dest="visual_pii",
        action="store_false",
        help=(
            "Skip face and QR/barcode redaction. On by default: Presidio "
            "redacts only OCR'd text, and an intact Aadhaar QR still carries "
            "the holder's name, DOB and address"
        ),
    )
    parser.add_argument(
        "--pyzbar",
        action="store_true",
        help=(
            "Additionally run pyzbar to decode code payloads. Off by default: "
            "OpenCV's detectors locate codes pyzbar cannot decode, and pyzbar "
            "needs the zbar system library"
        ),
    )
    parser.add_argument(
        "--wechat-qr",
        action="store_true",
        help=(
            "Additionally run the WeChat QR detector (needs models/, see "
            "setup.sh). Supplements rather than replaces the stock detector: "
            "it is better on small/blurry real QR codes and returns payloads, "
            "but yields no box for a code it cannot decode"
        ),
    )
    parser.set_defaults(visual_pii=True)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.4,
        help=(
            "Minimum Presidio confidence score to redact (default: 0.4). "
            "Deliberately below Presidio's usual 0.5: context-boosted weak "
            "patterns land at 0.45, so 0.5 silently misses PAN/voter/passport"
        ),
    )
    parser.add_argument(
        "--entities",
        nargs="+",
        default=None,
        help="Restrict detection to these entity types (default: all supported)",
    )
    parser.add_argument(
        "--upscale",
        default="auto",
        choices=["auto", "1", "2", "3", "4"],
        help=(
            "Upscale factor applied before OCR only (output keeps the original "
            "size). 'auto' scales narrow images toward %dpx wide; '1' disables"
            % AUTO_UPSCALE_TARGET_WIDTH
        ),
    )
    parser.add_argument(
        "--strict-aadhaar",
        action="store_true",
        help=(
            "Disable the OCR-tolerant Aadhaar fallback, so only numbers with a "
            "valid Verhoeff checksum are redacted (matches stock Presidio)"
        ),
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    started_at = datetime.now(timezone.utc)
    run_name = args.run_name or (
        f"{started_at.strftime('%Y%m%d-%H%M%S')}_{args.ocr}"
        f"_{'visual' if args.visual_pii else 'textonly'}"
    )
    run_dir = Path(args.runs_dir) / run_name
    output_dir = run_dir / "images"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging(run_dir)

    if not input_dir.exists() or not input_dir.is_dir():
        logger.error(
            "[red]Input folder '%s' does not exist.[/red] Create it and add images, "
            "or run generate_test_images.py to create sample images.",
            input_dir,
        )
        sys.exit(1)

    image_paths = sorted(
        p for p in input_dir.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if not image_paths:
        logger.error(
            "[red]No supported images found in '%s'.[/red] Supported extensions: %s",
            input_dir,
            ", ".join(sorted(SUPPORTED_EXTENSIONS)),
        )
        sys.exit(1)

    check_prerequisites(logger, args.ocr)

    console.rule(f"[bold blue]Presidio Image Redactor Evaluation — {run_name}")

    config = {
        "run_name": run_name,
        "started_at": started_at.isoformat(),
        "input_dir": str(input_dir),
        "image_count": len(image_paths),
        "ocr_backend": args.ocr,
        "visual_pii": args.visual_pii,
        "pyzbar": args.pyzbar,
        "wechat_qr": args.wechat_qr,
        "score_threshold": args.threshold,
        "entities": args.entities or "all_supported",
        "ocr_tolerant_aadhaar": not args.strict_aadhaar,
        "upscale": args.upscale,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    (run_dir / "config.json").write_text(json.dumps(config, indent=2))
    logger.info("Run config written to [bold]%s[/bold]", run_dir / "config.json")

    logger.info("Loading local OCR + Presidio analyzer engines...")
    analyzer, redactor = build_engines(
        logger,
        ocr_tolerant_aadhaar=not args.strict_aadhaar,
        ocr_backend=args.ocr,
    )

    analyzer_kwargs: dict = {"score_threshold": args.threshold}
    if args.entities:
        analyzer_kwargs["entities"] = args.entities
    logger.info(
        "Score threshold: %.2f | Entities: %s | Visual PII: %s",
        args.threshold,
        ", ".join(args.entities) if args.entities else "all supported",
        "on" if args.visual_pii else "off",
    )

    results: list[ImageResult] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing images", total=len(image_paths))
        for path in image_paths:
            progress.update(task, description=f"Processing [bold]{path.name}[/bold]")
            result = process_image(
                path,
                output_dir,
                analyzer,
                redactor,
                logger,
                analyzer_kwargs,
                args.upscale,
                args.visual_pii,
                args.pyzbar,
                args.wechat_qr,
            )
            results.append(result)
            progress.advance(task)

    print_summary(results)

    entity_totals: dict[str, int] = {}
    visual_totals: dict[str, int] = {}
    for r in results:
        for k, v in r.entities.items():
            entity_totals[k] = entity_totals.get(k, 0) + v
        for k, v in r.visual_regions.items():
            visual_totals[k] = visual_totals.get(k, 0) + v

    summary = {
        "config": config,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(sum(r.duration_seconds for r in results), 2),
        "totals": {
            "images": len(results),
            "processed": sum(1 for r in results if r.status == "processed"),
            "no_pii_found": sum(1 for r in results if r.status == "no_pii_found"),
            "failed": sum(1 for r in results if r.status == "failed"),
            "entities": sum(entity_totals.values()),
            "visual_regions": sum(visual_totals.values()),
        },
        "entities_by_type": dict(
            sorted(entity_totals.items(), key=lambda kv: -kv[1])
        ),
        "visual_regions_by_type": dict(
            sorted(visual_totals.items(), key=lambda kv: -kv[1])
        ),
        "results": [asdict(r) for r in results],
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    logger.info("Summary written to [bold]%s[/bold]", summary_path)
    console.print(f"[green]Run folder:[/green] [bold]{run_dir}[/bold]")

    if any(r.status == "failed" for r in results):
        sys.exit(2)


if __name__ == "__main__":
    main()

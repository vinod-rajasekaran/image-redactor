#!/usr/bin/env python3
"""Evaluate Presidio's image redactor against a folder of input images.

Per image (all local, no cloud calls): OCR several preprocessed variants
in parallel, find PII with Presidio, detect faces and QR/barcodes
alongside, union every box, and black out the result. Each run writes a
self-describing folder with the config it used, a summary, the log, and
the redacted images.

Usage:
    python evaluate_redactor.py [--input input_images] [--runs-dir runs]
"""
from __future__ import annotations

import argparse
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
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

from redactor.ocr import OCR_BACKENDS, TESSERACT_PSM_MODES
from redactor.recognizers import default_entities
from redactor.pipeline import (
    AUTO_UPSCALE_TARGET_TEXT_HEIGHT,
    SUPPORTED_EXTENSIONS,
    ImageResult,
    build_engines,
    check_prerequisites,
    process_image,
)
from redactor.render import REDACTION_STYLES
from redactor.runs import setup_logging, write_config, write_summary

console = Console()


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
        "--psm",
        type=int,
        default=4,
        choices=list(TESSERACT_PSM_MODES),
        help=(
            "Tesseract page-segmentation mode (default: 4, single column of "
            "variable-size text). Benchmarked at 76.5%% recall against 74.1%% "
            "for Tesseract's own default of 3, at no extra cost. Ignored by "
            "other backends"
        ),
    )
    parser.add_argument(
        "--no-reading-order",
        dest="reading_order",
        action="store_false",
        help=(
            "Do not re-sort OCR words top-to-bottom then left-to-right. On by "
            "default: without it, some segmentation modes emit every label "
            "before every value, stranding context words from the values they "
            "label and silently disabling context-scored recognizers"
        ),
    )
    parser.add_argument(
        "--no-merge-blocks",
        dest="merge_blocks",
        action="store_false",
        help=(
            "Do not merge vertically-stacked boxes of one entity type into "
            "their enclosing rectangle. On by default: a wrapped address is "
            "detected line by line and often only partly, leaving the "
            "undetected part of it legible"
        ),
    )
    parser.add_argument(
        "--style",
        default="solid",
        choices=list(REDACTION_STYLES),
        help=(
            "How to obscure PII. Only 'solid' destroys the information; blur "
            "and pixelate are partially reversible and are for review copies, "
            "not for output leaving a trusted environment"
        ),
    )
    parser.add_argument(
        "--single-variant",
        dest="variant_union",
        action="store_false",
        help=(
            "OCR only the plain upscaled image. By default three "
            "preprocessed variants (rgb, greyscale, CLAHE+Otsu) are OCR'd in "
            "parallel and their boxes unioned, because no single one wins on "
            "every document"
        ),
    )
    parser.add_argument(
        "--medical-ner",
        action="store_true",
        help=(
            "Also detect clinical entities (diagnoses, medications) with "
            "HuggingFace blaze999/Medical-NER. Off by default: pulls in "
            "transformers and downloads a model on first use"
        ),
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
    parser.add_argument(
        "--protect-clinical",
        action="store_true",
        help=(
            "Keep medications, dosages, diagnoses and procedures readable by "
            "withdrawing name/place/organisation boxes that land on them. For "
            "documents a clinician or downstream model must still read. "
            "Identifiers are never withdrawn — a checksum-validated Aadhaar "
            "inside a clinical sentence is still covered. Needs transformers"
        ),
    )
    parser.add_argument(
        "--dates",
        action="store_true",
        help=(
            "Also redact DATE_TIME. Off by default: a date of birth is "
            "personal data but a dosage schedule or statement period is not, "
            "and no entity type separates them — redacting all of them blacks "
            "out 'twice daily' and 'for 8 weeks' on a prescription. Dates of "
            "birth are covered by their label instead"
        ),
    )
    parser.add_argument(
        "--no-label-anchored",
        dest="label_anchored",
        action="store_false",
        help=(
            "Disable label-anchored redaction — covering the value beside a "
            "personal-data label regardless of its shape. Exists to measure "
            "the mechanism's contribution by A/B, not as a recommended setting"
        ),
    )
    parser.add_argument(
        "--vlm",
        action="store_true",
        help=(
            "Additionally ask a local vision model where the PII is, and "
            "union its boxes with everything else. Needs an OpenAI-compatible "
            "server (ollama serve, or LM Studio's). Off by default: it is "
            "orders of magnitude slower than OCR and its value over the "
            "deterministic layer is what --vlm exists to measure"
        ),
    )
    parser.add_argument(
        "--vlm-url",
        default=None,
        help="OpenAI-compatible base URL (default: Ollama on :11434/v1; "
             "LM Studio is http://localhost:1234/v1)",
    )
    parser.add_argument(
        "--vlm-model",
        default=None,
        help="Vision model id, e.g. qwen2.5vl:3b. On 8GB machines stay at 3B "
             "or below",
    )
    parser.add_argument(
        "--vlm-timeout", type=int, default=None,
        help="Seconds to wait per image (default: 180)",
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
            "Upscale factor applied before OCR only (output keeps the "
            "original size). 'auto' scales so text is about %dpx tall, which "
            "is what Tesseract's accuracy depends on; '1' disables"
            % AUTO_UPSCALE_TARGET_TEXT_HEIGHT
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

    vlm_options = None
    if args.vlm:
        from redactor import vlm as vlm_module

        vlm_options = {
            "url": args.vlm_url or vlm_module.DEFAULT_URL,
            "model": args.vlm_model or vlm_module.DEFAULT_MODEL,
            "timeout": args.vlm_timeout or vlm_module.DEFAULT_TIMEOUT,
        }
        # Fail here rather than silently produce a run with no VLM boxes:
        # `_vlm_regions_for` swallows per-image errors by design, so an
        # unreachable server would otherwise look like a model that found
        # nothing.
        served = vlm_module.available(vlm_options["url"])
        if not served:
            console.print(
                f"[red]No OpenAI-compatible server at {vlm_options['url']}[/red]\n"
                "  ollama serve     (then: ollama pull qwen2.5vl:3b)\n"
                "  or LM Studio -> Developer -> Start Server, then "
                "--vlm-url http://localhost:1234/v1"
            )
            sys.exit(1)
        if vlm_options["model"] not in served:
            console.print(
                f"[red]{vlm_options['model']!r} is not served by "
                f"{vlm_options['url']}[/red]\n"
                f"Available: {', '.join(served) or 'none'}"
            )
            sys.exit(1)
        logger.info(
            "Vision model enabled: [bold]%s[/bold] at %s",
            vlm_options["model"], vlm_options["url"],
        )

    console.rule(f"[bold blue]Presidio Image Redactor Evaluation — {run_name}")

    config = {
        "run_name": run_name,
        "started_at": started_at.isoformat(),
        "input_dir": str(input_dir),
        "image_count": len(image_paths),
        "ocr_backend": args.ocr,
        "psm": args.psm,
        "medical_ner": args.medical_ner,
        "reading_order": args.reading_order,
        "variant_union": args.variant_union,
        "style": args.style,
        "merge_blocks": args.merge_blocks,
        "label_anchored": args.label_anchored,
        "protect_clinical": args.protect_clinical,
        "visual_pii": args.visual_pii,
        "pyzbar": args.pyzbar,
        "wechat_qr": args.wechat_qr,
        "score_threshold": args.threshold,
        "entities": args.entities or (
            "all_supported" if args.dates else "all_supported_except_DATE_TIME"
        ),
        "ocr_tolerant_aadhaar": not args.strict_aadhaar,
        "upscale": args.upscale,
        "vlm": vlm_options,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    logger.info("Run config written to [bold]%s[/bold]", write_config(run_dir, config))

    logger.info("Loading local OCR + Presidio analyzer engines...")
    analyzer, redactor = build_engines(
        logger,
        ocr_tolerant_aadhaar=not args.strict_aadhaar,
        ocr_backend=args.ocr,
        psm=args.psm,
        medical_ner=args.medical_ner,
        reading_order=args.reading_order,
    )

    analyzer_kwargs: dict = {"score_threshold": args.threshold}
    if args.entities:
        analyzer_kwargs["entities"] = args.entities
    elif not args.dates:
        # Restrict to everything except the deliberately excluded types.
        # Presidio treats "no entities argument" as "all of them", so the
        # exclusion has to be expressed as an explicit list.
        analyzer_kwargs["entities"] = default_entities(analyzer.analyzer_engine.registry)
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
                args.variant_union,
                args.style,
                args.merge_blocks,
                args.label_anchored,
                args.protect_clinical,
                vlm=vlm_options,
            )
            results.append(result)
            progress.advance(task)

    print_summary(results)

    summary_path = write_summary(run_dir, config, results, started_at)
    logger.info("Summary written to [bold]%s[/bold]", summary_path)
    console.print(f"[green]Run folder:[/green] [bold]{run_dir}[/bold]")

    if any(r.status == "failed" for r in results):
        sys.exit(2)


if __name__ == "__main__":
    main()

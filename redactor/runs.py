"""Run folders: logging, config.json and summary.json.

Each run is self-describing so results stay reproducible and comparable;
a single overwritten output folder loses the settings that produced it.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

console = Console()

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




def write_config(run_dir: Path, config: dict) -> Path:
    path = run_dir / "config.json"
    path.write_text(json.dumps(config, indent=2))
    return path


def write_summary(run_dir: Path, config: dict, results, started: datetime) -> Path:
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
        "entities_by_type": dict(sorted(entity_totals.items(), key=lambda kv: -kv[1])),
        "visual_regions_by_type": dict(
            sorted(visual_totals.items(), key=lambda kv: -kv[1])
        ),
        "results": [asdict(r) for r in results],
    }
    path = run_dir / "summary.json"
    path.write_text(json.dumps(summary, indent=2))
    return path

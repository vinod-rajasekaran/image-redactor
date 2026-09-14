#!/usr/bin/env python3
"""Score a run's redacted images with Claude vision instead of OCR.

The OCR scorer can only see what its OCR sees, and on exactly the
low-contrast photographs where redaction fails it reads almost nothing.
It has been wrong in both directions because of that: reporting plainly
visible PII as "unverifiable", and reporting it as "redacted". On one
laptop-screen form it recovered the words "personal" and "details" from a
page whose address is legible at a glance.

This asks Claude to look at each redacted output image and say, for every
PII value the ground truth says is on that page, whether it is still
readable. Output goes to `runs/<run>/vision_verdicts.json`, which
`score_run.py` picks up automatically and prefers over its own verdicts.

Setup:
    echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env
    pip install anthropic

Usage:
    python vision_score.py runs/<run-name> [--model claude-opus-5]

Costs real money — one vision request per image with PII in it.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from rich.console import Console

console = Console()

PROMPT = """You are auditing a redacted document image for a privacy tool.

The unredacted original contained the personal data values listed below.
Redaction boxes (solid, blurred or pixelated) should have made them
unreadable.

For each value, decide whether it is STILL READABLE in this image:

- "leaked"   - you can read the value, or enough of it to recover the
               whole. A legible given name counts as leaked.
- "redacted" - it is covered, blurred, pixelated, or only a fragment too
               short to identify anyone remains (a postcode tail, the last
               letters of a surname).

Judge only what you can actually see in this image. Do not assume a value
is redacted because it ought to be, and do not guess at text hidden under
a box. If a value is genuinely ambiguous, answer "leaked" — under-reporting
a leak is the more dangerous error in a privacy audit.

Values to check:
{items}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["leaked", "redacted"]},
                    "note": {"type": "string"},
                },
                "required": ["value", "verdict", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def load_env(path: Path = Path(".env")) -> None:
    """Read KEY=value lines from .env without adding a dependency."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def media_type(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")


def score_image(client, model: str, image_path: Path, items: list[str]) -> dict:
    data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
    listed = "\n".join(f"- {v}" for v in items)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type(image_path),
                            "data": data,
                        },
                    },
                    {"type": "text", "text": PROMPT.format(items=listed)},
                ],
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Refused: {getattr(response, 'stop_details', None)}")

    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument(
        "--limit", type=int, default=None, help="Only score the first N images"
    )
    args = parser.parse_args()

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[red]ANTHROPIC_API_KEY is not set.[/red] Put it in .env as:\n"
            "  ANTHROPIC_API_KEY=sk-ant-..."
        )
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        console.print("[red]pip install anthropic[/red]")
        sys.exit(1)

    run_dir = Path(args.run_dir)
    images_dir = run_dir / "images"
    truth = json.loads(Path("ground_truth.json").read_text())
    client = anthropic.Anthropic()

    verdicts: dict[str, dict[str, str]] = {
        "_note": (
            f"Generated by vision_score.py using {args.model}. Each redacted "
            "output image was shown to the model alongside the values the "
            "ground truth says were on that page."
        )
    }
    totals = {"leaked": 0, "redacted": 0}

    names = [n for n in sorted(truth) if truth[n]["pii"] and (images_dir / n).exists()]
    if args.limit:
        names = names[: args.limit]

    for name in names:
        items = [p["text"] for p in truth[name]["pii"]]
        try:
            result = score_image(client, args.model, images_dir / name, items)
        except Exception as exc:
            console.print(f"[red]{name}: {exc}[/red]")
            continue

        page: dict[str, str] = {}
        for entry in result.get("verdicts", []):
            # Only trust verdicts for values we actually asked about.
            if entry["value"] in items:
                page[entry["value"]] = entry["verdict"]
                totals[entry["verdict"]] += 1
        verdicts[name] = page

        leaked = [v for v, k in page.items() if k == "leaked"]
        colour = "red" if leaked else "green"
        console.print(
            f"[{colour}]{name:34s} {len(leaked)} leaked of {len(page)}[/{colour}]"
            + (f"  {leaked}" if leaked else "")
        )

    out = run_dir / "vision_verdicts.json"
    out.write_text(json.dumps(verdicts, indent=2, ensure_ascii=False))
    console.print(
        f"\n[bold]{totals['redacted']} redacted, {totals['leaked']} leaked[/bold]"
    )
    console.print(f"[green]Written to[/green] {out}")
    console.print("Now re-run: [bold]python score_run.py " + str(run_dir) + "[/bold]")


if __name__ == "__main__":
    main()

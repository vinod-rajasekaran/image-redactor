"""Shared Claude vision helpers: .env loading, client, image encoding.

Both the output scorer and the input annotator need these; keeping one
copy stops them drifting apart on model choice or credential handling.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5"

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



def build_client():
    """Anthropic client, after loading .env. Raises with a usable message."""
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Put it in .env as:\n"
            "  ANTHROPIC_API_KEY=sk-ant-..."
        )
    import anthropic

    return anthropic.Anthropic()


def encode_image(path: Path) -> dict:
    """An image content block for the Messages API."""
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type(path),
            "data": base64.standard_b64encode(path.read_bytes()).decode("utf-8"),
        },
    }

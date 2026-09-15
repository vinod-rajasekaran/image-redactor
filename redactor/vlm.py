"""Vision-model PII detection against any OpenAI-compatible endpoint.

**Why this exists.** Most of this pipeline is a hand-rolled substitute for
reading a document: three preprocessing variants because OCR is fragile, a
reading-order re-sort because OCR flattens layout, label geometry because
forms pair labels with values, and recognizers because a regex cannot know
what a name is. A vision model does all four natively. The project's own
evidence points that way — `vision_score.py` uses one to *read* redacted
output and it has found leaks that both OCR and a careful manual pass
missed.

**Why it is not simply a replacement.** Redaction needs pixels, not
readings. Knowing the number is `8643 6694 9352` does not say what to
black out, and vision-generated boxes were measured on this project's own
corpus at **about a text row off** — which is why the per-region coverage
metric was built, measured and deleted. Newer document-grounded models
return boxes with the text, so this is worth re-testing, but it is a
hypothesis here and not an assumption.

So this is built as **another parallel path**, unioned with the OCR boxes
and the visual detectors exactly as the three preprocessing variants are.
The deterministic layer keeps what only it can offer: a Verhoeff checksum
on Aadhaar, IFSC's fixed `0`, and an auditable reason a box was drawn.

**Runtime-agnostic on purpose.** Ollama, LM Studio, vLLM and llama.cpp all
expose OpenAI-compatible chat completions, so pointing `--vlm-url` at a
different port is the whole switch. Uses stdlib HTTP rather than adding a
dependency for what is a local JSON POST.

    ollama serve && ollama pull qwen2.5vl:3b      # -> :11434/v1
    LM Studio -> Developer -> Start Server        # -> :1234/v1
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request

from .geometry import VisualRegion, clamp_box

DEFAULT_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5vl:3b"
DEFAULT_TIMEOUT = 180

# What the model is asked to find. Deliberately phrased as categories of
# *personal data*, not as this project's entity names: the point of using a
# vision model is that it does not need our taxonomy to recognise a name.
PROMPT = """This is a document image. Find every piece of personal data on \
the page that a privacy tool would need to cover.

Include: people's names (including signatures that spell a name), \
addresses, phone numbers, email addresses, dates of birth, and any \
identifying number — national ID, tax number, account, customer, policy, \
patient, case, licence, vehicle, registration.

Exclude anything that identifies no individual: the issuing organisation's \
own name, address, helpline or website; amounts of money; and bare dates \
that are not a date of birth.

For each item return a tight bounding box around **the value only**, not \
its printed label.

Answer with JSON only, no prose and no code fences:

{"items": [{"text": "the value as printed", "kind": "name|address|phone|\
email|dob|id_number|signature|other", "box": [x0, y0, x1, y1]}]}

Give box coordinates in **absolute pixels**, with [0,0] at the top-left. \
If you find nothing, return an empty items list."""

# Appended separately rather than interpolated into PROMPT: the prompt
# contains a literal JSON example, so `str.format` would trip over its
# braces.
SIZE_NOTE = "\n\nThis image is {width} pixels wide and {height} pixels tall."


def build_prompt(width: int, height: int) -> str:
    return PROMPT + SIZE_NOTE.format(width=width, height=height)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)

# `kind` -> the region label drawn in the output. Unknown kinds still get
# redacted; a vision model inventing a new category must not mean a missed
# box, which is the failure this project exists to prevent.
KIND_TO_LABEL = {
    "name": "vlm_name",
    "address": "vlm_address",
    "phone": "vlm_phone",
    "email": "vlm_email",
    "dob": "vlm_dob",
    "id_number": "vlm_id",
    "signature": "vlm_signature",
}


class VLMError(RuntimeError):
    """The endpoint was unreachable or answered with something unusable."""


def _post(url: str, payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise VLMError(f"{url} returned {exc.code}: {exc.read()[:300]!r}") from exc
    except urllib.error.URLError as exc:
        raise VLMError(
            f"Could not reach {url} ({exc.reason}). Start a server first:\n"
            "  ollama serve     (then: ollama pull qwen2.5vl:3b)\n"
            "  LM Studio -> Developer -> Start Server, then --vlm-url "
            "http://localhost:1234/v1"
        ) from exc


def available(base_url: str = DEFAULT_URL, timeout: int = 5) -> list[str]:
    """Model ids the endpoint can serve; empty if it is not reachable."""
    try:
        request = urllib.request.Request(f"{base_url.rstrip('/')}/models")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return sorted(m["id"] for m in json.loads(response.read()).get("data", []))
    except Exception:
        return []


def _encode(image) -> str:
    import io

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=90)
    return base64.b64encode(buffer.getvalue()).decode()


def _scale_factor(values: list[float], width: int, height: int) -> float:
    """Work out what coordinate convention the model answered in.

    Models disagree: some return fractions of the image, some per-mille
    (Qwen2-VL's 0-1000 convention), some absolute pixels. Guessing wrong
    puts every box in the wrong place, and a box in the wrong place is a
    leak that looks like a redaction. So infer it from the magnitudes
    rather than trusting the prompt to have been obeyed.

    The prompt now asks for absolute pixels and states the image size, so
    this is a safety net rather than the primary mechanism — but it is a
    needed one. Qwen2.5-VL was observed ignoring a request for fractions
    and answering in pixels; read as per-mille its box for a name came out
    clipped, covering x=64-502 where the name ran to 558. A box in the
    wrong place is a leak that looks like a redaction.

    **The residual ambiguity resolves to pixels.** Per-mille and pixels
    overlap whenever a coordinate fits inside the image, and there is no
    way to tell them apart from magnitudes alone. Pixels wins because that
    is what the prompt asks for and what grounded models return; per-mille
    is inferred only when a coordinate is too large to be a pixel. A model
    that answers in per-mille anyway will be mis-scaled — check a drawn
    output on a first run with an unfamiliar model.
    """
    biggest = max(values, default=0.0)
    if biggest <= 2.0:
        # Fractions. The bound is 2.0, not 1.0, because models overrun the
        # edge slightly and a box at 1.4 must stay fractional — read as
        # per-mille it collapses to nothing and the value is left visible.
        # Nothing legitimate is lost: a per-mille or pixel box whose largest
        # coordinate is under 2 has no area and is dropped regardless.
        return 1.0
    if biggest > max(width, height):
        # Cannot be pixels: it does not fit the image. Qwen2-VL's per-mille.
        return 1000.0
    return 0.0              # absolute pixels: caller uses them as-is


def parse_items(content: str, width: int, height: int) -> list[VisualRegion]:
    """Turn a model's JSON answer into regions in image pixel space."""
    cleaned = _FENCE.sub("", content).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Some models wrap the object in commentary despite being told not to.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise VLMError(f"No JSON in model reply: {content[:200]!r}")
        data = json.loads(match.group(0))

    items = data.get("items") or []
    coords = [c for item in items for c in (item.get("box") or [])
              if isinstance(c, (int, float))]
    divisor = _scale_factor(coords, width, height)

    regions: list[VisualRegion] = []
    for item in items:
        box = item.get("box") or []
        if len(box) != 4 or not all(isinstance(c, (int, float)) for c in box):
            continue
        if divisor:
            x0, y0, x1, y1 = (box[0] / divisor * width, box[1] / divisor * height,
                              box[2] / divisor * width, box[3] / divisor * height)
        else:
            x0, y0, x1, y1 = box
        # Models sometimes emit corners in the wrong order; normalise before
        # clamping so a reversed box is still a box.
        x0, y0, x1, y1 = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        left, top, box_width, box_height = clamp_box(
            int(x0), int(y0), int(x1 - x0), int(y1 - y0), (width, height)
        )
        if box_width <= 0 or box_height <= 0:
            continue
        kind = str(item.get("kind", "other")).lower()
        regions.append(
            VisualRegion(
                KIND_TO_LABEL.get(kind, "vlm_other"),
                left, top, box_width, box_height,
            )
        )
    return regions


def detect_pii_regions(
    image,
    base_url: str = DEFAULT_URL,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[VisualRegion]:
    """Ask a vision model where the personal data is on this page."""
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{_encode(image)}"
                        },
                    },
                    {"type": "text", "text": build_prompt(image.width, image.height)},
                ],
            }
        ],
        # Deterministic, so a benchmark run is repeatable.
        "temperature": 0,
        "max_tokens": 2048,
        "response_format": {"type": "json_object"},
    }
    body = _post(f"{base_url.rstrip('/')}/chat/completions", payload, timeout)
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise VLMError(f"Unexpected reply shape: {json.dumps(body)[:300]}") from exc
    return parse_items(content, image.width, image.height)

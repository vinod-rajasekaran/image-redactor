# Validation corpora

Every image this project validates against, with its annotations beside
it. One schema, one loader (`redactor/datasets.py`), so adding a corpus
does not mean editing every script.

## Everything here is synthetic

No real person, document, account or photograph appears in any corpus.
Every name, number and address was fabricated by a generator — one of
ours, one of the publishers', or an image model. That is stated per
corpus below and repeated in each `annotations.json` `_meta` block, which
is where a script reads it from.

| corpus | n | tracked | annotation | provenance | licence |
|---|---:|---|---|---|---|
| `documents/` | 20 | yes | text | 01–10 rendered by `generate_test_images.py`; 11–20 generated with an OpenAI image model, supplied as a collage and split | fully synthetic, freely redistributable — see [SOURCES.md](../SOURCES.md) |
| `holdout/` | 21 | yes | text | generated with an OpenAI image model, prompted by the repository owner | fully synthetic, freely redistributable — see [SOURCES.md](../SOURCES.md) |
| `ktp/` | 20 | no | box + text | [`cloverx-id/indonesian-id-card-dummy`](https://huggingface.co/datasets/cloverx-id/indonesian-id-card-dummy), publisher-declared dummy data | CC-BY-4.0 |
| `cheques/` | 10 | yes | box | [`jaganadhg/cheque-synthetic-images`](https://huggingface.co/datasets/jaganadhg/cheque-synthetic-images), publisher-declared synthetic | Apache-2.0 |
| `text/` | 2 files, 2.2MB | no | spans | IndiaPII-Bench; maskara-indian-pii-200k | CC-BY-4.0; MIT |

`text/` holds documents as **plain text with character-offset spans**, no
images. That is the point: fed straight to `AnalyzerEngine.analyze()`,
they isolate the recognizers from OCR, so a miss is a pattern gap and
nothing else. maskara adds an `ocr` domain of deliberately corrupted text
and `hard_negative` decoys, which is how the Aadhaar OCR-tolerance was
justified and how the PAN spacing gap was pinned on the pattern rather
than the reader.

## `holdout/` is held out, and the guard is not advisory

`holdout/` **may never be used to tune any OCR system** — not backend
selection, not PSM, not upscale factors, not preprocessing variants, not
thresholds. The line is between scoring and choosing: running it once with a
configuration decided elsewhere is the corpus's whole purpose, while sweeping
configurations over it and keeping the winner is forbidden.

That distinction is enforced rather than written down and hoped for.
`_meta` carries `held_out: true`, `redactor.datasets.refuse_if_tuning()`
raises `HeldOutCorpusError` for the corpus name or any path inside it,
`benchmark_ocr.py` calls it before the first configuration runs, and
`test_holdout_guard.py` pins both directions — that tuning is refused, and
that loading and scoring still work. The guard exists because the failure is
invisible: a sweep over a held-out corpus yields a number that looks exactly
like the measurement it used to be, and no diff shows that a test set
quietly became a training set.

**Holding it out does not make it independent evidence.** The repository
owner generated it, so it shares `documents/`'s standing — a ceiling on
familiar material. What it buys is a score no parameter here was fitted to,
which is narrower than independence and still worth having. Independent
evidence stays `cheques/`, IndiaPII-Bench and maskara.

Three things in it exist nowhere else here: a **Devanagari** name on an
image, where the label lexicon's Devanagari terms have never been exercised;
a **second checksum-invalid Aadhaar**, which only the OCR-tolerant fallback
can cover; and a page carrying **two different people**, which any
single-subject assumption gets wrong. Most of its pages are small — nine at about 471×363 and ten at about
277×547 — so character heights are low and the upscale-by-character-height
path carries most of the load. A low score on those pages may be measuring
resolution rather than detection.

`ktp/` is **Indonesian**, and is here because the label-to-value geometry
it validates is locale-independent while no Indian form corpus exists that
is both annotated and safe. It is a **cross-check only**: it must not set
thresholds, tolerances or defaults, however much larger it is than the
Indian corpora. Fetched by `ktp_benchmark.py`, not committed.

`datasets/.cache/` holds downloads that are not corpora — currently the
95MB parquet the cheque images unpack from. It used to sit in `text/`,
where 95MB of PNG bytes in a folder named for text corpora was both
misleading and the sole reason that folder was excluded from git. Deleting
anything in `.cache/` is always safe; the fetch step rebuilds it.

Images 11–20 *imitate* photographed pages — perspective, glare, low
contrast — and the notes elsewhere call them photographs for that reason.
That is rendered appearance, not a camera: they are the hardest images
here precisely because a generator was asked to make them look shot in
poor light.

## Size, and what stays out

Both image corpora are committed, so every image figure in `DECISIONS.md`
reproduces from a clone with no downloads. `documents/` costs 2.7MB and
`cheques/` 14MB for 10 images:

- the source PNGs are 2365×1065 with paper texture and ~138k unique
  colours, so PNG had almost nothing to remove — 4.4MB each, 44MB total
- the corpus was trimmed from 20 images to 10, keeping all four bank
  layouts (axis 3, canara 3, icici 2, syndicate 2)
- then stored as **JPEG q95, no chroma subsampling**: 44MB → 14MB. This
  changes pixels, so the coverage figures were **re-measured** on the
  JPEGs rather than carried over — and they moved. See DECISIONS.md.

**The exclusions are third-party data this project did not generate**:
`text/` (2.2MB, fetched by `benchmark_indiapii.py` and `benchmark_maskara.py`
per their docstrings) and `datasets/.cache/`. Both are one command to
restore, and neither is re-derived from anything here.

Redistributing the cheques is fine under Apache-2.0; the licence and the
upstream URL are recorded in `cheques/annotations.json` under `_meta`.

## Why two annotation kinds

`text` supports **legibility** scoring — is the PII still readable — which
is the headline metric, because a box 85% covered can still leak.

`box` supports **coverage** — how much of the region was painted over.
Weaker, but deterministic and free of any model call. It is only
trustworthy where the boxes are: computed at render time, or authored by
a person. Coverage from *vision-generated* boxes was built and removed,
because those were off by about a text row.

A corpus that knows both should record both.

## Schema

```json
{
  "_meta":  { "description": ..., "licence": ..., "source": ... },
  "<image file>": {
    "pii": [
      { "field": ..., "expected_type": ..., "tier": "core" | "sensitive",
        "text": "...", "box": [x0, y0, x1, y1] }
    ],
    "visual": { "face": 0, "qr_code": 0, "barcode": 0 },
    "notes": "..."
  }
}
```

`text` and `box` are each optional; at least one is always present.
`expected_type` is `null` where no Presidio recognizer covers the field.

## Adding a corpus

Add a row to [`SOURCES.md`](../SOURCES.md) first — licence as checked,
link, and what it lets you measure. Then write `_meta` with a `source` and
a `licence` before anything else. A
corpus whose provenance cannot be stated in one line does not belong
here, and one that is not synthetic does not belong here at all — real
document images are exactly what this tool exists to protect, and its
test set is a poor place to keep them.

# Validation corpora

Every image this project validates against, with its annotations beside
it. One schema, one loader (`redactor/datasets.py`), so adding a corpus
does not mean editing every script.

| corpus | n | annotation | licence / provenance |
|---|---:|---|---|
| `documents/` | 20 | text | 10 synthetic documents generated here + 10 photographs, hand-labelled. **May contain real PII.** |
| `cheques/` | 20 | box | [`jaganadhg/cheque-synthetic-images`](https://huggingface.co/datasets/jaganadhg/cheque-synthetic-images) — Apache-2.0, fully synthetic |
| `pack/` | 20 | box | `generate_synthetic_indian_pii_images.py` — fully synthetic, 8 document types |
| `text/` | 3 files | spans | Text-only benchmarks: IndiaPII-Bench (CC-BY-4.0), maskara-indian-pii-200k (MIT), the cheque parquet |

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

## Nothing here is committed

The images and annotations are gitignored. `documents/` holds real
photographs, and annotation files describe exactly where the PII is —
publishing either would defeat the point of the project. Regenerate with
`generate_test_images.py`, `cheque_benchmark.py` and the pack generator.

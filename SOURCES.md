# Sources: every dataset and model, its licence, and why it is here

One row per dataset or model this project uses, produced, considered or
rejected — with the licence **as actually checked**, a link to where it was
checked, and what the thing is *for*. A dataset with no stated purpose does not
belong in a benchmark, and a licence nobody verified is a guess.

**How to read the "verified" column.** Not all checks are equal, so each
row says how its licence was established:

| marker | meaning |
|---|---|
| **API** | queried programmatically (HuggingFace API, Python package metadata). Strongest. |
| **page** | read from the project's own repository or dataset page |
| **search** | seen only in a search result or secondary source — treat as provisional |
| **unstated** | the source publishes no licence. Not the same as permissive. |
| **self** | produced by this project, so the provenance is known first-hand rather than checked |

**This repository's own licence is [MIT](LICENSE)**, which is what "carries
this repository's licence" means in the rows below.

**Licence policy, two tiers.** MIT/Apache is required for anything
**committed to this repository**, because committing is redistribution.
Non-commercial terms (CC BY-NC-SA, research-and-education licences) are
acceptable for corpora **fetched and used locally and never committed** —
the treatment `datasets/text/` already gets.

---

## Datasets in use

| dataset | licence | verified | purpose |
|---|---|---|---|
| [jaganadhg/cheque-synthetic-images](https://huggingface.co/datasets/jaganadhg/cheque-synthetic-images) | Apache-2.0 | **API** | **The only independent image corpus this project has.** 295 synthetic Indian cheques with bounding boxes drawn by the publishers, so region coverage means something here and nowhere else. Also the hardest case we can measure: handwriting throughout. 10 images committed; the rest fetched on demand. |
| [maskflow-ai/indiapii-bench](https://huggingface.co/datasets/maskflow-ai/indiapii-bench) | CC-BY-4.0 | **API** | Recognizer recall on 2,000 independent Indian documents, with no OCR in the path — so a miss is provably a pattern gap. Also the **only independent test of the label lexicon**: every document is `Label: Value` form text, giving 9,782 labelled values. Carries PII-shaped decoys for false-positive measurement. |
| [somukandula/maskara-indian-pii-200k](https://huggingface.co/datasets/somukandula/maskara-indian-pii-200k) | MIT | **API** | A second, independent recognizer benchmark, deliberately not the same author as IndiaPII. Adds an **`ocr` domain of deliberately corrupted text** — the exact failure the Aadhaar fallback exists for — and hard negatives. Its disagreement with IndiaPII about driving-licence formats is itself a finding. |

---

## Produced by this project

Listed here for the same reason as everything else: provenance rots when
it is not written down, and this project has already had to correct a
claim that one of these corpora contained real photographs when it did
not.

| corpus | licence / terms | verified | purpose |
|---|---|---|---|
| `datasets/documents/` images **01–10** | fully synthetic; [MIT](LICENSE) | **self** | Ten Pillow-rendered Indian documents — Aadhaar, PAN, prescription, passbook, licence, voter ID, insurance, rental. Flat, crisp, no perspective: the easy end of the range, and the regression canary for the OCR-tolerant Aadhaar fallback lives here (`04_hospital_admission_report.png` carries a deliberately checksum-invalid number). |
| `datasets/documents/` images **11–20** | **OpenAI assigns output rights to the user**, "to the extent permitted by applicable law" — see [Terms of Use](https://openai.com/policies/row-terms-of-use/) | **self** + **page** (terms) | Ten pages generated with an OpenAI image model, supplied as a collage and split. They *imitate* photographed documents — perspective, glare, low contrast — which makes them the hardest images in the corpus and the source of most known leaks. Every value on them is fabricated. |

**Both halves are fully synthetic**: no real person, document, account or
photograph. Together they are the 77-item ground truth behind the 93.5%
headline — which `VALIDATION.md` states as a **ceiling on familiar
material**, because this project drew the documents and then wrote the
recognizers while looking at them.

### Redistribution: all of it can be open-sourced

Three different things with three different statuses, and none of them
blocks distribution:

| part | status | effect |
|---|---|---|
| images 01–10 | authored here, by code in this repository | copyrightable, carries this repository's licence |
| images 11–20, raw output | OpenAI assigns its rights to the user; purely AI-generated output generally **cannot be copyrighted**, since US and international law require human authorship | nobody holds an exclusive right, so nothing restricts redistribution — and equally, we cannot impose terms on the raw output |
| the annotations, the curation, the collage split | human-authored work | copyrightable, carries this repository's licence |

The practical position: **the corpus is freely usable.** What we authored
we license; over the raw model output we assert no copyright, which is a
statement about our rights, not a restriction on yours. Anyone generating
a similar image independently is free to use theirs.

**One caveat that survives all of that**, and it is not about copyright:
these reproduce official Indian document *layouts* — emblem, banding,
seal. They are mockups for testing a privacy tool. Every value on them is
fabricated, and nothing here is or should be presented as an issued
record.

### Deleted, and why

| corpus | why it is gone |
|---|---|
| `datasets/pack/` | Synthetic Indian documents generated here from a locally-run generator. Deleted 2026-09-15: the recognizers and the test data had the same author, so its 90% measured agreement with our own inventions. |
| `datasets/generated/` | 50 photoreal pages from `gpt-image-2`, 224 ground-truth items, 79.0%. Deleted the same day and for the same reason, along with the generator, so no later session could reach for it. |

The findings they produced survive in `DECISIONS.md`; the corpora and the
machinery do not.

---

## Datasets that are candidates, not yet used

| dataset | licence | verified | purpose |
|---|---|---|---|
| [cloverx-id/indonesian-id-card-dummy](https://huggingface.co/datasets/cloverx-id/indonesian-id-card-dummy) — **now in use**, see `ktp_benchmark.py` | **CC-BY-4.0** | **API** | **The only real-page evidence the label-anchored geometry has.** 24,000 synthetic Indonesian national ID cards plus 109,000 augmented, explicitly dummy data with no real people, and **per-field bounding boxes carried with the text** (`{"text": "...", "bounding_box": [145,11,565,36]}`). Its fields map almost one-to-one onto an Aadhaar card — `nik` (national ID number), `nama`, `tempat_tanggal_lahir` (DOB), `alamat` (address) — so it tests label→value geometry on ID-card layouts, and the augmented subset supplies the degraded captures that break our OCR path. Not Indian and not Devanagari, which is the right division of labour: the lexicon is already measured on Indian text. |
| [naver-clova-ix/cord-v2](https://huggingface.co/datasets/naver-clova-ix/cord-v2) | CC-BY-4.0 | **API** | Receipts with key-value field annotations. A second, differently-shaped test of label→value pairing — dense, small type, many fields per page. |
| [DocILE](https://github.com/rossumai/docile) | code MIT; **dataset gated** behind a request form | **page** | 6.7k annotated business documents, 100k synthetic, **55 field classes with localization** — the largest key-information-localization benchmark there is. Blocked on the access form rather than on terms. |
| [FUNSD](https://guillaumejaume.github.io/FUNSD/) | non-commercial, research and educational | **search** | **The best available test of the one thing that is unvalidated.** 199 real scanned forms whose annotation *is* human-decided label→value linking — a person chose which value belongs to which label, which is exactly what `redactor/labels.py` computes. English and American, so it tests the mechanism while the lexicon is measured on Indian data. Local use only. |
| [MIDV-500](ftp://smartengines.com/midv-500/) ([paper](https://arxiv.org/abs/1807.05786)) | source images from Wikimedia Commons, public domain or open licences | **page** | 50 identity-document types with field annotations, no gate and no form. Adds ID-card layouts the cheques cannot, plus **Cyrillic, Greek and Chinese fields** — the first real test of non-Latin labels, which the Devanagari terms in our lexicon currently lack. |
| [DocXPand-25k](https://github.com/QuickSign/docxpand) | dataset **CC BY-NC-SA 4.0**; code MIT | **page** | 24,994 synthetic ID images across 9 fictitious designs with rich per-field labels and artificially generated faces — scale for the geometry half, with no real personal data anywhere in it. Local use only. |
| [MIDV-2020](https://l3i-share.univ-lr.fr/MIDV2020/midv2020.html) ([paper](https://arxiv.org/abs/2107.00396)) | **undisclosed** — behind an acceptance form | **unstated** | 72,409 annotated images of 1,000 mock IDs, with 546 text fields, 48 photo fields and 40 signature fields carrying **both ideal values and positions**. Structurally ideal; blocked on 124GB and unknown terms. |
| [XFUND](https://github.com/doc-analysis/XFUND) | CC BY-NC-SA 4.0 | **search** | Human key-value form annotations across 7 languages. Same role as FUNSD, multilingual. No Indic languages. |
| [BID](https://github.com/ricardobnjunior/Brazilian-Identity-Document-Dataset) | **unstated** in the repository | **unstated** | 28,800 synthetic Brazilian ID images from 8 templates, with text-region and OCR annotations. Worth one email to the authors — unstated is not the same as restrictive. |

---

## Rejected on ethics, not licence

**These do not become usable under a permissive licence.** They are real
people's documents, held by people who did not consent to appearing in an
ML benchmark, and they are the exact category this tool exists to protect.

| dataset | what it is | why rejected |
|---|---|---|
| FIR dataset ([TransDocAnalyser](https://arxiv.org/abs/2306.02142)) | **Real** First Information Reports collected from Indian police stations, printed forms filled in by hand | Real complainants, addresses and case details, with no anonymisation described. FIRs carry crime-report data about victims and accused persons. It is the closest match to what this tool protects, and that is precisely the objection. |
| Kaggle / Roboflow Aadhaar collections ([example](https://universe.roboflow.com/cutm-iwh4a/aadhaar-card-details)) | Field-annotated **real Aadhaar cards** | Real national identity numbers belonging to identifiable people. One such set was already rejected in this project on the same grounds. |

---

## Rejected as unsuitable

| candidate | licence | verified | why not |
|---|---|---|---|
| [IndicDLP](https://huggingface.co/datasets/ai4bharat/indicdlp) | MIT | **page** | 121k real Indian pages, and genuinely MIT — but 11 of its 12 domains carry no field-level PII, publicly scrapeable forms are blank templates with no values to redact, and it annotates layout boxes with no text. The right licence attached to the wrong content. |
| [LeakageBench](https://arxiv.org/abs/2609.02207) | Data Use Agreement | **page** | 500 document images with 11,954 PII annotations — the right shape, but gated behind a DUA, GDPR/European rather than Indian, and days old. |
| [nvisycom/synthetic](https://github.com/nvisycom/synthetic) | MIT | **page** | Purpose-built for benchmarking redaction, which is exactly our problem — but "only text-bearing formats render"; images are unimplemented. We already have two text benchmarks. |
| [microsoft/presidio-research](https://github.com/microsoft/presidio-research) | MIT | **page** | A template-and-Faker **generator**, not a corpus. Using it would repeat the mistake that cost this project two deleted corpora: grading homework against its own answer key. Worth recording that **Presidio ships no test data**, so its India recognizers have no independent evidence except ours. |
| [DocLayNet](https://huggingface.co/datasets/ds4sd/DocLayNet) | CDLA-Permissive-1.0 | **search** | 80,863 real pages with layout annotations, permissively licensed — but no PII and no Indian content. |

---

## Models and libraries

| component | licence | verified | purpose |
|---|---|---|---|
| [presidio-analyzer](https://github.com/microsoft/presidio) 2.2.364 | MIT | **API** | The PII detection engine this project evaluates. |
| presidio-image-redactor 0.0.60 | MIT | **API** | OCR-to-analyzer plumbing and the `OCR` interface the backends adapt to. |
| [spaCy](https://spacy.io) 3.8.16 + `en_core_web_lg` | MIT | **API** | Named-entity recognition for people and places — the layer that finds names, and the one that fails most on photographed pages. |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) via pytesseract 0.3.13 | Apache-2.0 | **API** | Default OCR backend. Chosen on latency, not accuracy. |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) 3.7.0 | Apache-2.0 | **API** | Stronger OCR backend, ~17× slower. Carries two landmines documented in `CLAUDE.md`. |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) 1.4.4 | Apache-2.0 | **API** | Evaluated and rejected — dominated on both accuracy and speed. |
| [OpenCV](https://opencv.org) 4.14 | Apache-2.0 | **API** | QR and barcode detection, image preprocessing, signature component analysis. |
| [YuNet face detector](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | MIT (model directory); opencv_zoo overall Apache-2.0 | **search** | Face detection on ID documents. Replaced Haar cascades. |
| [WeChat QR models](https://github.com/WeChatCV/opencv_3rdparty) | **unverified** | **unstated** | Optional QR detector, off by default. Evaluated and **rejected on merit** — found 0 codes where OpenCV found 4, because it is decode-gated. Licence never needed resolving since it is not used. |
| [blaze999/Medical-NER](https://huggingface.co/blaze999/Medical-NER) | MIT | **API** | Optional `--medical-ner`: diagnoses and medications. Off by default; pulls in torch. |
| [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python) 1.5.0 | MIT | **API** | Vision scoring and ground-truth auditing. The only network call this project makes, and never for redaction. |
| **ultralytics / YOLO** | **AGPL-3.0** | **page** | **Rejected.** A YOLO document-layout model was tested for unioning with OCR boxes. AGPL-3.0 would have been the only copyleft dependency here and would attach to anything deploying the tool as a service — and it generalised poorly besides. |

---

## Maintaining this file

- Add a row **before** using a source, not after.
- Record the licence *and how it was checked*. "The README says MIT" and
  "the API reports MIT" are different claims.
- State the purpose in terms of what it lets us **measure**. If that
  cannot be written down, the dataset is not needed.
- A rejection is as valuable as an adoption — it stops the next session
  re-litigating it. Keep rejected rows, with the reason.
- **Ethics rejections never expire.** A real-document corpus does not
  become acceptable because a licence changes or a deadline is close.

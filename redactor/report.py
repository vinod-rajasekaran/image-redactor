"""Per-run HTML report, and the committed history behind its trend.

Two jobs, kept together because they share one shape — the `score.json`
that `score_run.py` already writes:

- **record** one line per scored run in `benchmarks/history.jsonl`, which is
  committed, so a trend reproduces from a clone the way `documents/` and
  `cheques/` figures do.
- **render** a self-contained page into the run folder and open it, so the
  result of a change is visible without reading a table in a terminal.

**Held-out corpora are tracked, and marked every place they appear.** The
alternative — leaving them out of the series — was considered and rejected
for a specific reason: a corpus with no visible history invites being scored
quietly, and an unrecorded score is exactly the one nobody can audit later.
Recording it puts every scoring on the record.

That record is the defence, because the guard cannot be. `refuse_if_tuning()`
stops a sweep; it cannot stop a person reading a trend line and keeping the
changes that move it up, which is hill-climbing on the test set at human
speed. So a held-out corpus's page carries a banner, its trend is drawn in
the warning colour rather than the accent, and it shows **how many times the
corpus has been scored** and **whether this commit has scored it before**. A
rising count is the signal that the corpus is being used as a target.

Every entry carries the **git SHA and whether the tree was dirty**. A
performance history that cannot say which code produced a number is how a
headline gets corrected six times.
"""
from __future__ import annotations

import html
import json
import subprocess
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "benchmarks" / "history.jsonl"

# Fields worth carrying from score.json's config block. A trend is unreadable
# without knowing what produced each point, and the whole config is noise.
CONFIG_KEYS = (
    "ocr_backend", "psm", "medical_ner", "reading_order",
    "protect_clinical", "threshold", "upscale", "vlm",
)


def git_state() -> dict:
    """The commit a number was produced at, and whether the tree was clean."""
    def run(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    sha = run("rev-parse", "--short", "HEAD")
    return {
        "sha": sha or "unknown",
        "dirty": bool(run("status", "--porcelain")),
        "subject": run("log", "-1", "--format=%s")[:90],
    }


def entry_for(score: dict, corpus_name: str) -> dict:
    cfg = score.get("config", {})
    totals = score.get("totals", {})
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run": score.get("run_name", ""),
        "corpus": corpus_name,
        "recall_floor_pct": score.get("recall_floor_pct"),
        "recall_ceiling_pct": score.get("recall_ceiling_pct"),
        "totals": {k: totals.get(k, 0) for k in ("redacted", "leaked", "unverifiable")},
        "by_tier": {
            tier: {k: v.get(k, 0) for k in ("redacted", "leaked", "unverifiable")}
            for tier, v in score.get("by_tier", {}).items()
        },
        "image_count": cfg.get("image_count"),
        "config": {k: cfg[k] for k in CONFIG_KEYS if k in cfg},
        "git": git_state(),
    }


def record(score: dict, corpus_name: str, *, held_out: bool) -> dict:
    """Append one run to the committed history, held-out corpora included.

    The `held_out` flag travels with the entry so every later reader — the
    report, a person, a future script — can tell a confirmation from a
    target without having to look the corpus up.
    """
    entry = entry_for(score, corpus_name)
    entry["held_out"] = held_out
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def history_for(corpus_name: str) -> list[dict]:
    if not HISTORY.exists():
        return []
    out = []
    for line in HISTORY.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("corpus") == corpus_name and row.get("recall_floor_pct") is not None:
            out.append(row)
    return out


# --- rendering ---------------------------------------------------------------

def _sparkline(
    points: list[float], width: int = 620, height: int = 120, *, held_out: bool = False
) -> str:
    """A trend line labelled with values it actually reaches.

    Deliberately plain: one scale, the real min and max on the axis, and a
    marked endpoint. A chart that flatters a change is worse than a table.
    """
    if len(points) < 2:
        return ""
    lo, hi = min(points), max(points)
    span = max(hi - lo, 1.0)
    pad_l, pad_r, pad_t, pad_b = 46, 12, 14, 24
    w = width - pad_l - pad_r
    h = height - pad_t - pad_b
    step = w / (len(points) - 1)

    def xy(i: int, v: float) -> tuple[float, float]:
        return pad_l + i * step, pad_t + h - ((v - lo) / span) * h

    # A held-out corpus is drawn in the warning colour, so its trend never
    # reads as the thing to push up.
    stroke = "var(--held)" if held_out else "var(--covered)"
    fill = "var(--sensitive-bg)" if held_out else "var(--covered-bg)"
    caption = "confirmations" if held_out else "runs"
    pts = [xy(i, v) for i, v in enumerate(points)]
    path = " ".join(
        ("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts)
    )
    area = path + f" L{pts[-1][0]:.1f},{pad_t + h:.1f} L{pts[0][0]:.1f},{pad_t + h:.1f} Z"
    ex, ey = pts[-1]
    return f"""<svg viewBox="0 0 {width} {height}" role="img"
   aria-label="Recall floor across {len(points)} scored runs, {lo:.1f}% to {hi:.1f}%">
  <line x1="{pad_l}" y1="{pad_t + h}" x2="{width - pad_r}" y2="{pad_t + h}"
        stroke="var(--rule)" stroke-width="1"/>
  <text x="{pad_l - 8}" y="{pad_t + 5}" text-anchor="end" class="tick">{hi:.1f}%</text>
  <text x="{pad_l - 8}" y="{pad_t + h + 4}" text-anchor="end" class="tick">{lo:.1f}%</text>
  <path d="{area}" fill="{fill}" stroke="none"/>
  <path d="{path}" fill="none" stroke="{stroke}" stroke-width="2"
        stroke-linejoin="round" stroke-linecap="round"/>
  <circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="{stroke}"/>
  <text x="{width - pad_r}" y="{height - 6}" text-anchor="end" class="tick">this run</text>
  <text x="{pad_l}" y="{height - 6}" class="tick">{len(points)} {caption}</text>
</svg>"""


def failures(corpus, run_dir: Path) -> list[dict]:
    """Every item still legible, with the page it is on.

    Two shapes, because the corpora are annotated two ways and the report has
    to serve both:

    - **text annotations** (`documents/`, `holdout/`) give per-item verdicts
      from `vision_verdicts.json`, so a failure names the value that leaked.
    - **box-only annotations** (`cheques/`) have no ground-truth text, so
      legibility is asked per *element* and lands in `legibility.json`. A
      failure there names the element, not the value.

    Returns [] rather than raising when neither file is present: a report
    that cannot list failures is still worth writing.
    """
    run_dir = Path(run_dir)
    pages: list[dict] = []

    verdict_path = run_dir / "vision_verdicts.json"
    legibility_path = run_dir / "legibility.json"

    def shot(name: str) -> str | None:
        """Prefer the annotated image — it shows where the leak is."""
        for rel in (f"scored/{name}", f"images/{name}"):
            if (run_dir / rel).exists():
                return rel
        return None

    if verdict_path.exists() and corpus is not None:
        try:
            verdicts = json.loads(verdict_path.read_text())
        except (OSError, json.JSONDecodeError):
            verdicts = {}
        verdicts.pop("_note", None)
        for name in sorted(corpus.annotations):
            items = corpus.pii(name)
            if not items:
                continue
            seen = verdicts.get(name, {})
            leaked = [p for p in items if seen.get(p.get("text")) == "leaked"]
            if not leaked:
                continue
            pages.append({
                "image": name,
                "shot": shot(name),
                "total": len(items),
                "leaks": [{
                    "field": p.get("field", ""),
                    "text": p.get("text", ""),
                    "type": p.get("expected_type"),
                    "tier": p.get("tier", "core"),
                    "note": p.get("note", ""),
                } for p in leaked],
            })
        return pages

    if legibility_path.exists():
        try:
            data = json.loads(legibility_path.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        for name, d in sorted(data.get("by_image", {}).items()):
            if not d.get("leaked"):
                continue
            pages.append({
                "image": name,
                "shot": shot(name),
                "total": len(d.get("leaked", [])) + len(d.get("covered", [])),
                "leaks": [{
                    "field": element,
                    "text": "still readable after redaction",
                    "type": None,
                    "tier": "core",
                    "note": "",
                } for element in d["leaked"]],
            })
    return pages


def _failure_section(pages: list[dict]) -> str:
    if not pages:
        return (
            "<h2>Failures</h2><p class='note'>Nothing leaked, or this run has "
            "no vision verdicts yet. Run <code>vision_score.py</code> (or "
            "<code>cheque_benchmark.py --legibility</code>) and score again — "
            "the OCR scorer is blind exactly where redaction fails.</p>"
        )
    total = sum(len(p["leaks"]) for p in pages)
    cards = []
    for p in pages:
        leaks = "".join(
            f"<div class='leak' data-tier=\"{html.escape(l['tier'])}\" "
            f"data-rec=\"{'1' if l['type'] else '0'}\">"
            f"<div class='field'>{html.escape(l['field'])}</div>"
            f"<div class='value'>{html.escape(l['text'])}</div>"
            f"<div class='meta'>"
            f"<span class='tag{'' if l['type'] else ' none'}'>"
            f"{html.escape(l['type'] or 'no recognizer')}</span>"
            f"<span class='tag{' sens' if l['tier'] == 'sensitive' else ''}'>"
            f"{html.escape(l['tier'])}</span></div>"
            + (f"<p class='note'>{html.escape(l['note'])}</p>" if l["note"] else "")
            + "</div>"
            for l in p["leaks"]
        )
        shot = (
            f"<div class='shot'><img src='{html.escape(p['shot'])}' loading='lazy' "
            f"alt='Redacted output for {html.escape(p['image'])}'>"
            f"<a href='{html.escape(p['shot'])}' target='_blank' rel='noopener'>"
            f"Open full size &rarr;</a></div>"
            if p["shot"] else
            "<div class='shot'><p class='dim'>No image in this run folder</p></div>"
        )
        cards.append(
            f"<section class='page'><div class='page-head'>"
            f"<span class='page-name'>{html.escape(p['image'])}</span>"
            f"<span class='page-stat'>{len(p['leaks'])} of {p['total']} leaked</span>"
            f"</div><div class='body'>{shot}<div class='leaks'>{leaks}</div></div></section>"
        )
    return (
        f"<h2>Failures — {total} item{'' if total == 1 else 's'} still legible</h2>"
        "<div class='controls'>"
        "<button data-f='all' aria-pressed='true'>All</button>"
        "<button data-f='sens' aria-pressed='false'>Sensitive tier</button>"
        "<button data-f='norec' aria-pressed='false'>No recognizer</button>"
        "<span class='spacer'></span><span class='count' id='shown'></span></div>"
        + "".join(cards)
    )


def _rows(score: dict) -> str:
    out = []
    for title, block in (("By tier", score.get("by_tier", {})),
                         ("By expected type", score.get("by_type", {}))):
        if not block:
            continue
        body = "".join(
            f"<tr><td>{html.escape(str(k))}</td>"
            f"<td class='n ok'>{v.get('redacted', 0)}</td>"
            f"<td class='n bad'>{v.get('leaked', 0)}</td>"
            f"<td class='n dim'>{v.get('unverifiable', 0)}</td></tr>"
            for k, v in sorted(block.items(), key=lambda kv: -kv[1].get("leaked", 0))
        )
        out.append(
            f"<h2>{title}</h2><div class='scroll'><table>"
            f"<thead><tr><th></th><th class='n'>redacted</th>"
            f"<th class='n'>leaked</th><th class='n'>unverifiable</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>"
        )
    return "".join(out)


def _held_out_banner(hist: list[dict], sha: str) -> str:
    """The count, and whether this commit has already scored this corpus."""
    times = len(hist)
    same_sha = sum(1 for h in hist if h.get("git", {}).get("sha") == sha)
    repeat = ""
    if same_sha > 1:
        repeat = (
            f" <b class='bad'>Commit <code>{html.escape(sha)}</code> has now "
            f"scored it {same_sha} times.</b> Re-scoring one commit is how a "
            f"result gets chased until it reads the way you wanted."
        )
    return (
        f"<div class='callout held'><h2>Held out — a confirmation, not a "
        f"target</h2><p>Scored <b>{times}</b> time{'' if times == 1 else 's'} in "
        f"all.{repeat} No backend, threshold, upscale factor or preprocessing "
        f"choice may be made from this number. Decide with <code>cheques/</code>, "
        f"IndiaPII-Bench or maskara, then come back here once to see what "
        f"happened. A rising count means this corpus is being used as a "
        f"target.</p></div>"
    )


def _delta_line(hist: list[dict]) -> str:
    if len(hist) < 2:
        return "<p class='note'>First scored run for this corpus — no trend yet.</p>"
    prev, cur = hist[-2], hist[-1]
    d = (cur["recall_floor_pct"] or 0) - (prev["recall_floor_pct"] or 0)
    word = "unchanged from" if abs(d) < 0.05 else (
        f"{'up' if d > 0 else 'down'} {abs(d):.1f} points from")
    g = prev.get("git", {})
    return (
        f"<p class='note'>Recall floor {word} the previous run "
        f"(<code>{html.escape(str(g.get('sha', '?')))}</code>, "
        f"{html.escape(str(prev.get('at', ''))[:10])}). A comparison only means "
        f"something if both runs used the same corpus the same way — check the "
        f"config on each below.</p>"
    )


STYLE = """
:root{
  --ground:#eef1f4;--surface:#fff;--surface-2:#f6f8fa;
  --ink:#131a21;--ink-2:#48565f;--ink-3:#77878f;--rule:#d5dde3;--rule-2:#e6ecf0;
  --covered:#1f6b63;--covered-bg:#e2efec;
  --leaked:#b03428;--leaked-bg:#fbe8e5;
  --sensitive:#8a5512;--sensitive-bg:#f8ecdc;--held:#8a5512;
  --shadow:0 1px 2px rgba(19,26,33,.06),0 8px 24px -16px rgba(19,26,33,.28);
}
@media (prefers-color-scheme:dark){:root{
  --ground:#0e1319;--surface:#161d25;--surface-2:#1b232c;
  --ink:#e6edf2;--ink-2:#a3b1bc;--ink-3:#71818d;--rule:#2a343e;--rule-2:#222b34;
  --covered:#5fc4b4;--covered-bg:#12312d;
  --leaked:#f08b7d;--leaked-bg:#3a1c18;
  --sensitive:#e0a458;--sensitive-bg:#352612;--held:#e0a458;
  --shadow:0 1px 2px rgba(0,0,0,.5),0 10px 28px -18px rgba(0,0,0,.9);
}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:Archivo,"Helvetica Neue",Helvetica,Arial,sans-serif;font-size:15px;line-height:1.55}
.wrap{max-width:1080px;margin:0 auto;padding-inline:20px;padding-block:40px 72px}
h1,h2{margin:0;text-wrap:balance}
h1{font-size:clamp(26px,4vw,36px);font-weight:700;letter-spacing:-.02em;margin-top:8px}
h2{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3);
   font-weight:600;margin:34px 0 10px}
.eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3);font-weight:600}
.tiles{display:grid;grid-template-columns:2fr 1fr 1fr;gap:14px;margin-top:26px}
@media(max-width:780px){.tiles{grid-template-columns:1fr}}
.tile{background:var(--surface);border:1px solid var(--rule);border-radius:10px;
  padding:18px 20px;box-shadow:var(--shadow)}
.tile h3{margin:0;font-size:11px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-3);font-weight:600}
.pct{font-size:40px;font-weight:700;letter-spacing:-.03em;line-height:1.1;margin-top:6px;
  font-variant-numeric:tabular-nums}
.tile p{margin:6px 0 0;font-size:13px;color:var(--ink-2)}
.meter{height:5px;border-radius:3px;background:var(--rule-2);margin-top:12px;display:flex;overflow:hidden}
.meter i{display:block;height:100%}.meter .ok{background:var(--covered)}.meter .bad{background:var(--leaked)}
.mono,code{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
.callout{margin-top:22px;background:var(--surface);border:1px solid var(--rule);
  border-left:3px solid var(--covered);border-radius:8px;padding:18px 22px}
.callout.held{border-left-color:var(--held)}
.callout h2{font-size:15px;font-weight:700;letter-spacing:0;text-transform:none;color:var(--ink);margin:0}
.callout p{margin:8px 0 0;color:var(--ink-2);font-size:14px;max-width:72ch}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:6px}
button{font:inherit;font-size:13px;font-weight:500;color:var(--ink-2);background:var(--surface);
  border:1px solid var(--rule);border-radius:999px;padding:6px 14px;cursor:pointer}
button:hover{border-color:var(--ink-3);color:var(--ink)}
button[aria-pressed="true"]{background:var(--ink);color:var(--ground);border-color:var(--ink)}
button:focus-visible{outline:2px solid var(--covered);outline-offset:2px}
.spacer{flex:1}.count{font-size:13px;color:var(--ink-3);font-variant-numeric:tabular-nums}
.page{margin-top:16px;background:var(--surface);border:1px solid var(--rule);
  border-radius:10px;overflow:hidden}
.page-head{padding:14px 20px;border-bottom:1px solid var(--rule-2);display:flex;
  flex-wrap:wrap;gap:6px 12px;align-items:baseline}
.page-name{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:13.5px;font-weight:600}
.page-stat{font-size:12px;color:var(--ink-3);font-variant-numeric:tabular-nums;margin-left:auto}
.body{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr)}
@media(max-width:760px){.body{grid-template-columns:1fr}}
.shot{border-right:1px solid var(--rule-2);background:var(--surface-2);padding:14px;
  display:flex;flex-direction:column;gap:8px}
@media(max-width:760px){.shot{border-right:0;border-bottom:1px solid var(--rule-2)}}
.shot img{width:100%;height:auto;display:block;border:1px solid var(--rule);
  border-radius:6px;background:#fff}
.shot a{font-size:12px;color:var(--ink-2);text-decoration:none;border-bottom:1px solid var(--rule)}
.shot a:hover{color:var(--ink)}
.leak{padding:12px 18px;border-top:1px solid var(--rule-2)}
.leak:first-child{border-top:0}
.field{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);font-weight:600}
.value{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:14.5px;margin-top:3px;
  color:var(--leaked);font-weight:500;word-break:break-word}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}
.tag{font-size:11px;padding:2px 8px;border-radius:4px;background:var(--surface-2);
  color:var(--ink-2);border:1px solid var(--rule-2);
  font-family:"IBM Plex Mono",ui-monospace,monospace}
.tag.sens{color:var(--sensitive);background:var(--sensitive-bg);border-color:transparent;font-weight:600}
.tag.none{font-style:italic}
.note{margin-top:8px;font-size:13px;color:var(--ink-2);border-left:2px solid var(--rule);
  padding-left:11px;max-width:72ch}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:7px 10px;border-top:1px solid var(--rule-2)}
thead th{border-top:0;font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-3)}
.n{text-align:right;font-variant-numeric:tabular-nums}
.ok{color:var(--covered)}.bad{color:var(--leaked);font-weight:600}.dim{color:var(--ink-3)}
.scroll{overflow-x:auto}
.tick{fill:var(--ink-3);font-size:10px;font-family:ui-monospace,Menlo,monospace}
svg{width:100%;height:auto;max-width:100%;margin-top:6px}
.dirtyflag{color:var(--sensitive);font-weight:700}
footer{margin-top:40px;padding-top:22px;border-top:1px solid var(--rule);
  color:var(--ink-3);font-size:13px;max-width:74ch}
.hidden{display:none!important}
"""

SCRIPT = """
const btns = [...document.querySelectorAll('.controls button')];
const shownEl = document.getElementById('shown');
function apply(f){
  let shown = 0;
  document.querySelectorAll('.page').forEach(pg => {
    let any = 0;
    pg.querySelectorAll('.leak').forEach(l => {
      const ok = f === 'all' ? true
        : f === 'sens' ? l.dataset.tier === 'sensitive'
        : l.dataset.rec === '0';
      l.classList.toggle('hidden', !ok);
      if (ok) { any++; shown++; }
    });
    pg.classList.toggle('hidden', any === 0);
  });
  if (shownEl) shownEl.textContent = shown + ' item' + (shown === 1 ? '' : 's') + ' shown';
}
btns.forEach(b => b.addEventListener('click', () => {
  btns.forEach(o => o.setAttribute('aria-pressed', o === b ? 'true' : 'false'));
  apply(b.dataset.f);
}));
if (btns.length) apply('all');
"""


def render(score: dict, corpus_name: str, *, held_out: bool,
           corpus=None, run_dir: Path | None = None) -> str:
    cfg = score.get("config", {})
    totals = score.get("totals", {})
    floor = score.get("recall_floor_pct") or 0.0
    ceiling = score.get("recall_ceiling_pct") or floor
    n = sum(totals.get(k, 0) for k in ("redacted", "leaked", "unverifiable"))
    git = git_state()
    hist = history_for(corpus_name)
    spark = _sparkline([h["recall_floor_pct"] for h in hist], held_out=held_out)
    band = f"{floor:.1f}%" if abs(ceiling - floor) < 0.05 else f"{floor:.1f}–{ceiling:.1f}%"
    pages = failures(corpus, run_dir) if run_dir is not None else []

    def shown(v) -> str:
        # A config line is read, not parsed. `False` and `None` both mean the
        # thing is off, and saying so beats making the reader translate.
        if v is True:
            return "on"
        if v is False or v is None:
            return "off"
        return str(v)

    conf = " · ".join(
        f"{html.escape(k)} <b>{html.escape(shown(cfg[k]))}</b>"
        for k in CONFIG_KEYS if k in cfg
    ) or "<b>defaults</b>"

    tiers = "".join(
        f"<div class='tile'><h3>{html.escape(tier)}</h3>"
        f"<div class='pct'>{(v.get('redacted', 0) / max(sum(v.values()), 1) * 100):.0f}%</div>"
        f"<div class='meter'>"
        f"<i class='ok' style='width:{v.get('redacted', 0) / max(sum(v.values()), 1) * 100:.1f}%'></i>"
        f"<i class='bad' style='width:{v.get('leaked', 0) / max(sum(v.values()), 1) * 100:.1f}%'></i>"
        f"</div><p>{v.get('redacted', 0)} covered · "
        f"<b class='bad'>{v.get('leaked', 0)}</b> leaked</p></div>"
        for tier, v in sorted(score.get("by_tier", {}).items())
    )

    hist_rows = "".join(
        f"<tr><td class='mono'>{html.escape(str(h.get('at', ''))[:16].replace('T', ' '))}</td>"
        f"<td class='mono'>{html.escape(str(h.get('git', {}).get('sha', '?')))}"
        + ("<span class='dirtyflag' title='uncommitted changes'>*</span>"
           if h.get("git", {}).get("dirty") else "")
        + f"</td><td class='mono'>{html.escape(str(h.get('run', '')))}</td>"
        f"<td class='n'>{h.get('recall_floor_pct')}%</td>"
        f"<td class='n dim'>{h.get('totals', {}).get('leaked', 0)}</td></tr>"
        for h in hist[-12:][::-1]
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(corpus_name)} — {band} — redaction report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>{STYLE}</style></head><body><div class="wrap">
<header>
  <div class="eyebrow">{html.escape(corpus_name)} · {cfg.get('image_count', '?')} images · {n} items</div>
  <h1>{html.escape(str(score.get('run_name', 'run')))}</h1>
</header>

<div class="tiles">
  <div class="tile">
    <h3>redaction recall</h3>
    <div class="pct">{band}</div>
    <div class="meter">
      <i class="ok" style="width:{floor:.1f}%"></i>
      <i class="bad" style="width:{100 - floor:.1f}%"></i>
    </div>
    <p><b>{totals.get('redacted', 0)}</b> covered ·
      <b class="bad">{totals.get('leaked', 0)}</b> still legible ·
      <b>{totals.get('unverifiable', 0)}</b> unverifiable</p>
    <p>{conf}</p>
    <p class="mono">{html.escape(git['sha'])}{' (uncommitted changes)' if git['dirty'] else ''}
      — {html.escape(git['subject'])}</p>
  </div>
  {tiers}
</div>

{_held_out_banner(hist, git['sha']) if held_out else ''}

<div class="callout">
  <h2>Trend</h2>
  {spark}
  {_delta_line(hist)}
</div>

{_failure_section(pages)}
{_rows(score)}
{"<h2>Recent runs on this corpus</h2><div class='scroll'><table><thead><tr><th>when</th><th>commit</th><th>run</th><th class='n'>floor</th><th class='n'>leaked</th></tr></thead><tbody>" + hist_rows + "</tbody></table></div>" if hist_rows else ""}

<footer>
  <p>Images are the annotated outputs from <code>annotate_leaks.py</code> where one exists,
  otherwise the redacted output. They are read from this run folder, so the page works
  offline and moves with the run.</p>
  <p>Written by <code>score_run.py</code>. History: <code>benchmarks/history.jsonl</code>{
    ' — held-out entries are flagged there too.' if held_out else '.'}</p>
</footer>
</div><script>{SCRIPT}</script></body></html>"""


def write(run_dir: Path, score: dict, corpus_name: str, *, held_out: bool,
          corpus=None) -> Path:
    path = Path(run_dir) / "report.html"
    path.write_text(
        render(score, corpus_name, held_out=held_out, corpus=corpus, run_dir=run_dir),
        encoding="utf-8",
    )
    return path


def open_in_browser(path: Path) -> bool:
    try:
        return webbrowser.open(Path(path).resolve().as_uri())
    except Exception:
        return False

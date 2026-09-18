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
    stroke = "var(--warn)" if held_out else "var(--accent)"
    fill = "var(--warn-fill)" if held_out else "var(--accent-fill)"
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
            for k, v in sorted(
                block.items(), key=lambda kv: -kv[1].get("leaked", 0)
            )
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
        f"<p class='note held'><b>Held out — this is a confirmation, not a "
        f"target.</b> Scored <b>{times}</b> time{'' if times == 1 else 's'} in "
        f"all.{repeat} No backend, threshold, upscale factor or preprocessing "
        f"choice may be made from this line. Decide with <code>cheques/</code>, "
        f"IndiaPII-Bench or maskara, then come back here once to see what "
        f"happened. A rising count means this corpus is being used as a "
        f"target.</p>"
    )


def _delta_line(hist: list[dict], held_out: bool) -> str:
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
        f"{html.escape(str(prev.get('at', ''))[:10])}). "
        f"Entry-count and config differences make a comparison meaningless "
        f"unless both ran the same corpus the same way — check the table below.</p>"
    )


def render(score: dict, corpus_name: str, *, held_out: bool) -> str:
    cfg = score.get("config", {})
    totals = score.get("totals", {})
    floor = score.get("recall_floor_pct") or 0.0
    ceiling = score.get("recall_ceiling_pct") or floor
    n = sum(totals.get(k, 0) for k in ("redacted", "leaked", "unverifiable"))
    git = git_state()
    hist = history_for(corpus_name)
    spark = _sparkline([h["recall_floor_pct"] for h in hist], held_out=held_out)
    band = f"{floor:.1f}%" if abs(ceiling - floor) < 0.05 else \
        f"{floor:.1f}–{ceiling:.1f}%"
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

    hist_rows = "".join(
        f"<tr><td class='mono'>{html.escape(str(h.get('at', ''))[:16].replace('T', ' '))}</td>"
        f"<td class='mono'>{html.escape(str(h.get('git', {}).get('sha', '?')))}"
        f"{'<span class=dirtyflag title=\"uncommitted changes\">*</span>' if h.get('git', {}).get('dirty') else ''}</td>"
        f"<td class='mono'>{html.escape(str(h.get('run', '')))}</td>"
        f"<td class='n'>{h.get('recall_floor_pct')}%</td>"
        f"<td class='n dim'>{h.get('totals', {}).get('leaked', 0)}</td></tr>"
        for h in hist[-12:][::-1]
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(corpus_name)} — {band} — redaction report</title>
<style>
:root{{
  --ground:#eef1f4;--surface:#fff;--surface-2:#f6f8fa;
  --ink:#131a21;--ink-2:#48565f;--ink-3:#77878f;--rule:#d5dde3;--rule-2:#e6ecf0;
  --accent:#1f6b63;--accent-fill:#dcebe8;--warn-fill:#f8ecdc;
  --ok:#1f6b63;--bad:#b03428;--warn:#8a5512;
}}
@media (prefers-color-scheme:dark){{:root{{
  --ground:#0e1319;--surface:#161d25;--surface-2:#1b232c;
  --ink:#e6edf2;--ink-2:#a3b1bc;--ink-3:#71818d;--rule:#2a343e;--rule-2:#222b34;
  --accent:#5fc4b4;--accent-fill:#12312d;--warn-fill:#352612;
  --ok:#5fc4b4;--bad:#f08b7d;--warn:#e0a458;
}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}}
.wrap{{max-width:780px;margin:0 auto;padding-inline:20px;padding-block:36px 64px}}
h1{{font-size:26px;letter-spacing:-.02em;margin:6px 0 0;text-wrap:balance}}
h2{{font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3);
   margin:30px 0 10px}}
.eyebrow{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--ink-3);font-weight:600}}
.card{{background:var(--surface);border:1px solid var(--rule);border-radius:10px;
  padding:22px;margin-top:22px}}
.big{{font-size:44px;font-weight:700;letter-spacing:-.03em;line-height:1;
  font-variant-numeric:tabular-nums}}
.sub{{color:var(--ink-2);font-size:14px;margin-top:8px}}
.mono,code{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
th,td{{text-align:left;padding:7px 10px;border-top:1px solid var(--rule-2)}}
thead th{{border-top:0;font-size:11px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink-3)}}
.n{{text-align:right;font-variant-numeric:tabular-nums}}
.ok{{color:var(--ok)}}.bad{{color:var(--bad);font-weight:600}}.dim{{color:var(--ink-3)}}
.scroll{{overflow-x:auto}}
.note{{color:var(--ink-2);font-size:14px;border-left:2px solid var(--rule);
  padding-left:12px;margin:14px 0 0;max-width:68ch}}
.note.held{{border-left-color:var(--bad)}}
.tick{{fill:var(--ink-3);font-size:10px;font-family:ui-monospace,Menlo,monospace}}
svg{{width:100%;height:auto;max-width:100%;margin-top:6px}}
.dirtyflag{{color:var(--warn);font-weight:700}}
footer{{margin-top:34px;color:var(--ink-3);font-size:13px}}
</style></head><body><div class="wrap">
<div class="eyebrow">{html.escape(corpus_name)} · {cfg.get('image_count', '?')} images · {n} items</div>
<h1>{html.escape(str(score.get('run_name', 'run')))}</h1>
<div class="card">
  <div class="big">{band}</div>
  <div class="sub"><b>{totals.get('redacted', 0)}</b> redacted ·
    <b class="bad">{totals.get('leaked', 0)}</b> still legible ·
    <b>{totals.get('unverifiable', 0)}</b> unverifiable</div>
  <div class="sub">{conf}</div>
  <div class="sub mono">{html.escape(git['sha'])}{'  (uncommitted changes)' if git['dirty'] else ''}
    — {html.escape(git['subject'])}</div>
  {spark}
  {_held_out_banner(hist, git['sha']) if held_out else ''}
  {_delta_line(hist, held_out)}
</div>
{_rows(score)}
{"<h2>Recent runs on this corpus</h2><div class='scroll'><table><thead><tr><th>when</th><th>commit</th><th>run</th><th class='n'>floor</th><th class='n'>leaked</th></tr></thead><tbody>" + hist_rows + "</tbody></table></div>" if hist_rows else ""}
<footer>Written by <code>score_run.py</code>. History:
<code>benchmarks/history.jsonl</code>{' — held-out entries are flagged there too.' if held_out else '.'}
</footer>
</div></body></html>"""


def write(run_dir: Path, score: dict, corpus_name: str, *, held_out: bool) -> Path:
    path = Path(run_dir) / "report.html"
    path.write_text(render(score, corpus_name, held_out=held_out), encoding="utf-8")
    return path


def open_in_browser(path: Path) -> bool:
    try:
        return webbrowser.open(path.resolve().as_uri())
    except Exception:
        return False

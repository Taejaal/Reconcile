#!/usr/bin/env python3
"""
generate_report.py
-------------------
Builds ONE self-contained HTML report comparing the reconciliation matcher's
performance on two datasets ("own" synthetic vs. "stress-test" adversarial).

No build step, no npm, no server. Run it, get an .html file, double-click it.
The only network dependency is that the browser (not this script) loads
Chart.js and two Google Fonts from a CDN when you open the file -- if you
need it to work fully offline, see the OFFLINE note near CHART_JS_CDN below.

USAGE
-----
    python3 generate_report.py \
        --own-audit own/audit_log.csv \
        --own-exceptions own/exceptions.csv \
        --stress-audit stress/audit_log.csv \
        --stress-exceptions stress/exceptions.csv \
        --output reconciliation_report.html

All four --*-audit/--*-exceptions flags default to the paths shown above,
so if your files already live under ./own/ and ./stress/ you can just run:

    python3 generate_report.py

Only stdlib is used (csv, json, argparse, html, pathlib) -- nothing to pip
install.

EDIT ME
-------
1. KNOWN_LIMITATIONS below -- replace with your real wording before the demo.
2. TOP_LINE_METRICS below -- these are your hardcoded precision/recall/F1/
   TP/FP/FN numbers. They are NOT recomputed from the CSVs on purpose
   (per your instructions) -- only the tier breakdown, rule-frequency
   breakdown, match rate, and exceptions tables are derived live from the
   CSVs you point the script at.
3. FALSE_POSITIVE_ROOT_CAUSE below -- the 3-category breakdown for the
   centerpiece section.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter
from pathlib import Path

# --------------------------------------------------------------------------
# EDIT ME: hardcoded top-line metrics (do not recompute from CSVs)
# --------------------------------------------------------------------------

TOP_LINE_METRICS = {
    "own": {
        "label": "Own Dataset",
        "subtitle": "Synthetic, self-generated",
        "precision": 79.3,
        "recall": 95.8,
        "f1": 86.8,
        "tp": 46,
        "fp": 10,
        "fn": 2,
        "true_matches": 48,
        "accent": "cyan",
    },
    "stress": {
        "label": "Stress-Test Dataset",
        "subtitle": "Independently generated, adversarial",
        "precision": 77.2,
        "recall": 71.0,
        "f1": 73.9,
        "tp": 44,
        "fp": 13,
        "fn": 18,
        "true_matches": 62,
        "accent": "coral",
    },
}

# --------------------------------------------------------------------------
# EDIT ME: false-positive root-cause breakdown (the centerpiece section)
# --------------------------------------------------------------------------

FALSE_POSITIVE_ROOT_CAUSE = [
    {
        "label": "Structural decoys",
        "count": 9,
        "total": 14,
        "note": "Unrelated transactions with coincidentally matching amount "
                "and date; not fixable without an extra data field.",
    },
    {
        "label": "Stolen match",
        "count": 4,
        "total": 14,
        "note": "Fixed by switching from greedy to optimal (Hungarian) "
                "assignment.",
    },
    {
        "label": "Cross-mismatch",
        "count": 1,
        "total": 14,
        "note": "Also fixed by the same greedy-to-optimal assignment change.",
    },
]

# --------------------------------------------------------------------------
# EDIT ME: known limitations -- replace with your exact wording
# --------------------------------------------------------------------------

KNOWN_LIMITATIONS = [
    "The matcher does not see a merchant-category or account-ID field, so "
    "structural decoys (same amount, same date, different counterparty) "
    "cannot currently be told apart from a true match.",
    "Greedy assignment is used instead of optimal (Hungarian) assignment, "
    "which accounts for 5 of the 14 false positives observed on the "
    "stress-test dataset.",
    "One-to-many splits (one bank deposit covering multiple ledger invoices) "
    "are not handled by the pairwise matching architecture.",
    "Text similarity is not currency/locale-aware and does not normalize "
    "merchant name variants or abbreviations beyond prefix/suffix stripping.",
]

# --------------------------------------------------------------------------
# EDIT ME: threshold sweep diagnostic results (from threshold_sweep.py)
# --------------------------------------------------------------------------

THRESHOLD_SWEEP_DATA = {
    "own": {
        "fp_scores": [0.391, 0.4, 0.449, 0.455, 0.522, 0.524, 0.679],
        "rescue_scores": [0.486, 0.5, 0.629, 0.756, 0.912, 1.0, 1.0, 1.0,
                          1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        "overlap_count": 3,
        "has_clean_gap": False,
    },
    "stress": {
        "fp_scores": [0.204, 0.254, 0.308, 0.344, 0.421, 0.423, 0.623, 0.667, 0.691],
        "rescue_scores": [0.294, 0.312, 0.339, 0.348, 0.364, 0.417, 0.435, 0.469,
                          0.511, 0.524, 0.585, 0.604, 0.617, 0.625, 0.667, 0.679,
                          0.684, 0.69, 0.691, 0.717, 0.727, 0.73, 0.792, 0.8, 0.809],
        "overlap_count": 7,
        "has_clean_gap": False,
    },
}

# Fixed display order for tiers and rules so charts/legends never reshuffle
# between runs just because a category happened to have zero rows.
TIER_ORDER = ["AUTO_MATCH", "NEEDS_REVIEW", "EXCEPTION"]
RULE_ORDER = [
    "EXACT_ID_MATCH",
    "EXACT_CONTENT_MATCH",
    "MONEY_DATE_LOCK",
    "TEXT_LOCK",
    "WEIGHTED_FALLBACK",
]

# OFFLINE note: these two CDNs are the only network calls the *browser* makes
# when the report is opened. If your demo machine/room has no internet,
# download chart.umd.min.js and the two font files once, then point these
# paths at local copies (e.g. "./vendor/chart.umd.min.js") -- everything
# else in the file is already self-contained.
CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"
FONTS_CDN = (
    "https://fonts.googleapis.com/css2?"
    "family=IBM+Plex+Sans:wght@400;500;600;700&"
    "family=IBM+Plex+Mono:wght@400;500;600&display=swap"
)


# --------------------------------------------------------------------------
# CSV loading
# --------------------------------------------------------------------------

def read_csv_rows(path: Path) -> list[dict]:
    """Read a CSV into a list of dicts. Returns [] if the file is missing
    so a report can still be generated with one dataset absent (and a
    visible warning) rather than crashing the whole script."""
    if not path.exists():
        print(f"  [!] warning: {path} not found -- treating as empty")
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_dataset(key: str, audit_path: Path, exceptions_path: Path) -> dict:
    audit_rows = read_csv_rows(audit_path)
    exception_rows = read_csv_rows(exceptions_path)

    tier_counts = Counter(row.get("tier", "").strip() for row in audit_rows)
    rule_counts = Counter(row.get("rule_fired", "").strip() for row in audit_rows)

    # Fold anything outside the known tiers/rules into an "OTHER" bucket
    # instead of silently dropping it -- keeps the chart totals honest.
    known_tiers = set(TIER_ORDER) - {"EXCEPTION"}
    other_tier_count = sum(v for k, v in tier_counts.items() if k not in known_tiers)
    known_rules = set(RULE_ORDER)
    other_rule_count = sum(v for k, v in rule_counts.items() if k not in known_rules)

    tier_values = [tier_counts.get(t, 0) for t in TIER_ORDER[:-1]]  # AUTO_MATCH, NEEDS_REVIEW
    tier_values.append(len(exception_rows))  # EXCEPTION comes from exceptions.csv, not tier col
    if other_tier_count:
        TIER_ORDER_LOCAL = TIER_ORDER + ["OTHER"]
        tier_values.append(other_tier_count)
    else:
        TIER_ORDER_LOCAL = TIER_ORDER

    rule_values = [rule_counts.get(r, 0) for r in RULE_ORDER]
    RULE_ORDER_LOCAL = RULE_ORDER
    if other_rule_count:
        RULE_ORDER_LOCAL = RULE_ORDER + ["OTHER"]
        rule_values.append(other_rule_count)

    matched_count = len(audit_rows)
    exception_count = len(exception_rows)
    total_records = matched_count + exception_count
    match_rate = (matched_count / total_records * 100) if total_records else 0.0

    metrics = TOP_LINE_METRICS[key]

    return {
        "key": key,
        "metrics": metrics,
        "match_rate": round(match_rate, 1),
        "matched_count": matched_count,
        "exception_count": exception_count,
        "total_records": total_records,
        "tier_labels": TIER_ORDER_LOCAL,
        "tier_values": tier_values,
        "rule_labels": RULE_ORDER_LOCAL,
        "rule_values": rule_values,
        "exception_rows": exception_rows,
        "exception_columns": list(exception_rows[0].keys()) if exception_rows else
            ["bank_txn_id", "ledger_txn_id", "amount", "date", "narration", "category"],
    }


# --------------------------------------------------------------------------
# HTML fragment builders
# --------------------------------------------------------------------------

def esc(value) -> str:
    return html.escape(str(value), quote=True)


def render_metric_column(ds: dict) -> str:
    m = ds["metrics"]
    accent = m["accent"]
    return f"""
    <div class="metrics-col metrics-col--{accent}">
      <div class="metrics-col__head">
        <span class="metrics-col__dot"></span>
        <div>
          <h2>{esc(m['label'])}</h2>
          <p>{esc(m['subtitle'])}</p>
        </div>
      </div>
      <div class="metrics-grid">
        <div class="metric">
          <span class="metric__value">{ds['match_rate']:.1f}<small>%</small></span>
          <span class="metric__label">Match rate</span>
        </div>
        <div class="metric">
          <span class="metric__value">{m['precision']:.1f}<small>%</small></span>
          <span class="metric__label">Precision</span>
        </div>
        <div class="metric">
          <span class="metric__value">{m['recall']:.1f}<small>%</small></span>
          <span class="metric__label">Recall</span>
        </div>
        <div class="metric metric--emphasis">
          <span class="metric__value">{m['f1']:.1f}<small>%</small></span>
          <span class="metric__label">F1 score</span>
        </div>
      </div>
      <div class="metrics-footnote">
        <span>{m['tp']} TP</span><span class="sep">&middot;</span>
        <span>{m['fp']} FP</span><span class="sep">&middot;</span>
        <span>{m['fn']} FN</span><span class="sep">&middot;</span>
        <span>{m['true_matches']} true matches</span>
      </div>
    </div>"""


def render_chart_pair(section_id: str, own: dict, stress: dict, kind: str) -> str:
    """kind: 'tier' (donut) or 'rule' (bar)"""
    blocks = []
    for ds in (own, stress):
        m = ds["metrics"]
        canvas_id = f"{section_id}-{ds['key']}"
        blocks.append(f"""
        <div class="chart-card chart-card--{m['accent']}">
          <div class="chart-card__head">
            <span class="chart-card__dot"></span>
            <h3>{esc(m['label'])}</h3>
          </div>
          <div class="chart-card__body">
            <canvas id="{canvas_id}"></canvas>
          </div>
        </div>""")
    return "\n".join(blocks)


def render_exceptions_table(ds: dict) -> str:
    cols = ds["exception_columns"]
    rows = ds["exception_rows"]
    thead = "".join(f'<th data-col="{i}">{esc(c.replace("_"," ").title())}</th>' for i, c in enumerate(cols))
    if not rows:
        tbody = f'<tr class="empty-row"><td colspan="{len(cols)}">No exception records -- every record was matched or reviewed.</td></tr>'
    else:
        body_rows = []
        for row in rows:
            cells = "".join(f"<td>{esc(row.get(c, ''))}</td>" for c in cols)
            body_rows.append(f"<tr>{cells}</tr>")
        tbody = "\n".join(body_rows)
    return f"""
    <table class="ex-table" data-count="{len(rows)}">
      <thead><tr>{thead}</tr></thead>
      <tbody>{tbody}</tbody>
    </table>"""


def render_fp_root_cause() -> str:
    cards = []
    colors = ["coral", "amber", "blue"]
    for item, color in zip(FALSE_POSITIVE_ROOT_CAUSE, colors):
        pct = round(item["count"] / item["total"] * 100)
        cards.append(f"""
        <div class="fp-card fp-card--{color}">
          <div class="fp-card__top">
            <span class="fp-card__frac">{item['count']}<span>/{item['total']}</span></span>
            <span class="fp-card__pct">{pct}%</span>
          </div>
          <h4>{esc(item['label'])}</h4>
          <p>{esc(item['note'])}</p>
        </div>""")
    return "\n".join(cards)


def render_limitations() -> str:
    items = "".join(f"<li>{esc(item)}</li>" for item in KNOWN_LIMITATIONS)
    return f"<ul>{items}</ul>"


def render_sweep_section() -> str:
    """Render the threshold sweep diagnostic as a two-column card with scatter charts."""
    cards = []
    for key, label, accent in [("own", "Own Dataset", "cyan"), ("stress", "Stress-Test Dataset", "coral")]:
        d = THRESHOLD_SWEEP_DATA[key]
        fp_count = len(d["fp_scores"])
        rescue_count = len(d["rescue_scores"])
        fp_min = min(d["fp_scores"]) if d["fp_scores"] else 0
        fp_max = max(d["fp_scores"]) if d["fp_scores"] else 0
        rescue_min = min(d["rescue_scores"]) if d["rescue_scores"] else 0
        rescue_max = max(d["rescue_scores"]) if d["rescue_scores"] else 0
        verdict_class = "verdict--fail" if not d["has_clean_gap"] else "verdict--pass"
        verdict_text = (
            f"No clean gap — {d['overlap_count']} false-positive scores overlap with genuine rescues. "
            f"A text floor would trade recall for precision."
        ) if not d["has_clean_gap"] else "Clean gap found — a text floor can safely separate false positives from genuine rescues."

        fp_dots = ", ".join(str(s) for s in d["fp_scores"])
        rescue_dots = ", ".join(str(s) for s in d["rescue_scores"])

        cards.append(f"""
        <div class="sweep-card sweep-card--{accent}">
          <div class="sweep-card__head">
            <span class="chart-card__dot"></span>
            <h3>{esc(label)}</h3>
          </div>
          <div class="sweep-stats">
            <div class="sweep-stat">
              <span class="sweep-stat__val">{fp_count}</span>
              <span class="sweep-stat__label">False-positive scores</span>
              <span class="sweep-stat__range">{fp_min:.3f} – {fp_max:.3f}</span>
            </div>
            <div class="sweep-stat">
              <span class="sweep-stat__val">{rescue_count}</span>
              <span class="sweep-stat__label">Genuine rescue scores</span>
              <span class="sweep-stat__range">{rescue_min:.3f} – {rescue_max:.3f}</span>
            </div>
            <div class="sweep-stat sweep-stat--overlap">
              <span class="sweep-stat__val">{d['overlap_count']}</span>
              <span class="sweep-stat__label">Overlapping scores</span>
            </div>
          </div>
          <div class="chart-card__body" style="height:200px;">
            <canvas id="sweep-{key}"></canvas>
          </div>
          <div class="sweep-verdict {verdict_class}">
            <p>{esc(verdict_text)}</p>
          </div>
          <div class="sweep-scores">
            <p><span class="sweep-dot sweep-dot--fp"></span> FP: [{fp_dots}]</p>
            <p><span class="sweep-dot sweep-dot--rescue"></span> Rescue: [{rescue_dots}]</p>
          </div>
        </div>""")
    return "\n".join(cards)


# --------------------------------------------------------------------------
# Main HTML template
# --------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Reconciliation Matcher &mdash; Results Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="__FONTS_CDN__" rel="stylesheet">
<script src="__CHART_JS_CDN__"></script>
<style>
__CSS__
</style>
</head>
<body>

<header class="hero">
  <div class="hero__inner">
    <p class="hero__kicker">AI Finance Controller &mdash; Razorpay Buildathon</p>
    <h1>Bank Statement &harr; Ledger Reconciliation Matcher</h1>
    <p class="hero__sub">Same matcher, two datasets: a synthetic set we built ourselves, and an independently generated adversarial stress test. Numbers below are reported side by side so the gap is visible, not smoothed over.</p>
  </div>
  <div class="metrics-row">
    __METRICS_OWN__
    __METRICS_STRESS__
  </div>
</header>

<main>

  <section class="section">
    <div class="section__head">
      <h2>Confidence tier breakdown</h2>
      <p>Every matched pair lands in AUTO_MATCH or NEEDS_REVIEW; unresolved records fall through to EXCEPTION.</p>
    </div>
    <div class="chart-pair">
      __TIER_CHARTS__
    </div>
  </section>

  <section class="section section--sweep">
    <div class="section__head">
      <h2>Threshold sweep diagnostic</h2>
      <p>Can a text-score floor cleanly separate coincidence false positives from genuine garbled-text rescues in the MONEY_DATE_LOCK rule? We swept every matched pair to find out.</p>
    </div>
    <div class="sweep-panel">
      __SWEEP_CARDS__
    </div>
    <div class="sweep-conclusion">
      <span class="sweep-conclusion__icon">&#128270;</span>
      <p><strong>Conclusion:</strong> No safe text-score threshold exists — the false-positive and genuine-rescue distributions overlap. The real production fix is an independent field (customer/account ID), not a stricter text threshold. This is documented as a known limitation, not hidden.</p>
    </div>
  </section>

  <section class="section">
    <div class="section__head">
      <h2>Matching rule frequency</h2>
      <p>Which rule in the cascade actually closed each match.</p>
    </div>
    <div class="chart-pair">
      __RULE_CHARTS__
    </div>
  </section>

  <section class="section section--fp">
    <div class="section__head">
      <h2>False positive root cause</h2>
      <p>Where the false positives actually come from, and which ones are fixable.</p>
    </div>
    <div class="fp-panel">
      __FP_CARDS__
    </div>
  </section>

  <section class="section">
    <div class="section__head">
      <h2>Exceptions</h2>
      <p>Unresolved records that need a human to close them out.</p>
    </div>
    <div class="tabs">
      <button class="tab-btn is-active" data-target="ex-own">Own dataset <span>__OWN_EX_COUNT__</span></button>
      <button class="tab-btn" data-target="ex-stress">Stress-test dataset <span>__STRESS_EX_COUNT__</span></button>
    </div>
    <div class="tab-panel is-active" id="ex-own">
      <div class="table-scroll">__EX_TABLE_OWN__</div>
    </div>
    <div class="tab-panel" id="ex-stress">
      <div class="table-scroll">__EX_TABLE_STRESS__</div>
    </div>
  </section>

  <section class="section">
    <div class="limitations">
      <div class="limitations__head">
        <span class="limitations__mark">&#9888;</span>
        <h2>Known limitations</h2>
      </div>
      __LIMITATIONS__
    </div>
  </section>

</main>

<footer class="footer">
  <p>Generated report &mdash; reconciliation matcher, own vs. stress-test dataset.</p>
</footer>

<script>
__JS__
</script>
</body>
</html>
"""


CSS_TEMPLATE = """
:root{
  --bg: #0a0e14;
  --panel: #121822;
  --panel-alt: #0e131c;
  --border: #202a38;
  --text: #e9eef3;
  --text-dim: #93a1b0;
  --text-faint: #5b6675;
  --cyan: #35d9c0;
  --cyan-dim: #1c7c6f;
  --coral: #ef6461;
  --coral-dim: #8a3b3a;
  --amber: #f2a93b;
  --amber-dim: #8a6425;
  --blue: #5c8df2;
  --blue-dim: #35508a;
  --radius: 8px;
}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{
  background:var(--bg);
  color:var(--text);
  font-family:"IBM Plex Sans", -apple-system, "Segoe UI", sans-serif;
  line-height:1.5;
  -webkit-font-smoothing:antialiased;
}
.num, .metric__value, .fp-card__frac, .fp-card__pct, table.ex-table td, .metrics-footnote{
  font-family:"IBM Plex Mono", ui-monospace, SFMono-Regular, monospace;
  font-feature-settings:"tnum";
}
h1,h2,h3,h4{
  font-family:"IBM Plex Sans", sans-serif;
  font-weight:600;
  margin:0;
  letter-spacing:-0.01em;
}
p{margin:0;color:var(--text-dim);}

/* ---------- Hero ---------- */
.hero{
  padding:56px 6vw 0 6vw;
  border-bottom:1px solid var(--border);
  background:
    radial-gradient(1200px 400px at 15% -10%, rgba(53,217,192,0.10), transparent 60%),
    radial-gradient(1200px 400px at 85% -10%, rgba(239,100,97,0.10), transparent 60%);
}
.hero__inner{max-width:900px;margin:0 auto 40px auto;text-align:left;}
.hero__kicker{
  color:var(--text-faint);
  font-size:13px;
  font-weight:500;
  margin-bottom:14px;
}
.hero h1{
  font-size:clamp(28px, 4vw, 44px);
  line-height:1.15;
  margin-bottom:16px;
  max-width:16ch;
}
.hero__sub{
  font-size:16px;
  max-width:62ch;
  color:var(--text-dim);
}
.metrics-row{
  max-width:1200px;
  margin:0 auto;
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:1px;
  background:var(--border);
  border:1px solid var(--border);
  border-bottom:none;
  border-radius:var(--radius) var(--radius) 0 0;
  overflow:hidden;
}
@media (max-width:820px){ .metrics-row{grid-template-columns:1fr;} }

.metrics-col{
  background:var(--panel);
  padding:32px clamp(20px,3vw,40px) 36px;
}
.metrics-col__head{
  display:flex;
  align-items:flex-start;
  gap:10px;
  margin-bottom:26px;
}
.metrics-col__dot{
  width:10px;height:10px;border-radius:50%;
  margin-top:6px;flex:none;
}
.metrics-col--cyan .metrics-col__dot{background:var(--cyan);box-shadow:0 0 12px rgba(53,217,192,0.6);}
.metrics-col--coral .metrics-col__dot{background:var(--coral);box-shadow:0 0 12px rgba(239,100,97,0.6);}
.metrics-col__head h2{font-size:19px;}
.metrics-col__head p{font-size:13px;margin-top:2px;}

.metrics-grid{
  display:grid;
  grid-template-columns:repeat(4,1fr);
  gap:18px;
}
@media (max-width:560px){ .metrics-grid{grid-template-columns:repeat(2,1fr);} }
.metric{display:flex;flex-direction:column;gap:4px;}
.metric__value{
  font-size:clamp(26px,3vw,34px);
  font-weight:600;
  color:var(--text);
}
.metric__value small{font-size:0.5em;color:var(--text-dim);font-weight:500;}
.metric__label{
  font-size:12.5px;
  color:var(--text-dim);
}
.metric--emphasis .metric__value{color:var(--cyan);}
.metrics-col--coral .metric--emphasis .metric__value{color:var(--coral);}

.metrics-footnote{
  margin-top:24px;
  padding-top:18px;
  border-top:1px solid var(--border);
  font-size:13px;
  color:var(--text-dim);
}
.metrics-footnote .sep{margin:0 8px;color:var(--text-faint);}

/* ---------- Main / sections ---------- */
main{max-width:1200px;margin:0 auto;padding:0 6vw;}
.section{
  padding:56px 0;
  border-bottom:1px solid var(--border);
}
.section__head{
  margin-bottom:26px;
  max-width:60ch;
}
.section__head h2{font-size:22px;margin-bottom:6px;}
.section__head p{font-size:14.5px;}

/* ---------- Charts ---------- */
.chart-pair{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:20px;
}
@media (max-width:820px){ .chart-pair{grid-template-columns:1fr;} }
.chart-card{
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:var(--radius);
  padding:20px 22px 22px;
}
.chart-card__head{display:flex;align-items:center;gap:9px;margin-bottom:14px;}
.chart-card__dot{width:8px;height:8px;border-radius:50%;}
.chart-card--cyan .chart-card__dot{background:var(--cyan);}
.chart-card--coral .chart-card__dot{background:var(--coral);}
.chart-card__head h3{font-size:14.5px;font-weight:500;color:var(--text-dim);}
.chart-card__body{position:relative;height:260px;}
.chart-fallback{
  display:flex;align-items:center;justify-content:center;
  height:100%;text-align:center;font-size:12.5px;
  color:var(--text-faint);padding:0 10px;
}

/* ---------- False positive centerpiece ---------- */
.section--fp{
  background:linear-gradient(180deg, rgba(239,100,97,0.05), transparent 30%);
}
.fp-panel{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:18px;
  border:1px solid var(--coral-dim);
  border-radius:12px;
  padding:22px;
  background:var(--panel);
  box-shadow:0 0 0 1px rgba(239,100,97,0.08), 0 20px 60px -30px rgba(239,100,97,0.4);
}
@media (max-width:820px){ .fp-panel{grid-template-columns:1fr;} }
.fp-card{
  background:var(--panel-alt);
  border:1px solid var(--border);
  border-radius:var(--radius);
  padding:20px;
  display:flex;
  flex-direction:column;
  gap:10px;
}
.fp-card__top{display:flex;align-items:baseline;justify-content:space-between;}
.fp-card__frac{font-size:30px;font-weight:600;color:var(--text);}
.fp-card__frac span{font-size:0.55em;color:var(--text-faint);font-weight:500;}
.fp-card__pct{font-size:14px;color:var(--text-dim);}
.fp-card h4{font-size:15px;}
.fp-card p{font-size:13px;line-height:1.55;}
.fp-card--coral{border-top:3px solid var(--coral);}
.fp-card--amber{border-top:3px solid var(--amber);}
.fp-card--blue{border-top:3px solid var(--blue);}

/* ---------- Tabs + table ---------- */
.tabs{display:flex;gap:8px;margin-bottom:18px;}
.tab-btn{
  background:var(--panel);
  border:1px solid var(--border);
  color:var(--text-dim);
  font-family:inherit;
  font-size:13.5px;
  font-weight:500;
  padding:9px 16px;
  border-radius:999px;
  cursor:pointer;
  display:flex;
  align-items:center;
  gap:8px;
  transition:border-color .15s ease, color .15s ease;
}
.tab-btn span{
  font-family:"IBM Plex Mono", monospace;
  font-size:11.5px;
  background:var(--panel-alt);
  padding:1px 7px;
  border-radius:999px;
  color:var(--text-faint);
}
.tab-btn:hover{color:var(--text);}
.tab-btn.is-active{color:var(--text);border-color:var(--cyan);}
.tab-panel{display:none;}
.tab-panel.is-active{display:block;}

.table-scroll{
  max-height:420px;
  overflow:auto;
  border:1px solid var(--border);
  border-radius:var(--radius);
}
table.ex-table{
  width:100%;
  border-collapse:collapse;
  font-size:13.5px;
}
table.ex-table thead th{
  position:sticky;top:0;
  background:var(--panel-alt);
  text-align:left;
  padding:11px 14px;
  font-family:"IBM Plex Sans", sans-serif;
  font-weight:600;
  font-size:12px;
  color:var(--text-dim);
  border-bottom:1px solid var(--border);
  cursor:pointer;
  user-select:none;
  white-space:nowrap;
}
table.ex-table thead th:hover{color:var(--text);}
table.ex-table thead th::after{content:"";margin-left:6px;color:var(--text-faint);}
table.ex-table thead th.sort-asc::after{content:"\\2191";}
table.ex-table thead th.sort-desc::after{content:"\\2193";}
table.ex-table td{
  padding:10px 14px;
  border-bottom:1px solid var(--border);
  color:var(--text);
  white-space:nowrap;
}
table.ex-table tbody tr:last-child td{border-bottom:none;}
table.ex-table tbody tr:hover{background:rgba(255,255,255,0.02);}
table.ex-table .empty-row td{color:var(--text-faint);white-space:normal;font-family:"IBM Plex Sans",sans-serif;padding:24px 14px;}

/* ---------- Limitations ---------- */
.limitations{
  border:1px solid var(--amber-dim);
  background:linear-gradient(180deg, rgba(242,169,59,0.06), transparent 60%);
  border-radius:12px;
  padding:24px 26px;
}
.limitations__head{display:flex;align-items:center;gap:10px;margin-bottom:14px;}
.limitations__mark{color:var(--amber);font-size:18px;}
.limitations__head h2{font-size:16px;color:var(--amber);}
.limitations ul{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:9px;}
.limitations li{font-size:14px;color:var(--text-dim);}

/* ---------- Threshold Sweep ---------- */
.section--sweep{
  background:linear-gradient(180deg, rgba(92,141,242,0.05), transparent 30%);
}
.sweep-panel{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:20px;
}
@media (max-width:820px){ .sweep-panel{grid-template-columns:1fr;} }
.sweep-card{
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:var(--radius);
  padding:20px 22px 22px;
}
.sweep-card--cyan{border-top:3px solid var(--cyan);}
.sweep-card--coral{border-top:3px solid var(--coral);}
.sweep-card__head{display:flex;align-items:center;gap:9px;margin-bottom:14px;}
.sweep-card__head h3{font-size:14.5px;font-weight:500;color:var(--text-dim);}
.sweep-stats{
  display:grid;
  grid-template-columns:1fr 1fr 1fr;
  gap:12px;
  margin-bottom:16px;
}
.sweep-stat{display:flex;flex-direction:column;gap:2px;}
.sweep-stat__val{
  font-family:"IBM Plex Mono", monospace;
  font-size:22px;font-weight:600;color:var(--text);
}
.sweep-stat__label{font-size:11.5px;color:var(--text-dim);}
.sweep-stat__range{font-family:"IBM Plex Mono", monospace;font-size:11px;color:var(--text-faint);}
.sweep-stat--overlap .sweep-stat__val{color:var(--coral);}
.sweep-verdict{
  margin-top:14px;
  padding:12px 16px;
  border-radius:var(--radius);
  border:1px solid var(--border);
  background:var(--panel-alt);
}
.sweep-verdict p{font-size:13px;line-height:1.55;}
.verdict--fail{border-left:3px solid var(--coral);}
.verdict--pass{border-left:3px solid var(--cyan);}
.sweep-scores{
  margin-top:12px;
  font-family:"IBM Plex Mono", monospace;
  font-size:11px;
  color:var(--text-faint);
  display:flex;flex-direction:column;gap:4px;
}
.sweep-scores p{color:var(--text-faint);font-size:11px;}
.sweep-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;}
.sweep-dot--fp{background:var(--coral);}
.sweep-dot--rescue{background:var(--cyan);}
.sweep-conclusion{
  margin-top:20px;
  padding:16px 20px;
  border:1px solid var(--blue-dim);
  border-radius:var(--radius);
  background:var(--panel);
  display:flex;align-items:flex-start;gap:12px;
}
.sweep-conclusion__icon{font-size:20px;flex:none;margin-top:1px;}
.sweep-conclusion p{font-size:14px;color:var(--text-dim);line-height:1.55;}

/* ---------- Footer ---------- */
.footer{
  text-align:center;
  padding:30px 6vw 50px;
  color:var(--text-faint);
  font-size:12.5px;
}
"""


JS_TEMPLATE = """
const CHART_COLORS = {
  cyan: "#35d9c0",
  coral: "#ef6461",
  amber: "#f2a93b",
  blue: "#5c8df2",
  faint: "#5b6675",
  grid: "#202a38",
  text: "#93a1b0"
};

// Charts are progressive enhancement: if the Chart.js CDN can't be reached
// (offline demo room, blocked script, etc.) the tabs/sorting below must
// still work, so every Chart.js call is guarded behind this flag instead
// of letting a ReferenceError stop the whole script.
const CHARTS_AVAILABLE = typeof Chart !== "undefined";
if (CHARTS_AVAILABLE) {
  Chart.defaults.font.family = "'IBM Plex Mono', monospace";
  Chart.defaults.color = CHART_COLORS.text;
} else {
  console.warn("Chart.js did not load (offline?) -- skipping charts, everything else still works.");
  document.querySelectorAll(".chart-card__body").forEach(el => {
    el.innerHTML = '<p class="chart-fallback">Chart.js could not be loaded from the CDN (no internet connection). The underlying numbers are still in the tables below.</p>';
  });
}

function donut(canvasId, labels, values, accentColor){
  if (!CHARTS_AVAILABLE) return;
  const el = document.getElementById(canvasId);
  if(!el) return;
  const palette = [accentColor, "#f2a93b", "#5c8df2", "#5b6675"];
  new Chart(el, {
    type: "doughnut",
    data: {
      labels: labels,
      datasets: [{
        data: values,
        backgroundColor: labels.map((_, i) => palette[i % palette.length]),
        borderColor: "#0e131c",
        borderWidth: 2,
        hoverOffset: 6
      }]
    },
    options: {
      maintainAspectRatio: false,
      cutout: "62%",
      plugins: {
        legend: {
          position: "bottom",
          labels: { boxWidth: 10, boxHeight: 10, padding: 14, font: { size: 11.5 } }
        }
      }
    }
  });
}

function bar(canvasId, labels, values, accentColor){
  if (!CHARTS_AVAILABLE) return;
  const el = document.getElementById(canvasId);
  if(!el) return;
  new Chart(el, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [{
        data: values,
        backgroundColor: accentColor,
        borderRadius: 4,
        maxBarThickness: 34
      }]
    },
    options: {
      maintainAspectRatio: false,
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: CHART_COLORS.grid }, ticks: { precision: 0 } },
        y: { grid: { display: false }, ticks: { font: { family: "IBM Plex Sans", size: 11.5 } } }
      }
    }
  });
}

const REPORT_DATA = __REPORT_DATA_JSON__;

donut("tier-own", REPORT_DATA.own.tier_labels, REPORT_DATA.own.tier_values, CHART_COLORS.cyan);
donut("tier-stress", REPORT_DATA.stress.tier_labels, REPORT_DATA.stress.tier_values, CHART_COLORS.coral);
bar("rule-own", REPORT_DATA.own.rule_labels, REPORT_DATA.own.rule_values, CHART_COLORS.cyan);
bar("rule-stress", REPORT_DATA.stress.rule_labels, REPORT_DATA.stress.rule_values, CHART_COLORS.coral);

// Sweep scatter charts
function sweepScatter(canvasId, fpScores, rescueScores, accentColor) {
  if (!CHARTS_AVAILABLE) return;
  const el = document.getElementById(canvasId);
  if (!el) return;
  const fpData = fpScores.map((v, i) => ({x: v, y: 0.3 + Math.random() * 0.15}));
  const rescueData = rescueScores.map((v, i) => ({x: v, y: 0.6 + Math.random() * 0.15}));
  new Chart(el, {
    type: "scatter",
    data: {
      datasets: [
        {
          label: "False positives",
          data: fpData,
          backgroundColor: CHART_COLORS.coral + "cc",
          borderColor: CHART_COLORS.coral,
          pointRadius: 6,
          pointHoverRadius: 8,
        },
        {
          label: "Genuine rescues",
          data: rescueData,
          backgroundColor: accentColor + "cc",
          borderColor: accentColor,
          pointRadius: 6,
          pointHoverRadius: 8,
        }
      ]
    },
    options: {
      maintainAspectRatio: false,
      scales: {
        x: {
          title: { display: true, text: "text_score", font: { size: 11 } },
          min: 0, max: 1.05,
          grid: { color: CHART_COLORS.grid },
        },
        y: {
          display: false,
          min: 0, max: 1,
        }
      },
      plugins: {
        legend: {
          position: "bottom",
          labels: { boxWidth: 10, boxHeight: 10, padding: 12, font: { size: 11 } }
        },
        tooltip: {
          callbacks: {
            label: function(ctx) { return ctx.dataset.label + ": " + ctx.parsed.x.toFixed(3); }
          }
        }
      }
    }
  });
}

const SWEEP = REPORT_DATA.sweep;
sweepScatter("sweep-own", SWEEP.own.fp_scores, SWEEP.own.rescue_scores, CHART_COLORS.cyan);
sweepScatter("sweep-stress", SWEEP.stress.fp_scores, SWEEP.stress.rescue_scores, CHART_COLORS.coral);

// Tabs
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("is-active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("is-active"));
    btn.classList.add("is-active");
    document.getElementById(btn.dataset.target).classList.add("is-active");
  });
});

// Sortable tables (click a header to sort by that column, click again to reverse)
document.querySelectorAll("table.ex-table").forEach(table => {
  const headers = table.querySelectorAll("thead th");
  headers.forEach((th, colIndex) => {
    let dir = null;
    th.addEventListener("click", () => {
      const tbody = table.querySelector("tbody");
      if (tbody.querySelector(".empty-row")) return;
      const rows = Array.from(tbody.querySelectorAll("tr"));
      dir = dir === "asc" ? "desc" : "asc";
      headers.forEach(h => h.classList.remove("sort-asc", "sort-desc"));
      th.classList.add(dir === "asc" ? "sort-asc" : "sort-desc");
      rows.sort((a, b) => {
        const av = a.children[colIndex].textContent.trim();
        const bv = b.children[colIndex].textContent.trim();
        const an = parseFloat(av.replace(/,/g, ""));
        const bn = parseFloat(bv.replace(/,/g, ""));
        let cmp;
        if (!isNaN(an) && !isNaN(bn)) { cmp = an - bn; }
        else { cmp = av.localeCompare(bv); }
        return dir === "asc" ? cmp : -cmp;
      });
      rows.forEach(r => tbody.appendChild(r));
    });
  });
});
"""


def build_html(own: dict, stress: dict) -> str:
    report_data_json = json.dumps({
        "own": {"tier_labels": own["tier_labels"], "tier_values": own["tier_values"],
                "rule_labels": own["rule_labels"], "rule_values": own["rule_values"]},
        "stress": {"tier_labels": stress["tier_labels"], "tier_values": stress["tier_values"],
                   "rule_labels": stress["rule_labels"], "rule_values": stress["rule_values"]},
        "sweep": {
            "own": {"fp_scores": THRESHOLD_SWEEP_DATA["own"]["fp_scores"],
                    "rescue_scores": THRESHOLD_SWEEP_DATA["own"]["rescue_scores"]},
            "stress": {"fp_scores": THRESHOLD_SWEEP_DATA["stress"]["fp_scores"],
                       "rescue_scores": THRESHOLD_SWEEP_DATA["stress"]["rescue_scores"]},
        },
    })

    js = JS_TEMPLATE.replace("__REPORT_DATA_JSON__", report_data_json)

    html_out = HTML_TEMPLATE
    html_out = html_out.replace("__FONTS_CDN__", FONTS_CDN)
    html_out = html_out.replace("__CHART_JS_CDN__", CHART_JS_CDN)
    html_out = html_out.replace("__CSS__", CSS_TEMPLATE)
    html_out = html_out.replace("__JS__", js)
    html_out = html_out.replace("__METRICS_OWN__", render_metric_column(own))
    html_out = html_out.replace("__METRICS_STRESS__", render_metric_column(stress))
    html_out = html_out.replace("__TIER_CHARTS__", render_chart_pair("tier", own, stress, "tier"))
    html_out = html_out.replace("__RULE_CHARTS__", render_chart_pair("rule", own, stress, "rule"))
    html_out = html_out.replace("__FP_CARDS__", render_fp_root_cause())
    html_out = html_out.replace("__SWEEP_CARDS__", render_sweep_section())
    html_out = html_out.replace("__OWN_EX_COUNT__", str(own["exception_count"]))
    html_out = html_out.replace("__STRESS_EX_COUNT__", str(stress["exception_count"]))
    html_out = html_out.replace("__EX_TABLE_OWN__", render_exceptions_table(own))
    html_out = html_out.replace("__EX_TABLE_STRESS__", render_exceptions_table(stress))
    html_out = html_out.replace("__LIMITATIONS__", render_limitations())
    return html_out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--own-audit", default="own/audit_log.csv")
    parser.add_argument("--own-exceptions", default="own/exceptions.csv")
    parser.add_argument("--stress-audit", default="stress/audit_log.csv")
    parser.add_argument("--stress-exceptions", default="stress/exceptions.csv")
    parser.add_argument("--output", default="reconciliation_report.html")
    args = parser.parse_args()

    print("Reading CSVs...")
    own = build_dataset("own", Path(args.own_audit), Path(args.own_exceptions))
    stress = build_dataset("stress", Path(args.stress_audit), Path(args.stress_exceptions))

    print("Building report...")
    out_path = Path(args.output)
    out_path.write_text(build_html(own, stress), encoding="utf-8")
    print(f"Done -- wrote {out_path.resolve()}")
    print(f"  own:    {own['matched_count']} matched, {own['exception_count']} exceptions")
    print(f"  stress: {stress['matched_count']} matched, {stress['exception_count']} exceptions")


if __name__ == "__main__":
    main()

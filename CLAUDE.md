# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal analysis tool that tracks money rotation across all 11 S&P 500 GICS sectors
(via the Sector SPDR ETFs), originally built to catch **early** signs of which sector is
about to receive the next wave of inflows via a Relative Rotation Graph (RRG) approach
(JdK RS-Ratio / RS-Momentum, quadrant classification) — as opposed to the lagging
moving-average-crossover approach used in the sibling project `Sector_Rotation`.

**Important scope-of-truth update (Phase B)**: an informal backtest (`backtest_rrg.py`)
plus web research found no real evidence that RRG's "Improving" quadrant has early
predictive value for sector rotation — see "Phase B: informal backtest results" below.
The RRG chart is kept as a visualization (it's still a legible "where is everything
right now" snapshot), but its wording was deliberately softened to stop implying
validated predictive power, and a second, evidence-backed view was added:
`plot_momentum_ranking.py`, a plain 12-month trailing-momentum leaderboard based on
Moskowitz & Grinblatt (1999) industry-momentum research. **When in doubt about which
view to trust for an actual decision, trust the momentum ranking, not the RRG
quadrant** — that's the whole point of Phase B's finding.

This is a deliberate sibling/successor to `Sector_Rotation` (same machine, directory
`../Sector_Rotation`), not a fork of it — see "Why a separate repo" below. Currently
**Phase A+B**: a PC-run pipeline that produces an RRG chart and a momentum-ranking
chart. No CI, no publishing, no mobile app yet (see "Planned phases" below).

All user-facing text (CLI output, chart labels, docs) is in Japanese.

## Commands

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

.\venv\Scripts\python.exe rrg_monitor.py             # 1. fetch prices, compute RS-Ratio/RS-Momentum + momentum ranking -> output/*.csv
.\venv\Scripts\python.exe plot_rrg.py                # 2a. render the RRG comet chart -> output/rrg_chart_*.png (+ sub 20d version)
.\venv\Scripts\python.exe plot_momentum_ranking.py   # 2b. render the 12-month momentum leaderboard -> output/momentum_ranking_chart_*.png
.\venv\Scripts\python.exe backtest_rrg.py            # optional: re-run the informal backtest (daily + weekly variants, ~5 min, hits network for 8y of data)
```

No test suite, no lint command.

## Architecture

### Data flow
`rrg_monitor.py` is the only script that hits the network (via `download_prices()`,
ported from `Sector_Rotation/sector_rotation_monitor.py`'s retry/MultiIndex-handling
logic). It writes a **long-format** CSV (`output/rrg_data_YYYYMMDD.csv`, one row per
`Date` × `Symbol`) — unlike `Sector_Rotation`'s one-CSV-per-pair convention, this repo
tracks a single cross-sectional table because RRG and rank-acceleration are inherently
cross-sectional (every sector needs to be compared against all the others on the same
day, not just against its own history). `plot_rrg.py` reads that CSV and never
recomputes anything — same "read the previous step's output" convention as the sibling
repo.

### The methodology (CONFIG in rrg_monitor.py)
- `RS_Ratio` = a rolling z-score (window `CONFIG["window"]`, default 63 trading days)
  of each sector's EMA-smoothed price ratio to the benchmark (`CONFIG["benchmark"]`,
  default `RSP` — equal-weight S&P 500, chosen over cap-weighted `SPY` specifically to
  avoid comparing e.g. XLK against an index SPY where XLK itself is a huge chunk of the
  weight).
- `RS_Momentum` = a rolling z-score of the *rate of change* of `RS_Ratio` over
  `CONFIG["momentum_lookback"]` days (default 5) — this is what makes the tool
  early/leading rather than lagging: it can flip before the raw level does.
- Both center on 100; `classify_quadrant()` buckets each day into Leading (≥100/≥100),
  Weakening (≥100/<100), Lagging (<100/<100), or **Improving** (<100/≥100) — Improving
  is the "early rotation candidate" signal this whole tool exists to surface.
- `RankAccel` (in `compute_rrg()`) is a secondary, deliberately simple confirming
  signal: the 2nd difference of each day's cross-sectional RS_Ratio rank among the 11
  sectors. It's a numeric leaderboard column only — **not** a second chart — mirroring
  how `Sector_Rotation` keeps its valuation read to one explainable composite score
  rather than reporting several raw metrics side by side.
- This is an honest self-implemented approximation of the JdK RRG methodology, not a
  claim of reproducing Julius de Kempenaer's unpublished exact constants — say so in
  any UI/doc text, same spirit as `top_holdings.py`'s "relative, not fair value"
  framing in the sibling repo.
- The window/lookback constants in `CONFIG` were tuning candidates in Phase B (see
  below) — the backtest found no variant worth switching to, so they're unchanged
  from the Phase A starting values, not because they were validated as optimal.
- `CONFIG["period"]` is `"2y"`, not `"1y"` — it needs to comfortably exceed
  `momentum_ranking_lookback_days` (252 trading days) so the newest date has a valid
  "252 trading days ago" price to diff against. `"1y"` actually returns ~251 trading
  days from yfinance (confirmed empirically), one short of what's needed — this bit
  Phase B, so don't shrink `period` back toward 1y without re-checking this.
- `GROUP_COLORS`/`GROUP_LABELS` (the 4 macro-group color/label dicts) live in
  `rrg_monitor.py`, not in either plot script — both `plot_rrg.py` and
  `plot_momentum_ranking.py` import them from there so the two charts' color coding
  always stays in sync. They used to be defined locally in `plot_rrg.py`; if you find
  a stray local copy anywhere, that's drift, not intentional duplication.

### Momentum ranking (`compute_momentum_ranking()` in rrg_monitor.py, plot_momentum_ranking.py)
Added in Phase B specifically *because* the RRG backtest came back weak — this is the
"trustworthy" view, by design. Deliberately the opposite of RRG's design: no EMA
smoothing, no rolling z-score, just `Close(i, today) / Close(i, today-252) - 1` minus
the same for the benchmark, ranked. The smoothing/normalization in RRG's `compute_rrg`
was specifically named by outside research as *why* RRG lags rather than leads (the
EMA eats the lead time) — so this view intentionally avoids that whole apparatus
rather than trying to tune it further. `RelativeReturn` (excess return vs `RSP`) is
the display metric, but note the *rank order* would be identical using raw
`TrailingReturn` instead — subtracting the same benchmark return from every sector
shifts all values by a constant and can't change their relative order. It's shown
anyway because "how much it's beating the market by" is more legible than a raw
12-month return number on its own.

### plot_rrg.py chart design (already-resolved gotchas, don't redo this analysis)
- **Color is a secondary encoding of 4 macro-groups, not per-sector identity.** With
  11 series, colorblind-safe all-pairs comparison caps out around 4 usable hues (see
  the `dataviz` skill's palette validator), so each sector is assigned one of
  `GROUP_COLORS` (growth/value/defensive/rate_sensitive) and the *primary* identity
  channel is a direct ticker-label at the tail head — don't add an 11-entry legend as
  a "fix" for this, it was deliberately rejected in favor of direct labeling.
- **Quadrant background tint is a single neutral gray at varying alpha, not 4 status
  colors.** Leading/Weakening/Lagging/Improving is a cyclical position, not a
  good/bad judgment — using e.g. green-for-Leading/red-for-Lagging would wrongly imply
  a normative read. Keep the wash neutral; corner text labels carry the meaning.
- **The group-color legend sits outside the axes** (`bbox_to_anchor=(1.02, 1.0)`)
  because all four plot corners are already occupied by quadrant labels — an
  in-plot corner legend (tried first) collided with the Weakening label specifically.
  `draw_ticker_glossary()` (ticker → full Japanese sector name, grouped under the
  same 4 macro-group headings/colors as the legend) is stacked directly below it in
  the same right-side margin, starting at a hardcoded `start_y` — if the legend ever
  grows (more groups, longer title), re-check that `start_y` still clears it.
- `draw_quadrant_background()`'s `axvspan(..., ymin=, ymax=)` call mixes coordinate
  systems on purpose: `xmin`/`xmax` are data coordinates, `ymin`/`ymax` are
  axes-fraction (0-1) — this is normal `axvspan` behavior, not a bug, and the
  fraction conversion from data coordinates is done inline in the function.
- **Axis limits (`draw_rrg_scatter`) are sized from the *plotted* tail only, not the
  full downloaded history, and X/Y are padded independently rather than forced
  square.** An earlier version sized the axes off the full ~1-year history's max
  deviation and used one shared `max_dev` for both axes — since only the last
  `tail_days` points are ever drawn, that left huge unused margin (framing for
  extremes from months ago) and wasted space on whichever axis has the smaller
  natural spread. Don't reintroduce either shortcut; both were explicit fixes for
  "the chart has too much dead space" feedback.
- **Sector-ticker labels are placed via `adjust_text` (the `adjustText` package,
  added as a dependency for this reason alone)**, not a fixed `xytext` offset —
  with several sectors clustered in the same quadrant (Improving especially), fixed
  offsets produced overlapping, unreadable labels. `adjust_text` is called once at
  the end of `draw_rrg_scatter` with all label `Text` objects plus the raw point
  coordinates (so labels repel both each other and the dots), and draws a thin
  connector line (`arrowprops`) when a label had to move away from its point. A
  matplotlib version warning ("transform doesn't support FancyArrowPatch...") prints
  to console on every run — cosmetic, from `adjustText`'s internal fallback path, not
  a sign anything is broken; confirmed by inspecting the rendered output.
- **The situation-summary banner (`draw_situation_banner`) wraps Japanese text with a
  hand-rolled `_wrap_cjk()`, not `textwrap.fill`.** `textwrap` only breaks on
  whitespace, and Japanese sentences have none between "words," so a whole clause can
  come out as one unbreakable token far wider than the intended wrap width (bug seen
  and fixed). `_wrap_cjk` counts full-width characters as width 2 so wrapping matches
  visual width, not code-point count. The banner axes' height is computed *from* the
  resulting line count (`main()`, `banner_height_in = header + lines*line_height + pad`)
  rather than a fixed guess — text volume is data-dependent (varies with how many
  sectors land in each quadrant on a given day), and a fixed-height banner will
  eventually overflow into the chart title below it on some future day even if it
  looks fine today. If you widen or narrow `wrap_situation_text`'s `max_width`, the
  banner height adapts automatically — no other change needed.

### Encoding
Same `console_utf8.py` fix as the sibling repo (copied verbatim, not imported across
repos) — must stay the first import in any new entry-point script that prints
Japanese text.

## Why a separate repo (not added to `Sector_Rotation`)
`Sector_Rotation`'s `CONFIG["pairs"]` is shaped for exactly two named baskets compared
via one ratio; RRG needs a per-instrument daily (RS-Ratio, RS-Momentum) state across an
11-member cross-section plus a cross-sectional rank join — a different data model, not
"one more pair." Also, `Sector_Rotation` is a live pipeline with a cron job, GitHub
Pages, and an Android app already depending on it; this repo is still being tuned
(Phase B) and shouldn't share a `requirements.txt`/CI change surface with something
already in daily use.

## Phase B: informal backtest results (read before trusting the "Improving" signal)

`backtest_rrg.py` (standalone, not part of `run_pipeline.py`/the exe; hits network for
8 years of daily data, resamples to weekly internally, ~5 min run) checks: after a
sector's quadrant changes, how did it do over the next N periods vs RSP? Two samplings
are computed — `all_days` (every day/week a sector sits in a quadrant) is included
mainly to show why it's misleading: consecutive periods in the same quadrant have
heavily overlapping forward-return windows, so a single multi-week trend gets counted
as dozens of "independent" rows. `entry_only` (just the period the quadrant changed)
is the one to trust.

**Round 1 (daily bars, 5-year sample)**: across 5 parameter variants (RSP/SPY
benchmark, window 42/63/84, momentum_lookback 5/10) and 4 forward horizons (5/10/20/40
trading days), `Improving`-quadrant entries showed at best a weak edge (~52-53% hit
rate at 5-10 day horizons) that faded or reversed by 20-40 days — and `Lagging`
entries matched or beat `Improving` in most variants, which runs counter to the
tool's premise.

**Round 2 (weekly bars, tried specifically because round 1's daily-bar granularity was
suspected as the culprit)**: resampled the same data to weekly (`close.resample("W-FRI")`)
and re-ran `compute_rrg()` unmodified — it's generic over "rows," so no signal-math
changes were needed, only the window/momentum_lookback units shift from days to weeks
(tested window 10/13/16 weeks, momentum_lookback 1/2 weeks, forward periods 2/4/8
weeks). **Weekly bars did not fix it** — `Improving` entries stayed flat-to-negative
(46-50% hit rate) across every weekly variant. The one config with a real, monotonic
edge across the whole exercise was plain `Leading` (already-strong sectors) at
window=16 weeks: 51.8%/51.8%/53.2% hit rate scaling *up* with the 2/4/8-week horizon —
i.e. simple momentum, not early rotation-catching, was the only thing that looked real.

**Round 3 (RankAccel filter, on the daily baseline)**: split `Improving` entries by
whether `RankAccel` was above/below its own median at entry, hypothesizing that a
sharper cross-sectional rank jump might be the "real" signal buried inside the noisier
full `Improving` set. Also inconclusive — the high-RankAccel half beat the low half at
a 5-day horizon but lost to it at 10- and 20-day horizons. No consistent split.

**Web research (two `fable`-model research agents, one on RRG's evidentiary basis, one
on data-source alternatives) explained *why*, not just confirmed the null result:**
RRG is not validated in peer-reviewed finance literature as an early-predictive
indicator — it's a technical-analysis/chart-vendor concept (StockCharts, Optuma,
TC2000), and even sympathetic sources concede it's coincident-to-lagging by
construction (e.g. IBKR's own glossary: "RS-Ratio and RS-Momentum are both derived
from historical price data that confirm trends already forming, rather than predict
reversals before any price data supports them"). The EMA smoothing that makes the
chart legible is *specifically* what eats the lead time — `Improving` can only flip
after the underlying ratio has already inflected, so by the time it fires the "early"
information is already gone. This is a structural property of the RS-Ratio/RS-Momentum
construction itself, not a parameter-tuning problem — which is consistent with rounds
1-3 all failing to find a fix via parameters. In contrast, the research surfaced real
peer-reviewed support for plain **industry/sector momentum at 6-12 month horizons**
(Moskowitz & Grinblatt, *Journal of Finance*, 1999; replicated e.g. in Quantpedia's
"Sector Momentum – Rotational System": 1928-2009, ~13.9% CAGR, Sharpe 0.54) — notably
the *same direction* round 2's best-performing variant (weekly, 16-week window) was
already pointing, before the literature search confirmed why.

**Decision (made with the user after all three rounds + the research)**: keep the RRG
chart as a visualization (still legible, still shows "where things are right now"),
but stop implying it has validated early-predictive power — quadrant-corner "★" and
"早期ローテーション候補" (early rotation candidate) wording were removed from
`plot_rrg.py` and `generate_situation_summary()`; the situation banner now explicitly
states the backtest found no consistent edge. **Added `compute_momentum_ranking()` +
`plot_momentum_ranking.py`** as the evidence-backed complementary view — plain 12-month
(252 trading day) trailing relative return, no smoothing, ranked. This is the view to
actually lean on; RRG is the (still useful, still kept) exploratory/visual companion.

**On sample-size honesty**: even round 1/2's "null" result isn't rock-solid — 5-8
years / ~300-450 entry events per quadrant per variant is not huge, and entries
cluster in time across sectors (a market-wide shock flips several sectors' quadrants
within days of each other), so the effective independent sample size is smaller than
the row count suggests. Don't over-read the null any more than the original "Improving"
claim should have been over-read — both are weakly-powered reads of ~1 market cycle.

## Planned phases (not yet built — check with the user before assuming these are wanted)
- **Phase B is functionally closed** (daily + weekly RRG tuning, RankAccel filtering,
  and external research all converged on the same "keep RRG as a visualization, lean
  on plain momentum for anything evidence-based" conclusion above) — further parameter
  search inside the RRG framework would mostly be curve-fitting to one historical
  sample, not a good use of effort without a genuinely different idea.
- **Phase C**: `generate_dashboard.py`-equivalent (banner + both charts combined) +
  `publish_latest.py` + `run_pipeline.py` + `.github/workflows/publish-rrg.yml`,
  mirroring `Sector_Rotation`'s CI/Pages/manifest shape exactly (same `_[0-9]*.png`
  glob-collision fix, same Noto-CJK-font CI step, same dual desktop/mobile PNG
  convention). Also a good point to reconsider the yfinance→Tiingo data-source
  research finding if reliability issues show up in CI (Tiingo has an official
  documented API and comfortable free-tier limits for this tool's ~13-ticker/day
  need; yfinance would stay as a fallback, not be fully dropped).
- **Phase D**: extend the *existing* `SectorRotationAndroid` app (new tab + second
  manifest fetch) rather than building a new app — the existing manifest-driven
  Coil/OkHttp/kotlinx.serialization plumbing is generic enough to reuse as-is.

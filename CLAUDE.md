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
**Phase A+B+C**: a PC-run pipeline (RRG chart + momentum-ranking chart + a combined
dashboard image) plus a CI/Pages publishing setup with a browsable archive of past
days (see "Phase C" below). **As of the Phase C code landing, the repo had not yet
been pushed to a GitHub remote** — it was built and tested entirely locally first,
deliberately, since turning on GitHub Actions + Pages means creating a public repo
and needs explicit user go-ahead (see "Phase C: publishing and archive" below for
what's still pending at that point). If you're reading this later and `git remote -v`
shows a real remote, that step has since happened — update this note if so, don't
leave it stale. Phase D (mobile app) is still not started.

All user-facing text (CLI output, chart labels, docs) is in Japanese.

## Commands

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

.\venv\Scripts\python.exe rrg_monitor.py             # 1. fetch prices, compute RS-Ratio/RS-Momentum + momentum ranking -> output/*.csv
.\venv\Scripts\python.exe plot_rrg.py                # 2a. render the RRG comet chart -> output/rrg_chart_*.png (+ sub 20d version)
.\venv\Scripts\python.exe plot_momentum_ranking.py   # 2b. render the 12-month momentum leaderboard -> output/momentum_ranking_chart_*.png
.\venv\Scripts\python.exe backtest_rrg.py               # optional: re-run RRG's informal backtest (daily + weekly variants, ~5 min, hits network for 8y of data)
.\venv\Scripts\python.exe backtest_momentum_ranking.py  # optional: simulate the top-N/monthly-rebalance rule -> output/momentum_backtest_results_*.csv

# or run the daily publish pipeline in one go (this is what CI runs too):
.\venv\Scripts\python.exe run_pipeline.py         # steps 1-2b above, in one process -> output/*
.\venv\Scripts\python.exe generate_dashboard.py   # composite RRG chart + momentum chart -> output/dashboard_*.png
.\venv\Scripts\python.exe publish_latest.py       # -> public/latest_*.png + public/latest.json, and archive/YYYY-MM-DD/ (see "Phase C" below)
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

## Phase B closing check: does the momentum ranking actually work on *this* universe?

Everything backing `plot_momentum_ranking.py` up to this point was someone else's
research on a different (broader, longer-history) universe — Moskowitz & Grinblatt
and Quantpedia's replication used the whole stock market / a 1928-2009 sample, not
specifically these 11 Sector SPDRs over the recent yfinance-reachable period. That gap
was closed with `backtest_momentum_ranking.py`: simulates the exact rule printed on
the chart's own "活用方法" box (top-3 or top-4 sectors by trailing 12-month return,
equal-weighted, rebalanced monthly) against 10 years of this tool's own data, and
compares to RSP buy-and-hold.

**Result (10y period, 108 simulated months after the 12-month lookback warmup):**

| Strategy | CAGR | Annualized Vol | Simple Sharpe | Max Drawdown |
|---|---|---|---|---|
| RSP buy-and-hold (benchmark) | +11.67% | 16.57% | 0.75 | -26.68% |
| Top 3, monthly rebalance | +15.31% | 14.92% | 1.03 | -17.97% |
| Top 4, monthly rebalance | +14.86% | 14.24% | 1.05 | -16.35% |

Both variants beat the benchmark on every axis tested — higher CAGR, lower vol,
meaningfully smaller max drawdown, better Sharpe. This is the one part of the whole
Phase B effort where this tool's *own* data confirmed rather than merely cited
someone else's result. Same caveats as everywhere else in Phase B apply though: no
transaction costs/slippage modeled, Sharpe here is a simplified return/vol ratio (no
risk-free subtraction), and 108 months is still roughly one market cycle — don't read
this as proof the edge persists in a genuinely different regime, just as a real (not
just imported) supporting data point for the direction Phase B ended up recommending.

**Japan capital-gains-tax follow-up**: the pre-tax numbers above ignore that monthly
rebalancing repeatedly *realizes* gains (taxed immediately, 20.315% for a Japanese
retail investor in a taxable account, no NISA/loss-carryforward modeled), while
RSP buy-and-hold defers all tax to one final sale — a real, non-trivial difference in
compounding base over time, not just a flat haircut. `backtest_momentum_ranking.py`
models two scenarios: `apply_monthly_tax()` (conservative — assumes 100% portfolio
turnover every month, i.e. even continuing top-N members get fully sold and rebought
to reset to equal weight, matching what `simulate_top_n()`'s "recompute equal-weight
every month" pre-tax model implicitly assumes) and
`simulate_top_n_minimal_turnover_after_tax()` (realistic — only sells tickers that
actually drop out of the top-N that month, tracks per-ticker cost basis, continuing
positions stay unsold/untaxed/unrebalanced).

| Strategy | Pre-tax CAGR | After-tax (conservative: full monthly turnover) | After-tax (realistic: only sell what's replaced) |
|---|---|---|---|
| RSP buy-and-hold | +11.67% | +10.05% (taxed once, at the end) | same |
| Top 3, monthly | +15.30% | +9.06% | **+11.44%** |
| Top 4, monthly | +14.86% | +8.80% | **+10.85%** |

**Under the conservative (100%-turnover) tax assumption, RSP buy-and-hold actually
wins after tax** — the pre-tax edge is more than erased by the repeated-realization
tax drag. **Under the realistic (minimal-turnover) tax assumption, the momentum
ranking still wins after tax, but the margin shrinks a lot**: from a ~3.2-3.6pp
pre-tax edge down to a ~0.8-1.4pp after-tax edge. Practical takeaway to keep in any
future user-facing text about this: the edge is real but thin after Japanese capital
gains tax, and *how much you actually trade* (not just which sectors you pick)
materially affects whether the strategy is worth it over simple buy-and-hold — don't
present the pre-tax backtest numbers on their own without this caveat.

## Planned phases (not yet built — check with the user before assuming these are wanted)
- **Phase B is now fully closed**, including the momentum-ranking self-check above —
  daily + weekly RRG tuning, RankAccel filtering, external research, and the
  momentum-ranking backtest on this tool's own universe all converged on the same
  "keep RRG as a visualization, lean on the momentum ranking for anything
  evidence-based" conclusion. Further parameter search inside the RRG framework
  would mostly be curve-fitting to one historical sample, not a good use of effort
  without a genuinely different idea.
- **Phase C code is built and locally tested; publishing (remote push, Pages, CI)
  was deliberately left for explicit user go-ahead** — see "Phase C: publishing and
  archive" below for the architecture and what specifically remains.
- **Phase D**: extend the *existing* `SectorRotationAndroid` app (new tab + second
  manifest fetch) rather than building a new app — the existing manifest-driven
  Coil/OkHttp/kotlinx.serialization plumbing is generic enough to reuse as-is.

## Phase C: publishing and archive

Unlike `Sector_Rotation`'s Pages setup (which only ever shows the single latest
dashboard — old runs are simply overwritten), this repo's Phase C explicitly adds a
**browsable history of past days**, per user request. That's the one meaningful
divergence from mirroring `Sector_Rotation`'s CI/Pages shape 1:1 — everything else
(cron schedule shape, Noto-CJK-font CI step, `_[0-9]*.png` digit-anchored globs,
`workflow_dispatch` + weekday cron trigger) follows the sibling repo's
already-battle-tested pattern directly.

### New scripts
- **`generate_dashboard.py`**: does *not* build a new matplotlib figure. It PIL-composites
  the already-rendered `rrg_chart_*.png` and `momentum_ranking_chart_*.png` into one
  vertically-stacked `dashboard_*.png`, resizing both to a common width first (they're
  naturally different widths — the RRG chart and the momentum bar chart have
  unrelated content, so equal widths were never guaranteed). This deliberately reuses
  each chart's own already-verified layout (banner, legend, wrapping) rather than
  risking new layout bugs by re-deriving a combined figure from scratch. `load_jp_font()`
  hunts the same font-name candidates matplotlib uses so the PIL-drawn banner title
  doesn't tofu-box on `ubuntu-latest` (falls back to Pillow's non-CJK default font
  silently if none are found, rather than crashing — acceptable since it's just the
  banner headline, not the charts themselves, that would be affected).
- **`run_pipeline.py`**: `rrg_monitor` → `plot_rrg` → `plot_momentum_ranking` in one
  process, mirroring `Sector_Rotation/run_pipeline.py`'s structure exactly (same
  `SystemExit`-code-checking loop). Does **not** include `generate_dashboard.py` or
  `publish_latest.py` as pipeline steps — those come after, as separate CI steps —
  and does **not** include either `backtest_*.py` script (those are occasional manual
  checks with multi-minute network calls, not part of the daily run).
- **`publish_latest.py`**: writes the usual `public/latest_*.png` + `public/latest.json`
  (same shape as `Sector_Rotation`'s), *plus* archiving logic — see below.

### Archive design (the reason Phase C's publish step differs from the sibling repo)
`Sector_Rotation`'s Pages deploy (`actions/upload-pages-artifact` + `deploy-pages`)
**replaces the entire site on every run** — there is no way to accumulate history
purely on the Pages side. To keep a browsable past, the history has to live somewhere
that persists *between* CI runs on its own: the git repository itself.

- **`archive/YYYY-MM-DD/`** is a normal tracked directory in this repo (deliberately
  *not* gitignored — see the comment in `.gitignore` warning against adding it).
  Each day, `add_to_archive()` copies that day's dated output files into it under
  fixed names (`rrg_chart.png`, `dashboard.png`, `rrg_data.csv`, etc.).
- **Retention policy** (`apply_retention_policy()`, user-specified): the most recent
  `FULL_RETENTION_DAYS` (180) are kept as one folder per day. Older than that, entries
  are thinned to **one per calendar month** (the last date recorded that month) —
  older groups are found via `(reference_date - d).days > 180`, grouped by
  `(year, month)`, and every date in a group except the max is `shutil.rmtree`'d. This
  runs on *every* `publish_latest.py` call, so thinning happens gradually as dates
  age past the 180-day line, not as a one-time migration.
- **`build_archive_index()`** regenerates `archive/index.html` (plain links, no JS)
  from whatever date folders currently exist — always a fresh reflection of on-disk
  state, not an incrementally-maintained list, so it can't drift out of sync.
- **`copy_archive_into_public()`** copies the (now-updated) `archive/` into
  `public/archive/` as the last publish step, so the *single* Pages artifact built
  from `public/` each run contains both the latest files and the full archive.
  `public/` itself stays gitignored/ephemeral as before — only `archive/` (the
  git-tracked source of truth) needs to survive between runs.
- **The CI workflow commits `archive/` back to the repo** (`git add archive/ && git
  commit && git push`, using the default `GITHUB_TOKEN` with `contents: write` — no
  extra secrets needed) *before* the Pages artifact upload step, so each day's commit
  is what the next run's `actions/checkout` will see. This is the one meaningful
  structural difference from `Sector_Rotation`'s workflow (`permissions: contents:
  read` there vs. `contents: write` here).

### What was intentionally deferred, and why
- **Not yet pushed to a GitHub remote.** Creating a new public repo (GitHub Pages on
  the Free plan requires public, same constraint hit in `Sector_Rotation`) and
  pushing code is a real, externally-visible, hard-to-fully-reverse action — it was
  built and fully tested locally first (`run_pipeline.py` → `generate_dashboard.py` →
  `publish_latest.py`, including a synthetic-old-dates test of the retention/thinning
  logic before reverting the test data) specifically so that step could be a single,
  reviewable go/no-go decision rather than something silently bundled into "build
  Phase C."
- **Tiingo migration** (flagged as a good Phase C moment in the Phase B web research)
  was not done — `yfinance` is still the only data source. Revisit only if CI actually
  hits reliability problems; don't switch preemptively without a concrete failure.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal analysis tool that tracks money rotation across all 11 S&P 500 GICS sectors
(via the Sector SPDR ETFs) and tries to catch **early** signs of which sector is about
to receive the next wave of inflows — using a Relative Rotation Graph (RRG) approach
(JdK RS-Ratio / RS-Momentum, quadrant classification) rather than the lagging
moving-average-crossover approach used in the sibling project `Sector_Rotation`.

This is a deliberate sibling/successor to `Sector_Rotation` (same machine, directory
`../Sector_Rotation`), not a fork of it — see "Why a separate repo" below. Currently
**Phase A only**: a PC-run pipeline that produces one RRG chart. No CI, no publishing,
no mobile app yet (see "Planned phases" below).

All user-facing text (CLI output, chart labels, docs) is in Japanese.

## Commands

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

.\venv\Scripts\python.exe rrg_monitor.py   # 1. fetch prices, compute RS-Ratio/RS-Momentum -> output/*.csv
.\venv\Scripts\python.exe plot_rrg.py      # 2. render the RRG comet chart -> output/rrg_chart_*.png
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
- The window/lookback constants in `CONFIG` are explicitly a starting point to be
  tuned against real data in Phase B, not settled values — don't treat them as fixed
  when iterating.

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

## Planned phases (not yet built — check with the user before assuming these are wanted)
- **Phase B**: tune `window`/`momentum_lookback`/`tail_days`/RSP-vs-SPY based on real
  data, add a leaderboard view of `RankAccel`, informal backtest against known past
  rotations.
- **Phase C**: `generate_dashboard.py` (banner + leaderboard image) + `publish_latest.py`
  + `run_pipeline.py` + `.github/workflows/publish-rrg.yml`, mirroring
  `Sector_Rotation`'s CI/Pages/manifest shape exactly (same `_[0-9]*.png` glob-collision
  fix, same Noto-CJK-font CI step, same dual desktop/mobile PNG convention).
- **Phase D**: extend the *existing* `SectorRotationAndroid` app (new tab + second
  manifest fetch) rather than building a new app — the existing manifest-driven
  Coil/OkHttp/kotlinx.serialization plumbing is generic enough to reuse as-is.

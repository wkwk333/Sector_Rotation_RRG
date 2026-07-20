# -*- coding: utf-8 -*-
"""
backtest_rrg.py
================
rrg_monitor.py のRS-Ratio/RS-Momentum/象限判定ロジックを、複数年の実データに
対して適用し、「その日(週)どの象限に入ったセクターが、その後どれだけ相対的に
値動きしたか」を集計する簡易バックテスト。

目的は3つ:
  1. 健全性チェック: そもそもこの手法に意味があるか
     (Improving象限に入ったセクターは、その後の相対リターンが他の象限より
     良い傾向にあるか。逆に、Leadingで既に強いセクターを買うのと比べて
     「早期に拾う」ことに優位性があるか)
  2. パラメータ比較: ベンチマーク(RSP/SPY)・窓幅(window)・モメンタム
     算出期間(momentum_lookback)を変えたときに、シグナルの効き方がどう
     変わるか
  3. 足の粒度比較: 日足 vs 週足。JdKのRRGは元々、S&P500セクターのような
     マクロ・ローテーション用途では週足で運用されるのが一般的な流儀
     (このツールは日足で実装している)。日足バックテスト(初回)では
     Improving象限の優位性がはっきり確認できなかったため、足の粒度自体が
     ミスマッチという仮説を検証する。

これは正式なウォークフォワード検証やパラメータ最適化ではなく、Phase Aの
計画で明記した「簡易バックテスト」。過去数年分・1回きりの集計であり、
将来の性能を保証しない。パラメータをこの結果に過剰に最適化(カーブ
フィッティング)しないよう、明らかな差が出た場合のみCONFIGを見直す方針。

象限の判定に使うベンチマーク(variantごとにRSP/SPYを切り替える)と、
その後の実績を測る評価用ベンチマークは別物であることに注意。評価は常に
RSP基準に固定している — SPY判定シグナルの評価にもSPYを使うと、
「XLK自身がSPYの大部分を占めるため、XLKの相対強度が薄まる」という
rrg_monitor.py側で避けている歪みを、評価の側で再び持ち込んでしまうため。

週足はcompute_rrg()・compute_forward_relative_return()どちらも「行=1本の
バー」という前提だけで書かれているため、日次DataFrameを週足にリサンプルして
同じ関数にそのまま渡すだけで計算できる(専用の週足ロジックは書いていない)。

実行方法(rrg_monitor.py / plot_rrg.py とは独立に単独実行できる):
    python backtest_rrg.py

出力:
    ./output/backtest_results_YYYYMMDD.csv (パラメータ・足種別・象限別の集計結果)
    コンソールにも同じ内容を表示する
"""

import console_utf8  # noqa: F401  (文字化け対策。最初にimportする)

import os
import sys
import traceback
from datetime import datetime

import pandas as pd

from rrg_monitor import CONFIG, download_prices, compute_rrg

BACKTEST_CONFIG = {
    # 判定用データの取得期間。週足側で「2*window週」程度のウォームアップを
    # 消費してもなお十分なentryイベント数が残るよう、5y→8yに延長した。
    # XLC(通信サービス)の設定日が2018年6月なので、8y取得時の最初の数週間は
    # XLCだけ欠けるが、compute_rrg側のmin_periods処理で自然にNaN扱いされる
    # だけで、他銘柄の計算には影響しない。
    "period": "8y",
    # 評価(その後の実績測定)は常にこのベンチマーク基準に固定する。
    # シグナル生成側のbenchmarkとは独立(上のdocstring参照)。
    "eval_benchmark": "RSP",
    # 日足: 5/10/20/40営業日で確認したところ、Improving象限のentry_only
    # 勝率は5-10営業日で52-53%、20-40営業日で46-50%とむしろ短期の方がマシ
    # だった。その4本すべてを再掲して足の粒度比較の材料にする。
    "daily_forward_periods": [5, 10, 20, 40],
    "daily_variants": [
        {"name": "daily baseline (RSP, window=63, momentum=5)", "benchmark": "RSP", "window": 63, "momentum_lookback": 5},
        {"name": "daily benchmark=SPY (window=63, momentum=5)", "benchmark": "SPY", "window": 63, "momentum_lookback": 5},
        {"name": "daily window=42 (RSP, momentum=5)", "benchmark": "RSP", "window": 42, "momentum_lookback": 5},
        {"name": "daily window=84 (RSP, momentum=5)", "benchmark": "RSP", "window": 84, "momentum_lookback": 5},
        {"name": "daily momentum_lookback=10 (RSP, window=63)", "benchmark": "RSP", "window": 63, "momentum_lookback": 10},
    ],
    # 週足: window/momentum_lookbackの単位は「週」。63営業日(約12.6週)に
    # 相当する13週を基準とし、momentum_lookback=1週(直近1週間の変化)を既定
    # とする。forward_periodsも週単位(2/4/8週 ≈ 日足の10/20/40営業日相当)。
    "weekly_forward_periods": [2, 4, 8],
    "weekly_variants": [
        {"name": "weekly baseline (RSP, window=13w, momentum=1w)", "benchmark": "RSP", "window": 13, "momentum_lookback": 1},
        {"name": "weekly window=10w (RSP, momentum=1w)", "benchmark": "RSP", "window": 10, "momentum_lookback": 1},
        {"name": "weekly window=16w (RSP, momentum=1w)", "benchmark": "RSP", "window": 16, "momentum_lookback": 1},
        {"name": "weekly momentum=2w (RSP, window=13w)", "benchmark": "RSP", "window": 13, "momentum_lookback": 2},
    ],
}

QUADRANT_ORDER = ["Leading", "Improving", "Weakening", "Lagging"]


def compute_forward_relative_return(
    close: pd.DataFrame, eval_benchmark: str, forward_periods: int, tickers: list
) -> pd.DataFrame:
    """
    各(Date, Symbol)について、そこからforward_periods本先までの
    「対eval_benchmark 相対リターン(差分近似、pp)」をlong形式で返す。
    closeの行が営業日でも週足でも、forward_periodsは常に「行数」として
    扱われる(日足なら営業日数、週足なら週数)。
    """
    bench = close[eval_benchmark]
    bench_fwd = bench.shift(-forward_periods) / bench - 1

    records = []
    for t in tickers:
        if t not in close.columns:
            print(f"[警告] {t} の価格データが無いため、評価対象から除外します。")
            continue
        sec_fwd = close[t].shift(-forward_periods) / close[t] - 1
        rel_fwd = sec_fwd - bench_fwd
        records.append(pd.DataFrame({
            "Date": close.index, "Symbol": t, "FwdRelReturn": rel_fwd.values,
        }))
    return pd.concat(records, ignore_index=True)


def _agg_fwd_return(merged: pd.DataFrame) -> pd.DataFrame:
    grouped = merged.groupby("Quadrant")["FwdRelReturn"].agg(
        平均pp=lambda s: s.mean() * 100,
        中央値pp=lambda s: s.median() * 100,
        勝率percent=lambda s: (s > 0).mean() * 100,
        件数="count",
    )
    return grouped.reindex(QUADRANT_ORDER)


def summarize_by_quadrant(long_df: pd.DataFrame, fwd_df: pd.DataFrame):
    """
    象限ごとに、その後の相対リターンの平均・中央値・勝率・件数を集計する。
    「その象限に留まっている全期間」を対象にした集計(all_days)に加えて、
    「その象限に入った当日/当週だけ」(entry_only)も別途返す。

    all_daysは、同じ銘柄が何週間も同じ象限に留まると、予測期間が大きく
    重複した非独立なサンプルで件数が水増しされる問題がある(1つのトレンドを
    何十行にも分解して数えてしまう)。entry_onlyは象限が切り替わった
    タイミングだけを見るため、この重複の影響が小さく、「シグナル発生時に
    動いたらどうなるか」というこのツールの実際の使われ方に近い。
    """
    merged = long_df.merge(fwd_df, on=["Date", "Symbol"], how="left")
    merged = merged.dropna(subset=["Quadrant", "FwdRelReturn"])

    all_days = _agg_fwd_return(merged)

    merged_sorted = merged.sort_values(["Symbol", "Date"])
    prev_quadrant = merged_sorted.groupby("Symbol")["Quadrant"].shift(1)
    is_entry = merged_sorted["Quadrant"] != prev_quadrant
    entry_only = _agg_fwd_return(merged_sorted[is_entry])

    return all_days, entry_only


def run_variant_group(close, variants, forward_periods_list, sector_tickers, eval_benchmark, bar_label):
    """
    variants(パラメータ違いのリスト)×forward_periods_list(評価期間違いの
    リスト)の全組み合わせについて、compute_rrg -> 象限別集計までを実行する。
    compute_rrg自体はforward_periodsに依存しないため、variantごとに1回だけ
    呼び、forward_periods_listはその結果を使い回して評価だけ繰り返す。
    """
    all_rows = []
    for variant in variants:
        long_df = compute_rrg(
            close,
            benchmark=variant["benchmark"],
            window=variant["window"],
            momentum_lookback=variant["momentum_lookback"],
        )
        print(f"\n--- {variant['name']} ---")
        for fp in forward_periods_list:
            fwd_df = compute_forward_relative_return(close, eval_benchmark, fp, sector_tickers)
            all_days, entry_only = summarize_by_quadrant(long_df, fwd_df)

            entry_only_named = entry_only.reset_index().rename(columns={"index": "Quadrant"})
            entry_only_named.insert(0, "forward_periods", f"{fp}{bar_label}")
            entry_only_named.insert(0, "sample", "entry_only")
            entry_only_named.insert(0, "variant", variant["name"])
            all_rows.append(entry_only_named)

            all_days_named = all_days.reset_index().rename(columns={"index": "Quadrant"})
            all_days_named.insert(0, "forward_periods", f"{fp}{bar_label}")
            all_days_named.insert(0, "sample", "all_days")
            all_days_named.insert(0, "variant", variant["name"])
            all_rows.append(all_days_named)

            print(f"  [forward={fp}{bar_label} / entry_only]")
            print(
                entry_only_named.drop(columns=["variant", "sample", "forward_periods"])
                .round(2).to_string(index=False)
                .replace("\n", "\n    ")
            )
    return all_rows


def main():
    try:
        print("=" * 70)
        print("RRG 簡易バックテスト (日足 / 週足)")
        print(f"  取得期間: {BACKTEST_CONFIG['period']}")
        print(f"  評価ベンチマーク(共通): {BACKTEST_CONFIG['eval_benchmark']}")
        print("=" * 70)

        sector_tickers = [s["ticker"] for s in CONFIG["sectors"]]
        all_tickers = sorted(set(sector_tickers) | {"RSP", "SPY"})
        close_daily = download_prices(all_tickers, BACKTEST_CONFIG["period"])
        print(f"[情報] 日足データ取得完了: {close_daily.shape[0]}営業日 × {close_daily.shape[1]}銘柄")

        close_weekly = close_daily.resample("W-FRI").last()
        close_weekly.index.name = "Date"
        print(f"[情報] 週足にリサンプル完了: {close_weekly.shape[0]}週 × {close_weekly.shape[1]}銘柄")

        print("\n" + "=" * 30 + " 日足 " + "=" * 30)
        daily_rows = run_variant_group(
            close_daily, BACKTEST_CONFIG["daily_variants"], BACKTEST_CONFIG["daily_forward_periods"],
            sector_tickers, BACKTEST_CONFIG["eval_benchmark"], bar_label="d",
        )

        print("\n" + "=" * 30 + " 週足 " + "=" * 30)
        weekly_rows = run_variant_group(
            close_weekly, BACKTEST_CONFIG["weekly_variants"], BACKTEST_CONFIG["weekly_forward_periods"],
            sector_tickers, BACKTEST_CONFIG["eval_benchmark"], bar_label="w",
        )

        combined = pd.concat(daily_rows + weekly_rows, ignore_index=True)
        stamp = datetime.now().strftime("%Y%m%d")
        out_path = os.path.join(CONFIG["output_dir"], f"backtest_results_{stamp}.csv")
        os.makedirs(CONFIG["output_dir"], exist_ok=True)
        combined.to_csv(out_path, encoding="utf-8-sig", index=False)
        print(f"\n[完了] 結果を保存しました: {out_path}")
        print(
            "\n[読み方の注意] これは簡易バックテストであり、過去数年・1回きりの集計です。"
            "パラメータをこの結果だけに過剰最適化しないこと。"
        )

    except Exception as e:
        print("\n[エラー] 処理が中断されました。")
        print(f"  内容: {e}")
        print("  --- 詳細トレースバック ---")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

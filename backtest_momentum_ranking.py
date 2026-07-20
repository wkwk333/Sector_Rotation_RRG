# -*- coding: utf-8 -*-
"""
backtest_momentum_ranking.py
==============================
plot_momentum_ranking.py の「活用方法」欄で案内している運用ルール
(上位N銘柄を均等保有し、月次でリバランス)を、このツール自身の
11セクターSPDRの実データに対してシミュレーションし、累積リターン・CAGR・
シャープレシオ・最大ドローダウンをRSP買い持ちと比較する。

Moskowitz & Grinblatt (1999) やQuantpedia「Sector Momentum - Rotational
System」(1928-2009年、米国株全体が対象)は他人の研究・他のユニバースでの
結果であり、このツール固有の「11セクターSPDR・直近10年」という条件でも
同じように機能するかはこれまで未検証だった。backtest_rrg.py がRRG側の
簡易バックテストだったのに対し、これはモメンタムランキング側の簡易
バックテストで、Phase Bの最後の検証項目にあたる。

手法:
    各月末時点で、直近lookback_monthsヶ月(既定12ヶ月)の月次トレイリング
    リターンで全セクターを順位付けし、上位top_n銘柄を均等保有。
    翌月末まで保有してそのリターンを記録し、翌月末に再度順位付けして
    入れ替える(=月次リバランス)。これをデータ全期間で繰り返して連結し、
    CAGR・年率ボラティリティ・シャープレシオ・最大ドローダウンを求める。

    XLC(通信サービス、2018年設定)のように取得期間中に未上場の月がある
    銘柄は、その月のランキング対象から自然に除外される(simulate_top_n内で
    NaNの銘柄をスキップするだけで、期間全体をXLC上場後に絞るような特別
    処理はしていない)。

これも簡易バックテストであり、取引コスト・スリッページ・税金・配当再投資の
細部は考慮していない。過去のある1期間の結果であり、将来の性能を保証しない。
シャープレシオも無リスク金利を引かない簡易版(平均超過リターン/ボラティリティ
ではなく、平均リターン/ボラティリティ)であることに注意。

実行方法(rrg_monitor.py / backtest_rrg.py とは独立に単独実行できる):
    python backtest_momentum_ranking.py

出力:
    ./output/momentum_backtest_results_YYYYMMDD.csv
    コンソールにも同じ内容を表示する
"""

import console_utf8  # noqa: F401  (文字化け対策。最初にimportする)

import os
import sys
import traceback
from datetime import datetime

import numpy as np
import pandas as pd

from rrg_monitor import CONFIG, download_prices

BACKTEST_CONFIG = {
    # yfinanceで安定して取れる範囲でできるだけ長く取る。XLC(2018年設定)は
    # この期間の前半は自然に対象外になるだけで、エラーにはならない。
    "period": "10y",
    "lookback_months": 12,
    # plot_momentum_ranking.pyの活用方法欄で案内している「上位3〜4銘柄」と
    # 揃える — 実際に案内している運用ルールをそのまま検証するため。
    "top_n_variants": [3, 4],
}


def build_monthly_close(close: pd.DataFrame) -> pd.DataFrame:
    """日次終値を月末値にリサンプルする(月次リバランスのシミュレーション用)。"""
    monthly = close.resample("ME").last()
    monthly.index.name = "Date"
    return monthly


def simulate_top_n(
    monthly: pd.DataFrame, sector_tickers: list, lookback_months: int, top_n: int,
) -> pd.DataFrame:
    """
    各月末に、直近lookback_monthsヶ月のトレイリングリターン上位top_n銘柄を
    均等保有したと仮定し、翌月のポートフォリオリターンを月次で記録する。
    """
    records = []
    n_rows = len(monthly)
    for i in range(lookback_months, n_rows - 1):
        base = monthly.iloc[i - lookback_months]
        latest = monthly.iloc[i]
        nxt = monthly.iloc[i + 1]

        trailing_returns = {}
        for t in sector_tickers:
            if t not in monthly.columns:
                continue
            b, l = base.get(t), latest.get(t)
            if pd.isna(b) or pd.isna(l):
                continue
            trailing_returns[t] = l / b - 1

        if len(trailing_returns) < top_n:
            continue  # まだ十分な銘柄が上場していない月(例: XLC設定前)はスキップ

        ranked = sorted(trailing_returns.items(), key=lambda kv: kv[1], reverse=True)
        selected = [t for t, _ in ranked[:top_n]]

        fwd_returns = []
        for t in selected:
            p_now, p_next = latest.get(t), nxt.get(t)
            if pd.isna(p_now) or pd.isna(p_next):
                continue
            fwd_returns.append(p_next / p_now - 1)
        if not fwd_returns:
            continue

        records.append({
            "Date": monthly.index[i + 1],
            "PortfolioReturn": float(np.mean(fwd_returns)),
            "Selected": ",".join(selected),
        })

    return pd.DataFrame(records)


def compute_stats(returns: pd.Series, periods_per_year: int = 12) -> dict:
    """月次リターン列からCAGR・年率ボラティリティ・簡易シャープ・最大DDを求める。"""
    returns = returns.dropna()
    n = len(returns)
    if n == 0:
        return {"CAGR": np.nan, "Vol": np.nan, "Sharpe": np.nan, "MaxDrawdown": np.nan, "件数": 0}

    cum = (1 + returns).cumprod()
    total_return = cum.iloc[-1] - 1
    years = n / periods_per_year
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else np.nan

    vol = returns.std() * np.sqrt(periods_per_year)
    sharpe = (returns.mean() * periods_per_year) / vol if vol and vol > 0 else np.nan

    running_max = cum.cummax()
    drawdown = cum / running_max - 1
    max_dd = drawdown.min()

    return {"CAGR": cagr, "Vol": vol, "Sharpe": sharpe, "MaxDrawdown": max_dd, "件数": n}


def print_stats(label: str, stats: dict):
    print(f"--- {label} ---")
    print(
        f"  CAGR: {stats['CAGR']*100:+.2f}%  年率ボラティリティ: {stats['Vol']*100:.2f}%  "
        f"簡易シャープレシオ: {stats['Sharpe']:.2f}  最大ドローダウン: {stats['MaxDrawdown']*100:.2f}%  "
        f"サンプル数: {stats['件数']}ヶ月"
    )


def main():
    try:
        print("=" * 70)
        print("モメンタムランキング運用ルールの簡易バックテスト (上位N銘柄・月次リバランス)")
        print(f"  取得期間: {BACKTEST_CONFIG['period']} / トレイリング期間: {BACKTEST_CONFIG['lookback_months']}ヶ月")
        print(f"  検証する上位銘柄数: {BACKTEST_CONFIG['top_n_variants']}")
        print("=" * 70)

        sector_tickers = [s["ticker"] for s in CONFIG["sectors"]]
        benchmark = CONFIG["benchmark"]
        all_tickers = sorted(set(sector_tickers) | {benchmark})
        close = download_prices(all_tickers, BACKTEST_CONFIG["period"])
        print(f"[情報] 価格データ取得完了: {close.shape[0]}営業日 × {close.shape[1]}銘柄")

        monthly = build_monthly_close(close)
        print(f"[情報] 月次にリサンプル完了: {monthly.shape[0]}ヶ月分\n")

        bench_returns = monthly[benchmark].pct_change().dropna()
        bench_stats = compute_stats(bench_returns)
        print_stats(f"ベンチマーク: {benchmark} 買い持ち", bench_stats)

        all_rows = [{"variant": f"benchmark_{benchmark}", **bench_stats}]

        for top_n in BACKTEST_CONFIG["top_n_variants"]:
            sim = simulate_top_n(monthly, sector_tickers, BACKTEST_CONFIG["lookback_months"], top_n)
            print()
            if sim.empty:
                print(f"--- 上位{top_n}銘柄・月次リバランス ---\n  [警告] シミュレーション結果が空です。")
                continue
            stats = compute_stats(sim["PortfolioReturn"])
            print_stats(f"上位{top_n}銘柄・月次リバランス", stats)
            all_rows.append({"variant": f"top_{top_n}", **stats})

        result_df = pd.DataFrame(all_rows)
        stamp = datetime.now().strftime("%Y%m%d")
        out_path = os.path.join(CONFIG["output_dir"], f"momentum_backtest_results_{stamp}.csv")
        os.makedirs(CONFIG["output_dir"], exist_ok=True)
        result_df.to_csv(out_path, encoding="utf-8-sig", index=False)
        print(f"\n[完了] 結果を保存しました: {out_path}")
        print(
            "\n[読み方の注意] 取引コスト・スリッページ・税金は考慮していない簡易バックテストです。"
            "シャープレシオも無リスク金利を引かない簡易版です。過去1期間の結果であり、"
            "将来の性能を保証しません。"
        )

    except Exception as e:
        print("\n[エラー] 処理が中断されました。")
        print(f"  内容: {e}")
        print("  --- 詳細トレースバック ---")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
